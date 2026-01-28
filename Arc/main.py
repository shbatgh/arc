import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

if __package__ in {None, ""}:  # Allow running as a script.
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from Arc.app.main_window import MainWindow


def _apply_stylesheet(app: QApplication) -> None:
    qss_path = Path(__file__).resolve().parent / "resources" / "styles" / "dark.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ARC")
    _apply_stylesheet(app)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
