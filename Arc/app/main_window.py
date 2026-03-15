"""Main application window — orchestrates viewport, sidebar, timeline, and I/O."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from Arc.app.clustering_panel import ClusteringPanel
from Arc.app.segmentation_viewer import SegmentationViewer
from Arc.app.sidebar import SidebarPanel
from Arc.app.timeline import TimelinePanel
from Arc.core.isolation_config import IsolationConfig
from Arc.core.render_types import RenderInitOptions, RenderScene
from Arc.render.vtk_backend import VtkRenderBackend

_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "arc_errors.log"
_log = logging.getLogger("arc")

_MAX_DIALOG_CHARS = 1500


def _setup_file_logging() -> None:
    """Configure arc logger to write to arc_errors.log (once)."""
    if _log.handlers:
        return
    _log.setLevel(logging.DEBUG)
    handler = logging.FileHandler(_LOG_PATH, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    _log.addHandler(handler)


def _show_error(parent, title: str, msg: str) -> None:
    """Log the full error to disk and show a truncated version in a dialog."""
    _log.error("%s\n%s", title, msg)
    if len(msg) > _MAX_DIALOG_CHARS:
        truncated = msg[:_MAX_DIALOG_CHARS] + f"\n\n... truncated ({len(msg)} chars total)\nFull error logged to:\n{_LOG_PATH}"
    else:
        truncated = msg + f"\n\nLogged to: {_LOG_PATH}"
    QMessageBox.critical(parent, title, truncated)


class _BundleLoaderWorker(QObject):
    """Loads a bundle in a background thread."""

    finished = Signal(object, object, object)  # scene, metadata, quant
    error = Signal(str)
    progress = Signal(int, str)

    def __init__(self, path: Path):
        super().__init__()
        self._path = path

    def run(self):
        try:
            from Arc.io.bundle_loader import load_bundle

            scene, metadata, quant = load_bundle(self._path, progress_cb=self.progress.emit)
            self.finished.emit(scene, metadata, quant)
        except Exception as exc:
            self.error.emit(str(exc))


class _PipelineWorker(QObject):
    """Runs the BioVision pipeline in a background thread."""

    finished = Signal(str)  # bundle directory path
    error = Signal(str)
    progress = Signal(int, str)

    def __init__(
        self,
        dataset_dir: str,
        output_dir: str | None = None,
        isolation_config: IsolationConfig | None = None,
    ):
        super().__init__()
        self._dataset_dir = dataset_dir
        self._output_dir = output_dir
        self._isolation_config = isolation_config

    def run(self):
        try:
            from Arc.io.pipeline_runner import run_pipeline

            result = run_pipeline(
                self._dataset_dir,
                self._output_dir,
                progress_cb=self.progress.emit,
                isolation_config=self._isolation_config,
            )
            self.finished.emit(str(result))
        except Exception as exc:
            self.error.emit(str(exc))


class _RawOutlineLoaderWorker(QObject):
    """Loads raw `_cp_outlines.txt` stacks in a background thread."""

    finished = Signal(object, object)  # scene, metadata
    error = Signal(str)
    progress = Signal(int, str)

    def __init__(self, dataset_dir: Path):
        super().__init__()
        self._dataset_dir = dataset_dir

    def run(self):
        try:
            from Arc.io.raw_outline_loader import load_raw_outlines

            scene, metadata = load_raw_outlines(
                self._dataset_dir,
                progress_cb=self.progress.emit,
            )
            self.finished.emit(scene, metadata)
        except Exception as exc:
            self.error.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        _setup_file_logging()
        self.setWindowTitle("ARC")
        self.resize(1400, 900)

        self._backend = VtkRenderBackend()
        self._scene: RenderScene | None = None
        self._metadata: dict = {}
        self._quant: dict | None = None
        self._mesh_scene: RenderScene | None = None
        self._mesh_metadata: dict = {}
        self._mesh_quant: dict | None = None
        self._raw_outline_scene: RenderScene | None = None
        self._raw_outline_metadata: dict = {}
        self._dataset_dir: Path | None = None
        self._display_mode: str = "mesh"
        self._timepoint_list: list[int] = []
        self._worker_thread: QThread | None = None
        self._active_workers: list[tuple[QThread, QObject]] = []
        self._pending_bundle_dir: Path | None = None
        self._isolation_config: IsolationConfig | None = None
        self._progress_offset = 0
        self._progress_span = 100

        self._setup_ui()
        self._setup_menus()
        self._connect_signals()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Splitter: viewport | right panel
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter, stretch=1)

        # Viewport tabs: 3D view + Segmentation overlay
        self._viewport_tabs = QTabWidget()
        self._viewport_tabs.setMinimumWidth(400)
        self._viewport_host = QWidget()
        self._viewport_tabs.addTab(self._viewport_host, "3D View")
        self._seg_viewer = SegmentationViewer()
        self._viewport_tabs.addTab(self._seg_viewer, "Segmentation")
        self._viewport_tabs.setTabEnabled(1, False)
        splitter.addWidget(self._viewport_tabs)

        # Right panel tabs
        right_tabs = QTabWidget()
        right_tabs.setFixedWidth(280)

        self._sidebar = SidebarPanel()
        right_tabs.addTab(self._sidebar, "Selection")

        self._clustering = ClusteringPanel()
        right_tabs.addTab(self._clustering, "Clustering")

        splitter.addWidget(right_tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        # Timeline at bottom
        self._timeline = TimelinePanel()
        main_layout.addWidget(self._timeline)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._progress = QProgressBar()
        self._progress.setFixedWidth(200)
        self._progress.setVisible(False)
        self._status.addPermanentWidget(self._progress)

        # Initialize VTK backend
        self._backend.initialize(self._viewport_host, RenderInitOptions())
        self._backend.on_cell_picked = self._on_cell_picked

    def _setup_menus(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        file_menu.addAction("Open Animation Bundle...", self._open_bundle)
        file_menu.addAction("Open Dataset...", self._open_dataset)
        file_menu.addSeparator()
        file_menu.addAction("Quit", self.close)

        view_menu = menubar.addMenu("View")
        self._raw_outlines_action = view_menu.addAction("Raw Outlines")
        self._raw_outlines_action.setCheckable(True)
        self._raw_outlines_action.setEnabled(False)
        self._raw_outlines_action.toggled.connect(self._on_raw_outlines_toggled)
        view_menu.addAction("Fit Scene", self._backend.fit_scene)

    def _connect_signals(self):
        self._timeline.timepoint_changed.connect(self._on_timepoint_changed)
        self._seg_viewer.changes_applied.connect(self._on_seg_changes_applied)
        self._seg_viewer.outline_picked.connect(self._on_outline_picked)

    # -- File actions --

    def _open_bundle(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Animation Bundle",
            "",
            "NPZ files (*.npz);;JSON metadata (*.json);;All files (*)",
        )
        if not path:
            return
        self._reset_raw_outline_context()
        self._load_bundle(Path(path))

    def _open_dataset(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Open Dataset Directory")
        if not dir_path:
            return
        from Arc.app.isolation_dialog import CellIsolationDialog

        proceed, isolation_config = CellIsolationDialog.get_config(self, Path(dir_path))
        if not proceed:
            return
        self._dataset_dir = Path(dir_path)
        self._isolation_config = isolation_config
        self._raw_outline_scene = None
        self._raw_outline_metadata = {}
        self._set_raw_outlines_checked(False)
        self._raw_outlines_action.setEnabled(False)
        self._seg_viewer.set_dataset(self._dataset_dir)
        self._run_pipeline(dir_path, isolation_config=isolation_config)

    def _load_bundle(
        self,
        path: Path,
        *,
        progress_offset: int = 0,
        progress_span: int = 100,
    ):
        self._start_progress(
            f"Loading bundle: {path.name}...",
            offset=progress_offset,
            span=progress_span,
        )

        thread = QThread()
        worker = _BundleLoaderWorker(path)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_worker_progress)
        worker.finished.connect(self._on_bundle_loaded)
        worker.error.connect(self._on_bundle_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)

        self._track_worker(thread, worker)
        self._worker_thread = thread
        thread.start()

    def _on_bundle_loaded(self, scene: RenderScene, metadata: dict, quant):
        self._mesh_scene = scene
        self._mesh_metadata = metadata
        self._mesh_quant = quant
        self._display_mode = "mesh"
        self._set_raw_outlines_checked(False)
        self._raw_outlines_action.setEnabled(self._dataset_dir is not None)
        self._viewport_tabs.setTabEnabled(1, self._dataset_dir is not None)
        self._sync_seg_viewer_colors(scene)
        self._show_mesh_scene(fit_scene=True, preserve_index=False)
        self._finish_progress()

    def _sync_seg_viewer_colors(self, scene: RenderScene) -> None:
        """Pass 3D cell colors to the seg viewer so both views match."""
        palette: dict[int, list[tuple[str, tuple[float, float, float]]]] = {}
        for frame_idx, frame in enumerate(scene.frames):
            seen: dict[str, tuple[float, float, float]] = {}
            for cell in frame.cells:
                if cell.cell_id not in seen:
                    seen[cell.cell_id] = cell.style.color
            palette[frame_idx] = list(seen.items())
        self._seg_viewer.set_scene_cell_palette(palette)

    def _on_bundle_error(self, msg: str):
        self._finish_progress()
        self._status.showMessage("Load failed")
        _show_error(self, "Bundle Load Error", msg)

    # -- Pipeline --

    def _run_pipeline(
        self,
        dataset_dir: str,
        isolation_config: IsolationConfig | None = None,
    ):
        self._start_progress(
            f"Running pipeline on {Path(dataset_dir).name}...",
            offset=0,
            span=85,
        )

        thread = QThread()
        worker = _PipelineWorker(dataset_dir, isolation_config=isolation_config)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_worker_progress)
        worker.finished.connect(self._on_pipeline_finished)
        worker.error.connect(self._on_pipeline_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._on_pipeline_thread_finished)
        thread.finished.connect(thread.deleteLater)

        self._track_worker(thread, worker)
        self._worker_thread = thread
        thread.start()

    def _on_pipeline_finished(self, bundle_dir: str):
        self._pending_bundle_dir = Path(bundle_dir)
        self._status.showMessage("Pipeline complete, starting bundle load...")

        # If cell isolation was used, update seg viewer to show filtered outlines
        # but keep looking for images in the original dataset directory
        if self._isolation_config is not None and self._dataset_dir is not None:
            isolated_dir = self._pending_bundle_dir.parent / "isolated_outlines"
            if isolated_dir.is_dir():
                self._seg_viewer.set_dataset(
                    isolated_dir, image_root=self._dataset_dir
                )

    def _on_pipeline_error(self, msg: str):
        self._pending_bundle_dir = None
        self._finish_progress()
        self._status.showMessage("Pipeline failed")
        _show_error(self, "Pipeline Error", msg)

    # -- Timepoint --

    def _on_timepoint_changed(self, index: int):
        if index < len(self._timepoint_list):
            tp = self._timepoint_list[index]
            self._backend.set_timepoint(tp)
        self._seg_viewer.set_timepoint(index)

    # -- Cell picking --

    def _on_cell_picked(self, cell_id: str):
        rows: list[tuple[str, str]] = [("cell_id", cell_id)]

        frame_idx = self._timeline.current_timepoint()
        if self._scene and frame_idx < len(self._scene.frames):
            frame = self._scene.frames[frame_idx]
            tp = frame.timepoint

            for cell in frame.cells:
                if cell.cell_id == cell_id:
                    c = cell.style.color
                    rows.append(("color", f"({c[0]:.2f}, {c[1]:.2f}, {c[2]:.2f})"))
                    if self._display_mode == "raw_outlines":
                        for key in (
                            "slice_index",
                            "outline_index",
                            "point_count",
                            "source_file",
                        ):
                            value = cell.metadata.get(key)
                            if value is not None:
                                rows.append((key, str(value)))
                    break

            if self._quant:
                qdata = self._quant.get((cell_id, tp))
                if qdata:
                    for key in (
                        "volume",
                        "surface_area",
                        "center_x",
                        "center_y",
                        "center_z",
                        "displacement",
                        "distance",
                    ):
                        if key in qdata:
                            val = qdata[key]
                            if isinstance(val, float):
                                rows.append((key, f"{val:.4f}"))
                            else:
                                rows.append((key, str(val)))

        self._sidebar.update_properties(rows)

    def _on_outline_picked(self, rows: list[tuple[str, str]]):
        if rows:
            self._sidebar.update_properties(rows)
        else:
            self._sidebar.clear_properties()

    # -- View toggles --

    def _on_raw_outlines_toggled(self, enabled: bool):
        if enabled:
            if self._raw_outline_scene is not None:
                self._show_raw_outline_scene()
                return
            if self._dataset_dir is None:
                self._set_raw_outlines_checked(False)
                return
            self._load_raw_outlines(self._dataset_dir)
            return

        if self._display_mode == "raw_outlines" and self._mesh_scene is not None:
            self._show_mesh_scene()

    def _load_raw_outlines(self, dataset_dir: Path):
        self._start_progress(
            f"Loading raw outlines: {dataset_dir.name}...",
            offset=0,
            span=100,
        )

        thread = QThread()
        worker = _RawOutlineLoaderWorker(dataset_dir)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_worker_progress)
        worker.finished.connect(self._on_raw_outlines_loaded)
        worker.error.connect(self._on_raw_outlines_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)

        self._track_worker(thread, worker)
        self._worker_thread = thread
        thread.start()

    def _on_raw_outlines_loaded(self, scene: RenderScene, metadata: dict):
        self._raw_outline_scene = scene
        self._raw_outline_metadata = metadata
        self._finish_progress()
        self._raw_outlines_action.setEnabled(True)

        if self._raw_outlines_action.isChecked():
            self._show_raw_outline_scene()
        else:
            name = metadata.get("dataset_name", "Unknown")
            outline_count = metadata.get("outline_count", 0)
            self._status.showMessage(
                f"Raw outlines ready for {name}: {outline_count} outlines"
            )

    def _on_raw_outlines_error(self, msg: str):
        self._finish_progress()
        self._status.showMessage("Raw outline load failed")
        self._set_raw_outlines_checked(False)
        _show_error(self, "Raw Outline Load Error", msg)

    def _start_progress(self, message: str, *, offset: int, span: int) -> None:
        self._progress_offset = max(0, min(100, offset))
        self._progress_span = max(0, min(100 - self._progress_offset, span))
        self._progress.setRange(0, 100)
        self._progress.setValue(self._progress_offset)
        self._progress.setVisible(True)
        self._status.showMessage(message)

    def _finish_progress(self) -> None:
        self._progress.setVisible(False)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress_offset = 0
        self._progress_span = 100

    def _on_worker_progress(self, value: int, label: str) -> None:
        bounded_value = max(0, min(100, int(value)))
        if bounded_value <= 0 or self._progress_span <= 0:
            mapped_value = self._progress_offset
        else:
            mapped_value = self._progress_offset + max(
                1,
                (bounded_value * self._progress_span + 99) // 100,
            )
        self._progress.setValue(max(0, min(100, mapped_value)))
        if label:
            self._status.showMessage(label)

    def _track_worker(self, thread: QThread, worker: QObject) -> None:
        self._active_workers.append((thread, worker))
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda thread=thread, worker=worker: self._release_worker(thread, worker)
        )

    def _release_worker(self, thread: QThread, worker: QObject) -> None:
        try:
            self._active_workers.remove((thread, worker))
        except ValueError:
            pass
        if self._worker_thread is thread:
            self._worker_thread = None

    def _on_pipeline_thread_finished(self) -> None:
        if self._pending_bundle_dir is None:
            return
        bundle_dir = self._pending_bundle_dir
        self._pending_bundle_dir = None
        self._load_bundle(bundle_dir, progress_offset=85, progress_span=15)

    def closeEvent(self, event: QCloseEvent) -> None:
        if any(thread.isRunning() for thread, _ in self._active_workers):
            self._status.showMessage("Wait for loading to finish before closing the app.")
            event.ignore()
            return
        super().closeEvent(event)

    def _show_mesh_scene(self, *, fit_scene: bool = False, preserve_index: bool = True):
        if self._mesh_scene is None:
            return
        self._display_mode = "mesh"
        self._apply_scene(
            self._mesh_scene,
            self._mesh_metadata,
            self._mesh_quant,
            fit_scene=fit_scene,
            preserve_index=preserve_index,
        )
        mesh_count = sum(len(frame.cells) for frame in self._mesh_scene.frames)
        name = self._mesh_metadata.get("dataset_name", "Unknown")
        self._status.showMessage(
            f"Viewing meshes: {name}, {mesh_count} meshes, {len(self._mesh_scene.frames)} timepoints"
        )

    def _show_raw_outline_scene(self):
        if self._raw_outline_scene is None:
            return
        self._display_mode = "raw_outlines"
        self._apply_scene(
            self._raw_outline_scene,
            self._raw_outline_metadata,
            None,
            fit_scene=False,
            preserve_index=True,
        )
        name = self._raw_outline_metadata.get("dataset_name", "Unknown")
        outline_count = self._raw_outline_metadata.get("outline_count", 0)
        self._status.showMessage(
            f"Viewing raw outlines: {name}, {outline_count} outlines, {len(self._raw_outline_scene.frames)} timepoints"
        )

    def _apply_scene(
        self,
        scene: RenderScene,
        metadata: dict,
        quant,
        *,
        fit_scene: bool,
        preserve_index: bool,
    ) -> None:
        current_index = self._timeline.current_timepoint() if preserve_index else 0
        if scene.frames:
            current_index = min(current_index, len(scene.frames) - 1)
        else:
            current_index = 0

        self._scene = scene
        self._metadata = metadata
        self._quant = quant
        self._timepoint_list = [frame.timepoint for frame in scene.frames]

        self._sidebar.clear_properties()
        self._backend.set_scene(scene)
        self._timeline.setup(len(scene.frames), start=current_index)
        if self._timepoint_list:
            self._backend.set_timepoint(self._timepoint_list[current_index])
        if fit_scene:
            self._backend.fit_scene()

    def _set_raw_outlines_checked(self, checked: bool):
        self._raw_outlines_action.blockSignals(True)
        self._raw_outlines_action.setChecked(checked)
        self._raw_outlines_action.blockSignals(False)

    def _on_seg_changes_applied(self):
        # Re-run pipeline on the directory the seg viewer is editing.
        # After isolation this is isolated_outlines/, not the original dataset.
        outlines_dir = self._seg_viewer.dataset_dir
        if outlines_dir is None:
            return
        self._viewport_tabs.setCurrentIndex(0)
        # Invalidate cached raw outlines since files changed
        self._raw_outline_scene = None
        self._raw_outline_metadata = {}
        self._set_raw_outlines_checked(False)
        # Don't re-run isolation — the outlines are already filtered and
        # the user has just manually edited them.
        self._isolation_config = None
        self._run_pipeline(str(outlines_dir))

    def _reset_raw_outline_context(self):
        self._dataset_dir = None
        self._raw_outline_scene = None
        self._raw_outline_metadata = {}
        self._set_raw_outlines_checked(False)
        self._raw_outlines_action.setEnabled(False)
