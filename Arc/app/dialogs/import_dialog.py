from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QFileDialog, QWidget


def get_import_folder(parent: Optional[QWidget] = None) -> Optional[str]:
    folder = QFileDialog.getExistingDirectory(
        parent,
        "Import Mesh Folder",
        "",
        QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
    )
    return folder or None
