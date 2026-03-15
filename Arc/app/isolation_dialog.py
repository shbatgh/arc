"""Modal dialog for configuring cell isolation color filters before pipeline run."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from Arc.core.isolation_config import IsolationConfig


class CellIsolationDialog(QDialog):
    def __init__(self, parent: QWidget | None, dataset_dir: Path):
        super().__init__(parent)
        self.setWindowTitle("Cell Isolation")
        self.setMinimumWidth(340)
        self._skipped = False

        layout = QVBoxLayout(self)

        # Enable checkbox
        self._enable_cb = QCheckBox("Enable Cell Isolation")
        layout.addWidget(self._enable_cb)

        # Controls container
        self._controls = QWidget()
        controls_layout = QVBoxLayout(self._controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        # Color space selector
        cs_row = QHBoxLayout()
        cs_row.addWidget(QLabel("Color Space:"))
        self._cs_combo = QComboBox()
        self._cs_combo.addItems(["HSV", "RGB"])
        cs_row.addWidget(self._cs_combo)
        controls_layout.addLayout(cs_row)

        # HSV group
        self._hsv_group = QGroupBox("HSV Bounds")
        hsv_layout = QVBoxLayout(self._hsv_group)
        self._hsv_lower = self._make_bound_row(hsv_layout, "Lower", [("H", 0, 179, 35), ("S", 0, 255, 70), ("V", 0, 255, 90)])
        self._hsv_upper = self._make_bound_row(hsv_layout, "Upper", [("H", 0, 179, 85), ("S", 0, 255, 255), ("V", 0, 255, 255)])
        controls_layout.addWidget(self._hsv_group)

        # RGB group
        self._rgb_group = QGroupBox("RGB Bounds")
        rgb_layout = QVBoxLayout(self._rgb_group)
        self._rgb_lower = self._make_bound_row(rgb_layout, "Lower", [("R", 0, 255, 0), ("G", 0, 255, 100), ("B", 0, 255, 0)])
        self._rgb_upper = self._make_bound_row(rgb_layout, "Upper", [("R", 0, 255, 100), ("G", 0, 255, 255), ("B", 0, 255, 100)])
        controls_layout.addWidget(self._rgb_group)

        # Pixel ratio
        ratio_row = QHBoxLayout()
        ratio_row.addWidget(QLabel("Pixel Ratio:"))
        self._ratio_spin = QDoubleSpinBox()
        self._ratio_spin.setRange(0.01, 1.00)
        self._ratio_spin.setSingleStep(0.05)
        self._ratio_spin.setValue(0.50)
        ratio_row.addWidget(self._ratio_spin)
        controls_layout.addLayout(ratio_row)

        # Warning label
        self._warning_label = QLabel()
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet("color: #b8860b; font-weight: bold;")
        self._warning_label.setVisible(False)
        controls_layout.addWidget(self._warning_label)

        has_seg = any(dataset_dir.rglob("*_seg.npy"))
        if not has_seg:
            self._warning_label.setText(
                "Warning: No *_seg.npy files found in this dataset. "
                "Cell isolation requires Cellpose segmentation output."
            )
            self._warning_label.setVisible(True)

        layout.addWidget(self._controls)

        # Buttons
        btn_row = QHBoxLayout()
        self._skip_btn = QPushButton("Skip")
        self._run_btn = QPushButton("Run with Isolation")
        btn_row.addWidget(self._skip_btn)
        btn_row.addWidget(self._run_btn)
        layout.addLayout(btn_row)

        # Connections
        self._enable_cb.toggled.connect(self._controls.setEnabled)
        self._enable_cb.toggled.connect(self._run_btn.setEnabled)
        self._cs_combo.currentTextChanged.connect(self._on_color_space_changed)
        self._skip_btn.clicked.connect(self._on_skip)
        self._run_btn.clicked.connect(self.accept)

        # Initial state
        self._controls.setEnabled(False)
        self._run_btn.setEnabled(False)
        self._rgb_group.setVisible(False)

    def _make_bound_row(
        self,
        parent_layout: QVBoxLayout,
        label: str,
        channels: list[tuple[str, int, int, int]],
    ) -> list[QSpinBox]:
        row = QHBoxLayout()
        row.addWidget(QLabel(f"{label}:"))
        spins: list[QSpinBox] = []
        for name, lo, hi, default in channels:
            row.addWidget(QLabel(name))
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(default)
            row.addWidget(spin)
            spins.append(spin)
        parent_layout.addLayout(row)
        return spins

    def _on_color_space_changed(self, text: str):
        self._hsv_group.setVisible(text == "HSV")
        self._rgb_group.setVisible(text == "RGB")

    def _on_skip(self):
        self._skipped = True
        self.accept()

    def get_result(self) -> tuple[bool, IsolationConfig | None]:
        if self.result() != QDialog.DialogCode.Accepted:
            return False, None
        if self._skipped or not self._enable_cb.isChecked():
            return True, None
        cs = self._cs_combo.currentText().lower()
        if cs == "hsv":
            lower = tuple(s.value() for s in self._hsv_lower)
            upper = tuple(s.value() for s in self._hsv_upper)
        else:
            lower = tuple(s.value() for s in self._rgb_lower)
            upper = tuple(s.value() for s in self._rgb_upper)
        return True, IsolationConfig(
            color_space=cs,
            lower=lower,  # type: ignore[arg-type]
            upper=upper,  # type: ignore[arg-type]
            ratio=self._ratio_spin.value(),
        )

    @staticmethod
    def get_config(parent: QWidget | None, dataset_dir: Path) -> tuple[bool, IsolationConfig | None]:
        dlg = CellIsolationDialog(parent, dataset_dir)
        dlg.exec()
        return dlg.get_result()
