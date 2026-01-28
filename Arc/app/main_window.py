from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QMessageBox, QVBoxLayout, QWidget, QInputDialog, QTabWidget, QSizePolicy

from Arc.app.dialogs.import_dialog import get_import_folder
from Arc.app.sidebar import Sidebar
from Arc.app.timeline import Timeline
from Arc.app.viewer_3d import Viewer3D
from Arc.app.clustering_panel import ClusteringPanel
from Arc.core.io.mesh_loader import load_dataset_from_root
from Arc.core.scene import Scene
from Arc.core.project import Project
from Arc.core.cell4d import CellTracker, Cell4D

import matplotlib.cm


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ARC")

        self.viewer = Viewer3D(self)
        self.sidebar = Sidebar(self)
        self.clustering_panel = ClusteringPanel(self)
        self.timeline = Timeline(self)
        self.project = Project()
        self.scene = Scene(timepoint=0)
        self._timepoints: list[int] = []
        self._cluster_map: dict[int, int] = {}  # track_id -> cluster
        self._cluster_colors: dict[int, tuple] = {}  # cluster -> (r, g, b)
        self._data_root: Path | None = None
        self._cell_tracker = CellTracker(max_distance=50.0)
        self._cell_tracks: dict[int, Cell4D] = {}  # track_id -> Cell4D

        self._build_ui()
        self._build_menu()
        self._connect_signals()

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Create right panel with tabs for sidebar and clustering
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.sidebar, "Selection")
        self.right_tabs.addTab(self.clustering_panel, "Clustering")
        self.right_tabs.setFixedWidth(280)
        self.right_tabs.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        # Viewer takes up all remaining space
        self.viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(0)
        top_row.addWidget(self.viewer, stretch=1)
        top_row.addWidget(self.right_tabs, stretch=0)

        layout.addLayout(top_row, stretch=1)
        layout.addWidget(self.timeline, stretch=0)

        self.setCentralWidget(central)
        self.resize(1280, 800)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        import_action = QAction("Import Dataset Folder...", self)
        import_action.triggered.connect(self.import_dataset_folder)
        file_menu.addAction(import_action)

        file_menu.addSeparator()

        exit_action = QAction("Quit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def _connect_signals(self) -> None:
        self.viewer.cell_picked.connect(self._on_cell_picked)
        self.timeline.slider.valueChanged.connect(self._show_timepoint_index)
        self.clustering_panel.clustering_complete.connect(self._on_clustering_complete)

    def import_dataset_folder(self) -> None:
        folder = get_import_folder(self)
        if not folder:
            return

        items = ["Solid", "Mesh", "Raw"]
        item, ok = QInputDialog.getItem(self, "Import Mode", "Select import mode:", items, 0, False)
        if not ok:
            return

        mode = item.lower()

        project, timepoints = load_dataset_from_root(folder, mode=mode)
        if not timepoints:
            QMessageBox.information(
                self,
                "Import Dataset Folder",
                "No timepoints with outline data were found.",
            )
            return

        self.project = project
        self._timepoints = timepoints
        self._data_root = Path(folder)
        self._cluster_map.clear()
        self._cluster_colors.clear()

        # Track cells across timepoints
        self._track_cells()

        # Look for quant_data CSV for clustering
        self._setup_clustering_data()

        self.timeline.set_range(len(timepoints))
        self._show_timepoint_index(0)

    def _track_cells(self) -> None:
        """Track cells across all timepoints to maintain consistent IDs."""
        if not self.project.scenes:
            return

        print("Tracking cells across timepoints...")
        self._cell_tracks = self._cell_tracker.track_cells(self.project.scenes)

        # Print tracking summary
        n_tracks = len(self._cell_tracks)
        lifespans = [track.lifespan for track in self._cell_tracks.values()]
        if lifespans:
            avg_lifespan = sum(lifespans) / len(lifespans)
            max_lifespan = max(lifespans)
            print(f"Cell tracking complete: {n_tracks} tracks, avg lifespan: {avg_lifespan:.1f}, max: {max_lifespan}")

    def _setup_clustering_data(self) -> None:
        """Find or generate clustering data CSV."""
        if not self._data_root:
            return

        # Look for existing quant_data.csv or similar
        search_paths = [
            self._data_root / "quant_data.csv",
            self._data_root / "quant_daeta2.csv",
            self._data_root / "outline_data.csv",
            self._data_root.parent / "quant_data.csv",
            self._data_root.parent / "quant_daeta2.csv",
            self._data_root.parent / "outline_data.csv",
        ]

        for path in search_paths:
            if path.exists():
                self.clustering_panel.set_data_path(path)
                return

        # No existing CSV found - generate one from loaded data
        generated_path = self._generate_clustering_csv()
        if generated_path:
            self.clustering_panel.set_data_path(generated_path)
        else:
            self.clustering_panel.set_data_path(None)

    def _generate_clustering_csv(self) -> Path | None:
        """Generate a CSV file with cell features from tracked cells."""
        if not self._cell_tracks:
            return None

        try:
            import csv

            rows = []
            for track_id, track in self._cell_tracks.items():
                # Collect measurements across all timepoints for this track
                measurements = []
                for timepoint, cell in track.cells.items():
                    try:
                        center = cell.center
                        volume = cell.volume
                        area = cell.area
                    except Exception:
                        continue

                    measurements.append({
                        "timepoint": timepoint,
                        "volume": volume,
                        "surface_area": area,
                        "centroid_x": center[0],
                        "centroid_y": center[1],
                        "centroid_z": center[2],
                    })

                if not measurements:
                    continue

                n = len(measurements)
                mean_volume = sum(m["volume"] for m in measurements) / n
                mean_area = sum(m["surface_area"] for m in measurements) / n
                mean_cx = sum(m["centroid_x"] for m in measurements) / n
                mean_cy = sum(m["centroid_y"] for m in measurements) / n
                mean_cz = sum(m["centroid_z"] for m in measurements) / n

                # Compute total distance traveled
                total_distance = 0.0
                sorted_measurements = sorted(measurements, key=lambda x: x["timepoint"])
                for i in range(1, len(sorted_measurements)):
                    prev = sorted_measurements[i - 1]
                    curr = sorted_measurements[i]
                    dx = curr["centroid_x"] - prev["centroid_x"]
                    dy = curr["centroid_y"] - prev["centroid_y"]
                    dz = curr["centroid_z"] - prev["centroid_z"]
                    total_distance += (dx**2 + dy**2 + dz**2) ** 0.5

                rows.append({
                    "Cell ID": track_id,  # Use track_id for clustering
                    "display_id": track.display_id,
                    "outlines": "[]",  # Placeholder for CellClusteringAnalyzer format detection
                    "mean_volume": mean_volume,
                    "mean_surface_area": mean_area,
                    "mean_centroid_x": mean_cx,
                    "mean_centroid_y": mean_cy,
                    "mean_centroid_z": mean_cz,
                    "total_distance_traveled": total_distance,
                    "num_timepoints": n,
                    "t_start": track.t_start,
                    "t_end": track.t_end,
                })

            if not rows:
                return None

            # Write CSV
            output_path = self._data_root / "generated_cell_features.csv"
            with open(output_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            print(f"Generated clustering CSV: {output_path} ({len(rows)} tracked cells)")
            return output_path

        except Exception as e:
            print(f"Failed to generate clustering CSV: {e}")
            return None

    def _show_timepoint_index(self, index: int) -> None:
        if not self._timepoints:
            return
        index = max(0, min(index, len(self._timepoints) - 1))
        timepoint = self._timepoints[index]
        scene = self.project.scenes.get(timepoint, Scene(timepoint=timepoint))
        self.scene = scene

        # Apply cluster colors if clustering has been done
        if self._cluster_map:
            self._apply_cluster_colors(scene)

        self.viewer.display_scene(scene)
        self.timeline.set_timepoint_label(f"t{timepoint}")

    def _on_cell_picked(self, cell_id: str) -> None:
        if not cell_id or cell_id not in self.scene.cells:
            return

        cell = self.scene.cells[cell_id]

        # Use display_id from 4D tracking if available
        display_id = cell.metadata.get("display_id", cell.cell_id)
        track_id = cell.metadata.get("track_id")

        props = {
            "ID": display_id,
            "Timepoint": self.scene.timepoint,
            "Volume": f"{cell.volume:.2f}",
            "Surface Area": f"{cell.area:.2f}",
            "Center X": f"{cell.center[0]:.2f}",
            "Center Y": f"{cell.center[1]:.2f}",
            "Center Z": f"{cell.center[2]:.2f}",
        }

        # Add lifespan info if tracked
        if track_id is not None:
            t_start = cell.metadata.get("t_start", "?")
            t_end = cell.metadata.get("t_end", "?")
            props["Lifespan"] = f"t{t_start} - t{t_end}"

        # Add cluster info if available (use track_id for clustering)
        if track_id is not None and track_id in self._cluster_map:
            props["Cluster"] = self._cluster_map[track_id]

        # Add other metadata
        skip_keys = {"curves", "display_id", "track_id", "t_start", "t_end", "id"}
        for k, v in cell.metadata.items():
            if k not in props and k not in skip_keys:
                props[str(k)] = str(v)

        self.sidebar.update_properties(props)

    def _on_clustering_complete(self, result: dict) -> None:
        """Handle clustering complete signal."""
        self._cluster_map = result.get("cluster_map", {})
        n_clusters = result.get("n_clusters", 0)

        # Generate colors for clusters using a colormap
        cmap = matplotlib.cm.get_cmap("tab10")
        self._cluster_colors.clear()
        for cluster_id in range(-1, n_clusters):  # -1 for outliers
            if cluster_id == -1:
                self._cluster_colors[-1] = (0.5, 0.5, 0.5)  # Gray for outliers
            else:
                rgba = cmap(cluster_id % 10)
                self._cluster_colors[cluster_id] = rgba[:3]

        # Update all scenes with cluster metadata using track_id
        for tp, scene in self.project.scenes.items():
            for cell in scene.cells.values():
                track_id = cell.metadata.get("track_id")
                if track_id is not None and track_id in self._cluster_map:
                    cell.metadata["cluster"] = self._cluster_map[track_id]

        # Refresh display
        current_index = self.timeline.slider.value()
        self._show_timepoint_index(current_index)

    def _apply_cluster_colors(self, scene: Scene) -> None:
        """Apply cluster colors to all cells in a scene."""
        for cell in scene.cells.values():
            track_id = cell.metadata.get("track_id")
            if track_id is None or track_id not in self._cluster_map:
                continue

            cluster_id = self._cluster_map[track_id]
            color = self._cluster_colors.get(cluster_id)
            if color is None:
                continue

            try:
                cell.mesh.c(color)
            except Exception:
                pass
