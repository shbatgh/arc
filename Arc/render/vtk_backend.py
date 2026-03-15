"""VTK render backend — Python port of arc-c++/src/render/vtk/vtk_render_backend.cpp."""

from __future__ import annotations

import math
from typing import Callable

import numpy as np
from PySide6.QtWidgets import QWidget
from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkCellPicker,
    vtkPolyDataMapper,
    vtkRenderer,
)

from Arc.app.viewport import ViewportWidget
from Arc.core.render_types import (
    CameraMode,
    CellStyle,
    PrimitiveType,
    RenderCellMesh,
    RenderFrame,
    RenderInitOptions,
    RenderScene,
)
from Arc.render.vtk_interactor import BlenderLikeInteractorStyle

# -- Vector math helpers (port of vtk_render_backend.cpp anonymous namespace) --


def _vec(p) -> np.ndarray:
    return np.array(p, dtype=np.float64)


def _norm(v: np.ndarray) -> float:
    return float(np.linalg.norm(v))


def _normalize(v: np.ndarray) -> np.ndarray:
    n = _norm(v)
    return v / n if n > 1e-12 else np.zeros(3)


def _rotate_axis_angle(vec: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    u = _normalize(axis)
    c, s = math.cos(angle), math.sin(angle)
    return vec * c + np.cross(u, vec) * s + u * np.dot(u, vec) * (1.0 - c)


class VtkRenderBackend:
    """VTK-based render backend implementing the IRenderBackend protocol."""

    def __init__(self):
        self.on_cell_picked: Callable[[str], None] | None = None
        self.on_frame_ready: Callable[[int], None] | None = None

        self._viewport: ViewportWidget | None = None
        self._renderer: vtkRenderer | None = None
        self._picker: vtkCellPicker | None = None
        self._init_options = RenderInitOptions()

        self._scene: RenderScene | None = None
        self._frames_by_tp: dict[int, RenderFrame] = {}
        self._active_timepoint: int = 0
        self._wireframe_enabled: bool = False
        self._camera_mode = CameraMode.Orbit

        self._actors_by_cell: dict[str, vtkActor] = {}
        self._cell_by_actor: dict[int, str] = {}

        self._move_speed: float = 5.0
        self._rotate_speed_deg: float = 5.0
        self._orientation_widget = None

    def initialize(self, host: QWidget, options: RenderInitOptions) -> bool:
        self._init_options = options
        self._viewport = ViewportWidget(host)

        layout = host.layout()
        if layout is None:
            from PySide6.QtWidgets import QVBoxLayout

            layout = QVBoxLayout(host)
            layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._viewport)

        self._renderer = vtkRenderer()
        bg = self._init_options.background
        self._renderer.SetBackground(bg[0], bg[1], bg[2])
        self._viewport.render_window().AddRenderer(self._renderer)

        self._picker = vtkCellPicker()
        self._picker.SetTolerance(0.0005)

        interactor = self._viewport.interactor()
        if interactor is not None:
            style = BlenderLikeInteractorStyle()
            interactor.SetInteractorStyle(style)
            interactor.AddObserver("LeftButtonPressEvent", self._on_left_button_press)
            interactor.AddObserver("KeyPressEvent", self._on_key_press)
            interactor.AddObserver("CharEvent", self._on_char_event, -1.0)
            interactor.AddObserver("InteractionEvent", self._on_interaction)

        from vtkmodules.vtkInteractionWidgets import vtkCameraOrientationWidget

        self._orientation_widget = vtkCameraOrientationWidget()
        self._orientation_widget.SetParentRenderer(self._renderer)
        self._orientation_widget.SetAnimate(True)
        rep = self._orientation_widget.GetRepresentation()
        rep.AnchorToUpperRight()
        self._orientation_widget.SetInteractor(interactor)
        self._orientation_widget.EnabledOn()

        self._viewport.start()
        self._viewport.setFocus()
        return True

    def shutdown(self) -> None:
        self._clear_actors()
        self._orientation_widget = None
        self._picker = None
        self._renderer = None
        self._viewport = None

    def set_scene(self, scene: RenderScene) -> None:
        self._scene = scene
        self._frames_by_tp = {f.timepoint: f for f in scene.frames}

        if self._frames_by_tp and self._active_timepoint not in self._frames_by_tp:
            self._active_timepoint = min(self._frames_by_tp.keys())

        self._rebuild_active_frame()

    def set_timepoint(self, timepoint: int) -> None:
        self._active_timepoint = timepoint
        self._rebuild_active_frame()
        if self.on_frame_ready:
            self.on_frame_ready(self._active_timepoint)

    def update_cell_style(self, cell_id: str, style: CellStyle) -> None:
        actor = self._actors_by_cell.get(cell_id)
        if actor is None:
            return
        self._apply_style(actor, style)
        if self._viewport:
            self._viewport.render_window().Render()

    def set_wireframe(self, enabled: bool) -> None:
        self._wireframe_enabled = enabled
        self._rebuild_active_frame()

    def set_camera_mode(self, mode: CameraMode) -> None:
        self._camera_mode = mode

    def fit_scene(self) -> None:
        if self._renderer is None or self._viewport is None:
            return
        self._renderer.ResetCamera()
        self._refresh_camera_clipping()
        self._viewport.render_window().Render()

    # -- Picking --

    def _on_left_button_press(self, obj, event):
        interactor = obj
        if interactor is None or self._picker is None or self._renderer is None:
            return
        if interactor.GetAltKey():
            return  # Alt+LMB is rotate, not pick

        pos = interactor.GetEventPosition()
        self._picker.Pick(pos[0], pos[1], 0.0, self._renderer)
        actor = self._picker.GetActor()
        if actor is None:
            return

        actor_id = id(actor)
        cell_id = self._cell_by_actor.get(actor_id)
        if cell_id is not None and self.on_cell_picked:
            self.on_cell_picked(cell_id)

    # -- Keyboard camera --

    def _on_key_press(self, obj, event):
        interactor = obj
        if interactor is None or self._viewport is None:
            return
        key_sym = interactor.GetKeySym()
        shift = bool(interactor.GetShiftKey())
        ctrl = bool(interactor.GetControlKey())
        if self._apply_camera_key(key_sym, shift, ctrl):
            self._viewport.render_window().Render()

    def _on_char_event(self, obj, event):
        # Suppress VTK's default char bindings in the viewport. In particular,
        # `w`/`s` would otherwise flip all actors between wireframe/surface.
        self._restore_actor_styles()
        if self._viewport is not None:
            self._viewport.render_window().Render()
        return 1

    def _on_interaction(self, obj, event):
        self._refresh_camera_clipping()

    def _restore_actor_styles(self) -> None:
        frame = self._frames_by_tp.get(self._active_timepoint)
        if frame is None:
            return

        for cell in frame.cells:
            actor = self._actors_by_cell.get(cell.cell_id)
            if actor is None:
                continue
            self._apply_style(
                actor,
                cell.style,
                cell.geometry.primitive == PrimitiveType.Lines,
            )

    def _refresh_camera_clipping(self) -> None:
        if self._renderer is None:
            return
        camera = self._renderer.GetActiveCamera()
        if camera is None:
            return

        self._renderer.ResetCameraClippingRange()
        near, far = camera.GetClippingRange()
        cam_dist = max(
            1e-3, _norm(_vec(camera.GetFocalPoint()) - _vec(camera.GetPosition()))
        )
        # Keep the near plane tight enough for close inspection without
        # clipping the front faces open when dollying toward a mesh.
        desired_near = max(1e-4, cam_dist * 1e-3)
        camera.SetClippingRange(min(near, desired_near), far)

    def _apply_camera_key(self, key: str | None, shift: bool, ctrl: bool) -> bool:
        if self._renderer is None or key is None:
            return False

        camera = self._renderer.GetActiveCamera()
        if camera is None:
            return False

        pos = _vec(camera.GetPosition())
        focal = _vec(camera.GetFocalPoint())
        up = _normalize(_vec(camera.GetViewUp()))
        if _norm(up) <= 1e-12:
            up = np.array([0.0, 1.0, 0.0])

        forward = _normalize(focal - pos)
        if _norm(forward) <= 1e-12:
            forward = np.array([0.0, 0.0, 1.0])

        right = _normalize(np.cross(forward, up))
        if _norm(right) <= 1e-12:
            right = np.array([1.0, 0.0, 0.0])

        cam_dist = max(1.0, _norm(focal - pos))
        move_step = max(self._move_speed, cam_dist * 0.08)
        move = move_step * (4.0 if shift else 1.0)
        handled = True

        if key in ("w", "W"):
            delta = forward * move
            pos += delta
            focal += delta
        elif key in ("s", "S"):
            delta = forward * move
            pos -= delta
            focal -= delta
        elif key in ("a", "A"):
            delta = right * move
            pos -= delta
            focal -= delta
        elif key in ("d", "D"):
            delta = right * move
            pos += delta
            focal += delta
        elif key in ("q", "Q"):
            delta = up * move
            pos += delta
            focal += delta
        elif key in ("e", "E"):
            delta = up * move
            pos -= delta
            focal -= delta
        elif key in ("f", "F"):
            self.fit_scene()
            return True
        elif key == "Left":
            angle = self._rotate_speed_deg * math.pi / 180.0
            direction = focal - pos
            focal = pos + _rotate_axis_angle(
                direction, np.array([0.0, 1.0, 0.0]), angle
            )
        elif key == "Right":
            angle = -self._rotate_speed_deg * math.pi / 180.0
            direction = focal - pos
            focal = pos + _rotate_axis_angle(
                direction, np.array([0.0, 1.0, 0.0]), angle
            )
        elif key == "Up":
            angle = self._rotate_speed_deg * math.pi / 180.0
            direction = focal - pos
            focal = pos + _rotate_axis_angle(direction, right, angle)
        elif key == "Down":
            angle = -self._rotate_speed_deg * math.pi / 180.0
            direction = focal - pos
            focal = pos + _rotate_axis_angle(direction, right, angle)
        elif key in ("1", "KP_1"):
            dist = max(1.0, _norm(focal - pos))
            sign = 1.0 if ctrl else -1.0
            pos = np.array([focal[0], focal[1] + sign * dist, focal[2]])
            camera.SetViewUp(0.0, 0.0, 1.0)
        elif key in ("3", "KP_3"):
            dist = max(1.0, _norm(focal - pos))
            sign = -1.0 if ctrl else 1.0
            pos = np.array([focal[0] + sign * dist, focal[1], focal[2]])
            camera.SetViewUp(0.0, 0.0, 1.0)
        elif key in ("7", "KP_7"):
            dist = max(1.0, _norm(focal - pos))
            sign = -1.0 if ctrl else 1.0
            pos = np.array([focal[0], focal[1], focal[2] + sign * dist])
            camera.SetViewUp(0.0, 1.0, 0.0)
        else:
            handled = False

        if not handled:
            return False

        camera.SetPosition(float(pos[0]), float(pos[1]), float(pos[2]))
        camera.SetFocalPoint(float(focal[0]), float(focal[1]), float(focal[2]))
        self._refresh_camera_clipping()
        return True

    # -- Frame rebuild --

    def _rebuild_active_frame(self) -> None:
        if self._renderer is None or self._viewport is None:
            return

        self._clear_actors()

        frame = self._frames_by_tp.get(self._active_timepoint)
        if frame is None:
            self._viewport.render_window().Render()
            return

        for cell in frame.cells:
            actor = self._build_actor(cell)
            if actor is None:
                continue
            self._apply_style(
                actor, cell.style, cell.geometry.primitive == PrimitiveType.Lines
            )
            self._renderer.AddActor(actor)
            self._actors_by_cell[cell.cell_id] = actor
            self._cell_by_actor[id(actor)] = cell.cell_id

        self._refresh_camera_clipping()
        self._viewport.render_window().Render()

    def _clear_actors(self) -> None:
        if self._renderer is not None:
            for actor in self._actors_by_cell.values():
                self._renderer.RemoveActor(actor)
        self._actors_by_cell.clear()
        self._cell_by_actor.clear()

    def _build_actor(self, cell: RenderCellMesh) -> vtkActor | None:
        geom = cell.geometry
        verts = geom.vertices  # Nx3 float32
        faces = geom.faces  # Mx3 uint32

        if verts.size == 0:
            return None

        # Build vtkPoints from numpy (near-zero-copy via numpy_to_vtk)
        verts_contiguous = np.ascontiguousarray(verts, dtype=np.float64)
        vtk_points_data = numpy_to_vtk(verts_contiguous, deep=True)
        points = vtkPoints()
        points.SetData(vtk_points_data)

        poly = vtkPolyData()
        poly.SetPoints(points)

        if geom.primitive == PrimitiveType.Triangles and faces.size > 0:
            # Build connectivity array: [3, i0, i1, i2, 3, i0, i1, i2, ...]
            n_faces = faces.shape[0]
            conn = np.empty((n_faces, 4), dtype=np.int64)
            conn[:, 0] = 3
            conn[:, 1:] = faces.astype(np.int64)
            vtk_conn = numpy_to_vtkIdTypeArray(conn.ravel(), deep=True)
            cells = vtkCellArray()
            cells.SetCells(n_faces, vtk_conn)
            poly.SetPolys(cells)
        else:
            # Lines mode
            if faces.size > 0:
                n_lines = faces.shape[0]
                conn = np.empty((n_lines, 3), dtype=np.int64)
                conn[:, 0] = 2
                conn[:, 1:] = faces[:, :2].astype(np.int64)
            else:
                n_pts = verts.shape[0]
                n_lines = max(0, n_pts - 1)
                conn = np.empty((n_lines, 3), dtype=np.int64)
                conn[:, 0] = 2
                conn[:, 1] = np.arange(n_lines, dtype=np.int64)
                conn[:, 2] = np.arange(1, n_lines + 1, dtype=np.int64)
            vtk_conn = numpy_to_vtkIdTypeArray(conn.ravel(), deep=True)
            cells = vtkCellArray()
            cells.SetCells(n_lines, vtk_conn)
            poly.SetLines(cells)

        mapper = vtkPolyDataMapper()
        mapper.SetInputData(poly)

        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.PickableOn()
        return actor

    def _apply_style(
        self, actor: vtkActor, style: CellStyle, is_line_primitive: bool = False
    ) -> None:
        prop = actor.GetProperty()
        prop.SetColor(*style.color)
        prop.SetOpacity(style.opacity)
        prop.SetLineWidth(style.line_width)
        actor.SetVisibility(1 if style.visible else 0)

        if is_line_primitive or self._wireframe_enabled or style.wireframe:
            prop.SetRepresentationToWireframe()
        else:
            prop.SetRepresentationToSurface()
