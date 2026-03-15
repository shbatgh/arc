"""Dark Fusion theme with design tokens from the Figma GUI document."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# Design tokens
WINDOW = QColor("#1A1C1F")
BASE = QColor("#141619")
SURFACE = QColor("#24272C")
TEXT = QColor("#E8ECF0")
TEXT_DIM = QColor("#8B919A")
ACCENT = QColor("#418CD2")
BORDER = QColor("#35393F")
HIGHLIGHT = ACCENT
HIGHLIGHT_TEXT = QColor("#FFFFFF")

QSS = """
QMainWindow, QDialog {
    background-color: #1A1C1F;
}
QMenuBar {
    background-color: #141619;
    color: #E8ECF0;
    border-bottom: 1px solid #35393F;
}
QMenuBar::item:selected {
    background-color: #24272C;
}
QMenu {
    background-color: #24272C;
    color: #E8ECF0;
    border: 1px solid #35393F;
}
QMenu::item:selected {
    background-color: #418CD2;
}
QTabWidget::pane {
    border: 1px solid #35393F;
    background-color: #1A1C1F;
}
QTabBar::tab {
    background-color: #141619;
    color: #8B919A;
    padding: 6px 14px;
    border: 1px solid #35393F;
    border-bottom: none;
}
QTabBar::tab:selected {
    background-color: #24272C;
    color: #E8ECF0;
}
QTableWidget {
    background-color: #141619;
    color: #E8ECF0;
    gridline-color: #35393F;
    border: 1px solid #35393F;
    selection-background-color: #418CD2;
}
QTableWidget::item {
    padding: 3px 6px;
}
QHeaderView::section {
    background-color: #24272C;
    color: #E8ECF0;
    padding: 4px 8px;
    border: 1px solid #35393F;
}
QSlider::groove:horizontal {
    height: 4px;
    background-color: #35393F;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px;
    height: 14px;
    margin: -5px 0;
    background-color: #418CD2;
    border-radius: 7px;
}
QSlider::sub-page:horizontal {
    background-color: #418CD2;
    border-radius: 2px;
}
QPushButton {
    background-color: #24272C;
    color: #E8ECF0;
    border: 1px solid #35393F;
    padding: 5px 12px;
    border-radius: 3px;
}
QPushButton:hover {
    background-color: #35393F;
}
QPushButton:pressed {
    background-color: #418CD2;
}
QPushButton:disabled {
    color: #55595F;
}
QLabel {
    color: #E8ECF0;
}
QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #141619;
    color: #E8ECF0;
    border: 1px solid #35393F;
    padding: 3px 6px;
    border-radius: 3px;
}
QCheckBox {
    color: #E8ECF0;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
}
QSplitter::handle {
    background-color: #35393F;
}
QTextEdit, QPlainTextEdit {
    background-color: #141619;
    color: #E8ECF0;
    border: 1px solid #35393F;
}
QGraphicsView {
    background-color: #141619;
    border: 1px solid #35393F;
}
QStatusBar {
    background-color: #141619;
    color: #8B919A;
    border-top: 1px solid #35393F;
}
QProgressBar {
    background-color: #141619;
    border: 1px solid #35393F;
    border-radius: 3px;
    text-align: center;
    color: #E8ECF0;
}
QProgressBar::chunk {
    background-color: #418CD2;
    border-radius: 2px;
}
"""


def apply_theme(app: QApplication) -> None:
    """Apply the dark Fusion theme to the application."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, WINDOW)
    palette.setColor(QPalette.ColorRole.WindowText, TEXT)
    palette.setColor(QPalette.ColorRole.Base, BASE)
    palette.setColor(QPalette.ColorRole.AlternateBase, SURFACE)
    palette.setColor(QPalette.ColorRole.Text, TEXT)
    palette.setColor(QPalette.ColorRole.Button, SURFACE)
    palette.setColor(QPalette.ColorRole.ButtonText, TEXT)
    palette.setColor(QPalette.ColorRole.Highlight, HIGHLIGHT)
    palette.setColor(QPalette.ColorRole.HighlightedText, HIGHLIGHT_TEXT)
    palette.setColor(QPalette.ColorRole.ToolTipBase, SURFACE)
    palette.setColor(QPalette.ColorRole.ToolTipText, TEXT)
    palette.setColor(QPalette.ColorRole.PlaceholderText, TEXT_DIM)
    palette.setColor(QPalette.ColorRole.BrightText, HIGHLIGHT_TEXT)
    palette.setColor(QPalette.ColorRole.Link, ACCENT)

    # Disabled colors
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, TEXT_DIM)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, TEXT_DIM)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, TEXT_DIM)

    app.setPalette(palette)
    app.setStyleSheet(QSS)
