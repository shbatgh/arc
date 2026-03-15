"""Clustering panel UI stub (Phase 2+)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QSpinBox,
    QPushButton,
    QTextEdit,
    QCheckBox,
    QGroupBox,
)


class ClusteringPanel(QWidget):
    """Stub clustering panel with method selection, k, features, and run button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Method
        method_row = QHBoxLayout()
        method_row.addWidget(QLabel("Method:"))
        self._method_combo = QComboBox()
        self._method_combo.addItems(["KMeans", "Spectral", "HDBSCAN"])
        method_row.addWidget(self._method_combo)
        layout.addLayout(method_row)

        # K
        k_row = QHBoxLayout()
        k_row.addWidget(QLabel("k:"))
        self._k_spin = QSpinBox()
        self._k_spin.setRange(2, 50)
        self._k_spin.setValue(5)
        k_row.addWidget(self._k_spin)
        layout.addLayout(k_row)

        # Features
        features_group = QGroupBox("Features")
        features_layout = QVBoxLayout(features_group)
        self._feature_checks: dict[str, QCheckBox] = {}
        for name in ["volume", "surface_area", "displacement", "distance"]:
            cb = QCheckBox(name)
            cb.setChecked(True)
            features_layout.addWidget(cb)
            self._feature_checks[name] = cb
        layout.addWidget(features_group)

        # Run
        self._run_btn = QPushButton("Run Clustering")
        self._run_btn.setEnabled(False)
        layout.addWidget(self._run_btn)

        # Results
        self._results = QTextEdit()
        self._results.setReadOnly(True)
        self._results.setPlaceholderText("Clustering results will appear here...")
        self._results.setMaximumHeight(150)
        layout.addWidget(self._results)

        layout.addStretch()
