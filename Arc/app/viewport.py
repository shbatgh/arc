"""Qt viewport widget for embedding VTK."""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout

import vtkmodules.vtkRenderingOpenGL2  # noqa: F401
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor


class ViewportWidget(QWidget):
    """Thin wrapper around QVTKRenderWindowInteractor with its own render window."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._vtk_widget = QVTKRenderWindowInteractor(self)
        # QVTKRenderWindowInteractor wires its own render window and interactor
        # together. Swapping in a second render window leaves the widget painting
        # one window while the backend renders into another.
        self._render_window = self._vtk_widget.GetRenderWindow()
        self._started = False
        layout.addWidget(self._vtk_widget)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def render_window(self):
        return self._render_window

    def interactor(self):
        return self._vtk_widget

    def start(self):
        """Initialize the interactor (call once after renderer is attached)."""
        if self._started:
            return
        if not self.isVisible():
            QTimer.singleShot(0, self.start)
            return
        self._vtk_widget.Initialize()
        self._vtk_widget.Start()
        self._started = True

    def focusInEvent(self, event):
        self._vtk_widget.setFocus()
        super().focusInEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.start()
