from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, List, Callable
import sys

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QDoubleSpinBox, QComboBox, QGroupBox, QProgressBar,
    QTextEdit, QCheckBox, QMessageBox, QFileDialog, QScrollArea, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal

# Available features for clustering
AVAILABLE_FEATURES = {
    "mean_volume": "Volume",
    "mean_surface_area": "Surface Area",
    "mean_centroid_x": "Centroid X",
    "mean_centroid_y": "Centroid Y",
    "mean_centroid_z": "Centroid Z",
    "total_distance_traveled": "Distance Traveled",
    "num_timepoints": "Timepoints",
    "t_start": "First Timepoint",
    "t_end": "Last Timepoint",
}


try:
    from BioVision.clustering.cell_clustering import CellClusteringAnalyzer
    CLUSTERING_AVAILABLE = True
except ImportError:
    CLUSTERING_AVAILABLE = False
    CellClusteringAnalyzer = None


class ClusteringWorker(QThread):
    """Worker thread for running clustering analysis."""
    progress = Signal(str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, analyzer: "CellClusteringAnalyzer", settings: dict):
        super().__init__()
        self.analyzer = analyzer
        self.settings = settings

    def run(self):
        try:
            self.progress.emit("Loading data...")
            self.analyzer.load_data()

            self.progress.emit("Extracting features...")
            self.analyzer.extract_features()

            if self.analyzer.features is None or len(self.analyzer.features) == 0:
                self.error.emit("No features could be extracted from the data.")
                return

            self.progress.emit("Performing clustering...")
            selected_features = self.settings.get("selected_features")
            self.analyzer.perform_clustering(
                n_clusters=self.settings["n_clusters"],
                method=self.settings["method"],
                remove_correlated=self.settings["remove_correlated"],
                correlation_threshold=self.settings["correlation_threshold"],
                selected_features=selected_features if selected_features else None,
            )

            self.progress.emit("Clustering complete!")

            # Build result mapping: cell_id -> cluster
            cluster_map = {}
            if self.analyzer.features is not None and "cluster" in self.analyzer.features.columns:
                for _, row in self.analyzer.features.iterrows():
                    cell_id = row.get("cell_id") or row.get("Cell ID")
                    cluster = row["cluster"]
                    if cell_id is not None:
                        cluster_map[int(cell_id)] = int(cluster)

            n_clusters = self.analyzer.clusters.get("n_clusters", 0) if self.analyzer.clusters else 0
            silhouette = self.analyzer.clusters.get("silhouette_score", 0.0) if self.analyzer.clusters else 0.0

            # Print cluster statistics to terminal
            self._print_cluster_statistics(n_clusters, silhouette)

            self.finished.emit({
                "cluster_map": cluster_map,
                "n_clusters": n_clusters,
                "silhouette_score": silhouette,
            })

        except Exception as e:
            self.error.emit(str(e))

    def _print_cluster_statistics(self, n_clusters: int, silhouette: float) -> None:
        """Print detailed cluster statistics to terminal."""
        if self.analyzer.features is None or "cluster" not in self.analyzer.features.columns:
            return

        features = self.analyzer.features
        selected = self.settings.get("selected_features", [])

        # Get feature columns (exclude cell_id and cluster)
        feature_cols = [col for col in features.columns if col not in ["cell_id", "Cell ID", "cluster", "outlines"]]
        if selected:
            feature_cols = [col for col in feature_cols if col in selected]

        print("\n" + "=" * 60)
        print("CLUSTERING RESULTS")
        print("=" * 60)
        print(f"Method: {self.settings.get('method', 'unknown')}")
        print(f"Number of clusters: {n_clusters}")
        print(f"Silhouette score: {silhouette:.4f}")
        print(f"Total cells: {len(features)}")
        print(f"Features used: {', '.join(feature_cols)}")
        print("=" * 60)

        # Statistics per cluster
        unique_clusters = sorted(features["cluster"].unique())
        for cluster_id in unique_clusters:
            cluster_data = features[features["cluster"] == cluster_id]
            n_cells = len(cluster_data)

            if cluster_id == -1:
                print(f"\nOUTLIERS (n={n_cells})")
            else:
                print(f"\nCLUSTER {cluster_id} (n={n_cells})")
            print("-" * 40)

            for col in feature_cols:
                if col in cluster_data.columns:
                    mean_val = cluster_data[col].mean()
                    std_val = cluster_data[col].std()
                    min_val = cluster_data[col].min()
                    max_val = cluster_data[col].max()
                    print(f"  {col}:")
                    print(f"    mean={mean_val:.4f}, std={std_val:.4f}")
                    print(f"    min={min_val:.4f}, max={max_val:.4f}")

        print("\n" + "=" * 60 + "\n")


class ClusteringPanel(QWidget):
    """Panel for cell clustering analysis."""

    clustering_complete = Signal(dict)  # Emits cluster assignments

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._data_path: Optional[Path] = None
        self._worker: Optional[ClusteringWorker] = None
        self._feature_checkboxes: Dict[str, QCheckBox] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Title
        title = QLabel("Clustering")
        title.setObjectName("ClusteringTitle")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        if not CLUSTERING_AVAILABLE:
            error_label = QLabel("Clustering module not available.\nInstall dependencies: sklearn, pandas, numpy")
            error_label.setStyleSheet("color: red;")
            layout.addWidget(error_label)
            layout.addStretch(1)
            return

        # Method selection
        method_group = QGroupBox("Clustering Method")
        method_layout = QHBoxLayout(method_group)

        method_layout.addWidget(QLabel("Method:"))
        self.method_combo = QComboBox()
        self.method_combo.addItems(["kmeans", "spectral", "hdbscan"])
        self.method_combo.currentTextChanged.connect(self._on_method_changed)
        method_layout.addWidget(self.method_combo)

        layout.addWidget(method_group)

        # Parameters
        params_group = QGroupBox("Parameters")
        params_layout = QVBoxLayout(params_group)

        # Number of clusters
        clusters_row = QHBoxLayout()
        clusters_row.addWidget(QLabel("Number of clusters:"))
        self.n_clusters_spin = QSpinBox()
        self.n_clusters_spin.setRange(2, 20)
        self.n_clusters_spin.setValue(3)
        clusters_row.addWidget(self.n_clusters_spin)
        clusters_row.addStretch()
        params_layout.addLayout(clusters_row)

        # Correlation threshold
        corr_row = QHBoxLayout()
        corr_row.addWidget(QLabel("Correlation threshold:"))
        self.corr_threshold_spin = QDoubleSpinBox()
        self.corr_threshold_spin.setRange(0.5, 1.0)
        self.corr_threshold_spin.setSingleStep(0.05)
        self.corr_threshold_spin.setValue(0.85)
        corr_row.addWidget(self.corr_threshold_spin)
        corr_row.addStretch()
        params_layout.addLayout(corr_row)

        # Remove correlated
        self.remove_correlated_check = QCheckBox("Remove correlated features")
        self.remove_correlated_check.setChecked(True)
        params_layout.addWidget(self.remove_correlated_check)

        layout.addWidget(params_group)

        # Feature selection
        features_group = QGroupBox("Features")
        features_layout = QVBoxLayout(features_group)

        # Quick selection buttons
        btn_row = QHBoxLayout()
        select_all_btn = QPushButton("All")
        select_all_btn.clicked.connect(self._select_all_features)
        btn_row.addWidget(select_all_btn)

        select_none_btn = QPushButton("None")
        select_none_btn.clicked.connect(self._select_no_features)
        btn_row.addWidget(select_none_btn)

        btn_row.addStretch()
        features_layout.addLayout(btn_row)

        # Feature checkboxes
        for feature_id, feature_name in AVAILABLE_FEATURES.items():
            checkbox = QCheckBox(feature_name)
            checkbox.setChecked(True)  # Default all selected
            checkbox.setToolTip(feature_id)
            self._feature_checkboxes[feature_id] = checkbox
            features_layout.addWidget(checkbox)

        layout.addWidget(features_group)

        # Run button
        self.run_button = QPushButton("Run Clustering")
        self.run_button.clicked.connect(self._run_clustering)
        self.run_button.setEnabled(False)
        layout.addWidget(self.run_button)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Data file selection
        data_group = QGroupBox("Data File")
        data_layout = QVBoxLayout(data_group)

        self.status_label = QLabel("No CSV file selected.")
        self.status_label.setWordWrap(True)
        data_layout.addWidget(self.status_label)

        self.browse_button = QPushButton("Browse CSV...")
        self.browse_button.clicked.connect(self._browse_csv)
        data_layout.addWidget(self.browse_button)

        layout.addWidget(data_group)

        # Results
        results_group = QGroupBox("Results")
        results_layout = QVBoxLayout(results_group)
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setMaximumHeight(100)
        results_layout.addWidget(self.results_text)
        layout.addWidget(results_group)

        layout.addStretch(1)

    def _on_method_changed(self, method: str) -> None:
        # HDBSCAN determines clusters automatically
        self.n_clusters_spin.setEnabled(method != "hdbscan")

    def _select_all_features(self) -> None:
        """Select all feature checkboxes."""
        for checkbox in self._feature_checkboxes.values():
            checkbox.setChecked(True)

    def _select_no_features(self) -> None:
        """Deselect all feature checkboxes."""
        for checkbox in self._feature_checkboxes.values():
            checkbox.setChecked(False)

    def _get_selected_features(self) -> List[str]:
        """Get list of selected feature IDs."""
        return [
            feature_id
            for feature_id, checkbox in self._feature_checkboxes.items()
            if checkbox.isChecked()
        ]

    def _browse_csv(self) -> None:
        """Open file dialog to select a CSV file for clustering."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Cell Data CSV",
            "",
            "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            self.set_data_path(Path(file_path))

    def set_data_path(self, path: Path | None) -> None:
        """Set the path to the data CSV file for clustering."""
        self._data_path = path
        enabled = path is not None and path.exists()
        if hasattr(self, "run_button"):
            self.run_button.setEnabled(enabled)
        if hasattr(self, "status_label"):
            if path and path.exists():
                self.status_label.setText(f"Data: {path.name}")
            else:
                self.status_label.setText("No CSV file found.\nUse 'Browse CSV...' to select one.")

    def _run_clustering(self) -> None:
        if not CLUSTERING_AVAILABLE:
            QMessageBox.critical(self, "Error", "Clustering module not available.")
            return

        if not self._data_path or not self._data_path.exists():
            QMessageBox.warning(self, "Warning", "No data file available for clustering.")
            return

        # Check that at least one feature is selected
        selected_features = self._get_selected_features()
        if not selected_features:
            QMessageBox.warning(self, "Warning", "Please select at least one feature for clustering.")
            return

        # Disable UI
        self.run_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.results_text.clear()
        self.status_label.setText("Running clustering...")

        # Create analyzer
        analyzer = CellClusteringAnalyzer(str(self._data_path))

        settings = {
            "n_clusters": self.n_clusters_spin.value(),
            "method": self.method_combo.currentText(),
            "remove_correlated": self.remove_correlated_check.isChecked(),
            "correlation_threshold": self.corr_threshold_spin.value(),
            "selected_features": selected_features,
        }

        # Run in worker thread
        self._worker = ClusteringWorker(analyzer, settings)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, message: str) -> None:
        self.status_label.setText(message)

    def _on_finished(self, result: dict) -> None:
        self.progress_bar.setVisible(False)
        self.run_button.setEnabled(True)
        self.status_label.setText("Clustering complete!")

        # Display results
        n_clusters = result.get("n_clusters", 0)
        silhouette = result.get("silhouette_score", 0.0)
        cluster_map = result.get("cluster_map", {})

        self.results_text.setText(
            f"Clusters found: {n_clusters}\n"
            f"Silhouette score: {silhouette:.3f}\n"
            f"Cells clustered: {len(cluster_map)}"
        )

        # Emit signal for main window to update colors
        self.clustering_complete.emit(result)

    def _on_error(self, message: str) -> None:
        self.progress_bar.setVisible(False)
        self.run_button.setEnabled(True)
        self.status_label.setText(f"Error: {message}")
        QMessageBox.critical(self, "Clustering Error", message)
