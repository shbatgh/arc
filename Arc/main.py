"""ARC application entry point."""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so `Arc.*` imports resolve
# when running as `uv run python Arc/main.py` from the repo root.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from PySide6.QtWidgets import QApplication

from Arc.app.theme import apply_theme
from Arc.app.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
