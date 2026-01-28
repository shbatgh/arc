from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QFileDialog, QWidget


def get_export_path(parent: Optional[QWidget] = None) -> Optional[str]:
    path, _ = QFileDialog.getSaveFileName(
        parent,
        "Export",
        "",
        "Mesh Files (*.obj *.stl *.ply)",
    )
    return path or None
