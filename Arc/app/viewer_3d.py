from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget, QSizePolicy
from PySide6.QtGui import QKeyEvent
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.vtkRenderingCore import vtkCellPicker
from vedo import Mesh, Plotter

from Arc.core.scene import Scene


class Viewer3D(QWidget):
    cell_picked = Signal(str)

    # Movement speed for keyboard navigation
    MOVE_SPEED = 5.0

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Make the widget expand to fill available space
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(400, 300)

        self.vtk_widget = QVTKRenderWindowInteractor(self)
        self.vtk_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.vtk_widget)

        self.plotter = Plotter(qt_widget=self.vtk_widget, bg=(0.06, 0.07, 0.08), axes=0)
        self.plotter.show(interactive=False)

        self._actor_to_cell_id: Dict[object, str] = {}
        self._picker = vtkCellPicker()
        self._picker.SetTolerance(0.0005)
        self._wireframe_mode = False

        # Enable keyboard focus
        self.setFocusPolicy(Qt.StrongFocus)
        self.vtk_widget.setFocusPolicy(Qt.StrongFocus)

        self._configure_interactor()

    def _configure_interactor(self) -> None:
        # QVTKRenderWindowInteractor proxies vtkGenericRenderWindowInteractor via __getattr__.
        self.vtk_widget.AddObserver("LeftButtonPressEvent", self._on_left_button_press)
        self.vtk_widget.Initialize()
        self.vtk_widget.Start()

    def _on_left_button_press(self, obj, event) -> None:
        x, y = self.vtk_widget.GetEventPosition()
        self._picker.Pick(x, y, 0, self.plotter.renderer)
        actor = self._picker.GetActor()
        if actor is not None:
            cell_id = self._actor_to_cell_id.get(actor)
            if cell_id:
                self.cell_picked.emit(cell_id)

    def set_wireframe_mode(self, enabled: bool) -> None:
        self._wireframe_mode = enabled
        for mesh in self.plotter.actors:
            if isinstance(mesh, Mesh):
                mesh.wireframe(enabled)
        self.plotter.render()

    def display_scene(self, scene: Scene) -> None:
        self.clear_scene()
        meshes = scene.meshes()
        if not meshes:
            self.plotter.render()
            return
        for mesh in meshes:
            self._add_mesh(mesh)
        self.plotter.reset_camera()
        self.plotter.render()

    def clear_scene(self) -> None:
        self.plotter.clear()
        self._actor_to_cell_id.clear()

    def _add_mesh(self, mesh: Mesh) -> None:
        cell_id = getattr(mesh, "cell_id", None) or getattr(mesh, "name", None)
        if self._wireframe_mode:
            mesh.wireframe(True)
        self.plotter.add(mesh)
        actor = getattr(mesh, "actor", None)
        if cell_id and actor is not None:
            actor.SetPickable(True)
            self._actor_to_cell_id[actor] = cell_id

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keyboard input for camera movement."""
        key = event.key()
        camera = self.plotter.camera

        # Get camera vectors for movement
        pos = list(camera.GetPosition())
        focal = list(camera.GetFocalPoint())
        up = list(camera.GetViewUp())

        # Calculate forward and right vectors
        forward = [focal[i] - pos[i] for i in range(3)]
        forward_len = (forward[0]**2 + forward[1]**2 + forward[2]**2) ** 0.5
        if forward_len > 0:
            forward = [f / forward_len for f in forward]

        # Right vector = forward x up
        right = [
            forward[1] * up[2] - forward[2] * up[1],
            forward[2] * up[0] - forward[0] * up[2],
            forward[0] * up[1] - forward[1] * up[0],
        ]

        moved = False

        # W / Up Arrow - move forward
        if key in (Qt.Key_W, Qt.Key_Up):
            for i in range(3):
                pos[i] += forward[i] * self.MOVE_SPEED
                focal[i] += forward[i] * self.MOVE_SPEED
            moved = True

        # S / Down Arrow - move backward
        elif key in (Qt.Key_S, Qt.Key_Down):
            for i in range(3):
                pos[i] -= forward[i] * self.MOVE_SPEED
                focal[i] -= forward[i] * self.MOVE_SPEED
            moved = True

        # A / Left Arrow - move left
        elif key in (Qt.Key_A, Qt.Key_Left):
            for i in range(3):
                pos[i] -= right[i] * self.MOVE_SPEED
                focal[i] -= right[i] * self.MOVE_SPEED
            moved = True

        # D / Right Arrow - move right
        elif key in (Qt.Key_D, Qt.Key_Right):
            for i in range(3):
                pos[i] += right[i] * self.MOVE_SPEED
                focal[i] += right[i] * self.MOVE_SPEED
            moved = True

        # Q - move up
        elif key == Qt.Key_Q:
            for i in range(3):
                pos[i] += up[i] * self.MOVE_SPEED
                focal[i] += up[i] * self.MOVE_SPEED
            moved = True

        # E - move down
        elif key == Qt.Key_E:
            for i in range(3):
                pos[i] -= up[i] * self.MOVE_SPEED
                focal[i] -= up[i] * self.MOVE_SPEED
            moved = True

        if moved:
            camera.SetPosition(pos)
            camera.SetFocalPoint(focal)
            self.plotter.render()
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:
        """Ensure VTK widget also gets focus."""
        super().focusInEvent(event)
        self.vtk_widget.setFocus()

    def mousePressEvent(self, event) -> None:
        """Grab focus when clicked."""
        self.setFocus()
        super().mousePressEvent(event)
