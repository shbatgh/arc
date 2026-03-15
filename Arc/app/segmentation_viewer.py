"""2D segmentation overlay viewer — shows microscopy images with outline overlays."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from Arc.io.outline_editor import (
    backup_outlines,
    cell_color_from_id,
    match_outlines_to_cells,
    read_outlines,
    write_outlines,
)
from Arc.io.raw_outline_loader import _parse_int_token, _sorted_timepoint_dirs


def _qcolor_from_cell_id(cell_id: int) -> QColor:
    """Deterministic QColor from a cell identifier."""
    r, g, b = cell_color_from_id(cell_id)
    return QColor(int(r * 255), int(g * 255), int(b * 255))


class _ZoomableGraphicsView(QGraphicsView):
    """QGraphicsView with scroll-to-zoom and middle-click pan."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHint(self.renderHints())
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


class SegmentationViewer(QWidget):
    """2D overlay viewer: microscopy image + Cellpose outlines."""

    changes_applied = Signal()
    outline_picked = Signal(list)  # list[tuple[str, str]] for sidebar rows

    def __init__(self, parent=None):
        super().__init__(parent)

        self._dataset_dir: Path | None = None
        self._image_root: Path | None = None  # where to find .tif images (if different from dataset)
        self._timepoint_dirs: list[Path] = []
        self._current_tp_index: int = 0
        self._current_slice_index: int = 0
        self._deleted: set[tuple[int, int, int]] = set()  # (tp, slice, outline_idx)
        self._has_unsaved_changes: bool = False

        # Outline file paths per timepoint: list[list[Path]]
        self._cp_files_per_tp: list[list[Path]] = []
        # Loaded outlines for current view
        self._current_outlines: list[list[tuple[float, float]]] = []
        # Graphics items for outlines
        self._outline_items: list[QGraphicsPolygonItem] = []

        # Cell matching: {tp_index: {(slice_idx, outline_idx): cell_id}}
        self._cell_assignments: dict[int, dict[tuple[int, int], int]] = {}
        # 3D scene cell palette: {tp_index: [(scene_cell_id, (r,g,b)), ...]}
        # Used to keep seg viewer colors consistent with the 3D view.
        self._scene_cell_palette: dict[int, list[tuple[str, tuple[float, float, float]]]] = {}
        # Undo stack: each entry is a batch of deleted keys
        self._undo_stack: list[set[tuple[int, int, int]]] = []

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Toolbar ---
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)

        self._show_outlines_cb = QCheckBox("Outlines")
        self._show_outlines_cb.setChecked(True)
        self._show_outlines_cb.toggled.connect(self._on_outlines_toggled)
        toolbar.addWidget(self._show_outlines_cb)

        toolbar.addWidget(QLabel("Opacity"))
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setMinimum(0)
        self._opacity_slider.setMaximum(100)
        self._opacity_slider.setValue(40)
        self._opacity_slider.setFixedWidth(100)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        toolbar.addWidget(self._opacity_slider)

        toolbar.addStretch()

        self._apply_btn = QPushButton("Apply Changes")
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply_changes)
        toolbar.addWidget(self._apply_btn)

        toolbar_widget = QWidget()
        toolbar_widget.setLayout(toolbar)
        layout.addWidget(toolbar_widget)

        # --- Graphics view ---
        self._gfx_scene = QGraphicsScene(self)
        self._gfx_scene.selectionChanged.connect(self._on_selection_changed)
        self._view = _ZoomableGraphicsView(self._gfx_scene)
        layout.addWidget(self._view, stretch=1)

        # --- Bottom bar: slice slider + status ---
        bottom = QHBoxLayout()
        bottom.setContentsMargins(8, 4, 8, 4)

        bottom.addWidget(QLabel("Slice:"))
        self._slice_slider = QSlider(Qt.Orientation.Horizontal)
        self._slice_slider.setMinimum(0)
        self._slice_slider.setMaximum(0)
        self._slice_slider.valueChanged.connect(self._on_slice_changed)
        bottom.addWidget(self._slice_slider, stretch=1)

        self._slice_label = QLabel("0 / 0")
        self._slice_label.setFixedWidth(80)
        self._slice_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom.addWidget(self._slice_label)

        self._outline_count_label = QLabel("0 outlines")
        self._outline_count_label.setFixedWidth(100)
        bottom.addWidget(self._outline_count_label)

        bottom_widget = QWidget()
        bottom_widget.setLayout(bottom)
        layout.addWidget(bottom_widget)

    # -- Public API --

    def set_dataset(self, path: Path, *, image_root: Path | None = None) -> None:
        """Set or change the dataset directory.

        Args:
            path: Directory containing timepoint folders with _cp_outlines.txt files.
            image_root: If provided, look for microscopy images here instead of *path*.
                        Useful when outlines are in a separate directory (e.g. after
                        cell isolation) but images remain in the original dataset.
        """
        self._dataset_dir = path
        self._image_root = image_root
        self._timepoint_dirs = _sorted_timepoint_dirs(path)
        self._cp_files_per_tp = []
        for tp_dir in self._timepoint_dirs:
            cp_files = sorted(
                tp_dir.glob("*_cp_outlines.txt"),
                key=lambda p: (_parse_int_token(p.stem), p.name),
            )
            self._cp_files_per_tp.append(cp_files)
        self._deleted.clear()
        self._has_unsaved_changes = False
        self._apply_btn.setEnabled(False)
        self._cell_assignments.clear()
        self._scene_cell_palette.clear()
        self._undo_stack.clear()
        self._current_tp_index = 0
        self._current_slice_index = 0
        self._update_slice_slider()
        self._load_current_view()

    def set_timepoint(self, index: int) -> None:
        """Called by the timeline when the user changes timepoint."""
        if not self._timepoint_dirs or index == self._current_tp_index:
            return
        self._current_tp_index = min(index, len(self._timepoint_dirs) - 1)
        # Clamp slice index to valid range but don't reset to 0
        if self._current_tp_index < len(self._cp_files_per_tp):
            num_slices = len(self._cp_files_per_tp[self._current_tp_index])
            self._current_slice_index = min(self._current_slice_index, max(0, num_slices - 1))
        self._update_slice_slider()
        self._load_current_view()

    @property
    def dataset_dir(self) -> Path | None:
        """The directory currently loaded (may be isolated_outlines/)."""
        return self._dataset_dir

    def has_dataset(self) -> bool:
        return self._dataset_dir is not None and len(self._timepoint_dirs) > 0

    def set_scene_cell_palette(
        self,
        palette: dict[int, list[tuple[str, tuple[float, float, float]]]],
    ) -> None:
        """Set per-timepoint cell colors from the 3D scene.

        *palette* maps timepoint index → ordered list of
        ``(scene_cell_id, (r, g, b))`` entries.  The ordering must match the
        cell creation order so that local matching cell N gets palette entry N.
        """
        self._scene_cell_palette = palette
        # Redraw so colours update immediately
        self._load_current_view()

    # -- Internals --

    def _update_slice_slider(self):
        if not self._cp_files_per_tp or self._current_tp_index >= len(self._cp_files_per_tp):
            self._slice_slider.setMaximum(0)
            self._slice_label.setText("0 / 0")
            return
        num_slices = len(self._cp_files_per_tp[self._current_tp_index])
        self._slice_slider.setMaximum(max(0, num_slices - 1))
        self._slice_slider.setValue(min(self._current_slice_index, max(0, num_slices - 1)))
        self._update_slice_label()

    def _update_slice_label(self):
        if not self._cp_files_per_tp or self._current_tp_index >= len(self._cp_files_per_tp):
            self._slice_label.setText("0 / 0")
            return
        total = len(self._cp_files_per_tp[self._current_tp_index])
        current = self._slice_slider.value() + 1 if total > 0 else 0
        self._slice_label.setText(f"{current} / {total}")

    def _on_slice_changed(self, value: int):
        self._current_slice_index = value
        self._update_slice_label()
        self._load_current_view()

    def _load_current_view(self):
        """Load image + outlines for the current timepoint and slice."""
        self._gfx_scene.clear()
        self._outline_items.clear()
        self._current_outlines.clear()

        if (
            not self._cp_files_per_tp
            or self._current_tp_index >= len(self._cp_files_per_tp)
        ):
            self._outline_count_label.setText("0 outlines")
            return

        cp_files = self._cp_files_per_tp[self._current_tp_index]
        if not cp_files or self._current_slice_index >= len(cp_files):
            self._outline_count_label.setText("0 outlines")
            return

        cp_path = cp_files[self._current_slice_index]
        tp_dir = self._timepoint_dirs[self._current_tp_index]

        # Try to find a matching image (use image_root if outlines are separate)
        if self._image_root is not None:
            image_dir = self._image_root / tp_dir.name
        else:
            image_dir = tp_dir
        pixmap = self._find_and_load_image(image_dir, cp_path)
        if pixmap is not None:
            self._gfx_scene.addPixmap(pixmap)

        # Load outlines
        outlines = read_outlines(cp_path)
        self._current_outlines = outlines

        # Get cell assignments for coloring
        cell_map = self._ensure_cell_assignments(self._current_tp_index)

        # Build local-cell-id → (scene_cell_id, QColor) from 3D palette
        palette = self._scene_cell_palette.get(self._current_tp_index)
        local_to_scene: dict[int, tuple[str, QColor]] = {}
        if palette:
            unique_ids = sorted(set(cell_map.values()))
            for i, local_id in enumerate(unique_ids):
                if i < len(palette):
                    scene_id, (r, g, b) = palette[i]
                    local_to_scene[local_id] = (
                        scene_id,
                        QColor(int(r * 255), int(g * 255), int(b * 255)),
                    )

        visible_count = 0
        fill_alpha = self._opacity_slider.value() * 255 // 100

        for outline_idx, polygon_pts in enumerate(outlines):
            if (self._current_tp_index, self._current_slice_index, outline_idx) in self._deleted:
                continue

            qpoly = QPolygonF()
            for x, y in polygon_pts:
                qpoly.append(QPointF(x, y))

            local_cell_id = cell_map.get((self._current_slice_index, outline_idx), outline_idx)
            if local_cell_id in local_to_scene:
                display_cell_id, color = local_to_scene[local_cell_id]
            else:
                display_cell_id = local_cell_id
                color = _qcolor_from_cell_id(local_cell_id)
            fill_color = QColor(color)
            fill_color.setAlpha(fill_alpha)
            pen = QPen(color, 1.5)

            item = self._gfx_scene.addPolygon(qpoly, pen, fill_color)
            item.setFlag(QGraphicsPolygonItem.GraphicsItemFlag.ItemIsSelectable, True)
            item.setData(0, outline_idx)        # store outline index
            item.setData(1, display_cell_id)    # store cell id (scene id when available)
            self._outline_items.append(item)
            visible_count += 1

        self._outline_count_label.setText(f"{visible_count} outlines")

        # Fit view on first load
        if pixmap is not None or visible_count > 0:
            self._view.fitInView(self._gfx_scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _find_and_load_image(self, tp_dir: Path, cp_path: Path) -> QPixmap | None:
        """Try to find a .tif/.png image that corresponds to the outline file."""
        # The outline file is often named like: image_cp_outlines.txt
        # The source image might be: image.tif, image.png, etc.
        stem = cp_path.name
        # Remove _cp_outlines.txt suffix to get the image base name
        for suffix in ("_cp_outlines.txt",):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break

        for ext in (".tif", ".tiff", ".png", ".jpg", ".jpeg"):
            candidate = tp_dir / (stem + ext)
            if candidate.exists():
                return self._load_image(candidate)

        # Fallback: try any image file with matching index
        return None

    def _load_image(self, path: Path) -> QPixmap | None:
        """Load a microscopy image (including 16-bit TIF) into a QPixmap."""
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            return None

        # Convert to 8-bit grayscale for display
        if img.dtype == np.uint16:
            img = (img / 256).astype(np.uint8)
        elif img.dtype != np.uint8:
            img = img.astype(np.uint8)

        # Handle multichannel
        if len(img.shape) == 3:
            if img.shape[2] == 4:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
                fmt = QImage.Format.Format_RGBA8888
            elif img.shape[2] == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                fmt = QImage.Format.Format_RGB888
            else:
                img = img[:, :, 0]
                fmt = QImage.Format.Format_Grayscale8
        else:
            fmt = QImage.Format.Format_Grayscale8

        h, w = img.shape[:2]
        bytes_per_line = img.strides[0]
        qimage = QImage(img.data, w, h, bytes_per_line, fmt)
        # Must copy because img.data is a temporary buffer
        return QPixmap.fromImage(qimage.copy())

    # -- Cell matching --

    def _ensure_cell_assignments(self, tp_index: int) -> dict[tuple[int, int], int]:
        """Lazily compute and cache cell assignments for a timepoint."""
        if tp_index in self._cell_assignments:
            return self._cell_assignments[tp_index]
        if tp_index >= len(self._cp_files_per_tp):
            return {}
        cp_files = self._cp_files_per_tp[tp_index]
        if not cp_files:
            self._cell_assignments[tp_index] = {}
            return {}
        assignments = match_outlines_to_cells(cp_files)
        self._cell_assignments[tp_index] = assignments
        return assignments

    # -- Outline picking --

    def _on_selection_changed(self):
        selected = self._gfx_scene.selectedItems()
        if not selected:
            self.outline_picked.emit([])
            return
        item = selected[0]
        outline_idx = item.data(0)
        cell_id = item.data(1)
        rows: list[tuple[str, str]] = []
        if cell_id is not None:
            rows.append(("cell_id", str(cell_id)))
        rows.append(("slice", str(self._current_slice_index + 1)))
        if outline_idx is not None:
            rows.append(("outline_index", str(outline_idx)))
            if outline_idx < len(self._current_outlines):
                rows.append(("point_count", str(len(self._current_outlines[outline_idx]))))
        if (
            self._cp_files_per_tp
            and self._current_tp_index < len(self._cp_files_per_tp)
        ):
            cp_files = self._cp_files_per_tp[self._current_tp_index]
            if self._current_slice_index < len(cp_files):
                rows.append(("source_file", cp_files[self._current_slice_index].name))
        self.outline_picked.emit(rows)

    # -- Outline visibility / opacity --

    def _on_outlines_toggled(self, checked: bool):
        for item in self._outline_items:
            item.setVisible(checked)

    def _on_opacity_changed(self, value: int):
        alpha = value * 255 // 100
        for item in self._outline_items:
            brush = item.brush()
            color = brush.color()
            color.setAlpha(alpha)
            brush.setColor(color)
            item.setBrush(brush)

    # -- Delete / Apply --

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._on_delete_pressed()
        elif event.key() == Qt.Key.Key_Z and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._on_undo()
        else:
            super().keyPressEvent(event)

    def _on_delete_pressed(self):
        """Remove selected outline polygons."""
        selected = self._gfx_scene.selectedItems()
        if not selected:
            return
        batch: set[tuple[int, int, int]] = set()
        for item in selected:
            outline_idx = item.data(0)
            if outline_idx is not None:
                key = (self._current_tp_index, self._current_slice_index, outline_idx)
                self._deleted.add(key)
                batch.add(key)
            self._gfx_scene.removeItem(item)
            if item in self._outline_items:
                self._outline_items.remove(item)

        if batch:
            self._undo_stack.append(batch)

        visible = len(self._outline_items)
        self._outline_count_label.setText(f"{visible} outlines")
        self._has_unsaved_changes = len(self._deleted) > 0
        self._apply_btn.setEnabled(self._has_unsaved_changes)

    def _on_undo(self):
        """Undo last delete batch."""
        if not self._undo_stack:
            return
        batch = self._undo_stack.pop()
        self._deleted -= batch
        self._has_unsaved_changes = len(self._deleted) > 0
        self._apply_btn.setEnabled(self._has_unsaved_changes)
        self._load_current_view()

    def _on_apply_changes(self):
        """Write modified outlines back to disk and emit signal."""
        if not self._deleted or self._dataset_dir is None:
            return

        # Group deletions by (tp, slice)
        deletions_by_file: dict[tuple[int, int], set[int]] = {}
        for tp, sl, idx in self._deleted:
            deletions_by_file.setdefault((tp, sl), set()).add(idx)

        files_written = 0
        for (tp, sl), deleted_indices in deletions_by_file.items():
            if tp >= len(self._cp_files_per_tp):
                continue
            cp_files = self._cp_files_per_tp[tp]
            if sl >= len(cp_files):
                continue
            cp_path = cp_files[sl]

            # Read current outlines
            outlines = read_outlines(cp_path)
            # Filter out deleted
            kept = [
                o for i, o in enumerate(outlines) if i not in deleted_indices
            ]

            # Backup then write
            backup_outlines(cp_path)
            write_outlines(cp_path, kept)
            files_written += 1

        self._deleted.clear()
        self._has_unsaved_changes = False
        self._apply_btn.setEnabled(False)
        self._undo_stack.clear()
        self._cell_assignments.clear()
        self._scene_cell_palette.clear()

        # Reload current view to reflect changes
        self._load_current_view()
        self.changes_applied.emit()
