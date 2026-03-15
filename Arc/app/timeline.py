"""Timeline playback panel with slider and play/pause."""

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QSlider


class TimelinePanel(QWidget):
    """Horizontal panel: [Play/Pause] [Label] [Slider]."""

    timepoint_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self._play_btn = QPushButton("Play")
        self._play_btn.setFixedWidth(60)
        self._play_btn.clicked.connect(self._toggle_play)
        layout.addWidget(self._play_btn)

        self._label = QLabel("0 / 0")
        self._label.setFixedWidth(80)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self._slider, stretch=1)

        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._tick)

        self._playing = False
        self._num_frames = 0

    def setup(self, num_frames: int, start: int = 0) -> None:
        """Configure the timeline for a given number of frames."""
        self._num_frames = num_frames
        self._slider.setMaximum(max(0, num_frames - 1))
        self._slider.setValue(start)
        self._update_label()

    def current_timepoint(self) -> int:
        return self._slider.value()

    def _on_slider_changed(self, value: int) -> None:
        self._update_label()
        self.timepoint_changed.emit(value)

    def _update_label(self) -> None:
        current = self._slider.value() + 1
        total = self._num_frames
        self._label.setText(f"{current} / {total}")

    def _toggle_play(self) -> None:
        self._playing = not self._playing
        if self._playing:
            self._play_btn.setText("Pause")
            self._timer.start()
        else:
            self._play_btn.setText("Play")
            self._timer.stop()

    def _tick(self) -> None:
        if self._num_frames <= 0:
            return
        next_val = (self._slider.value() + 1) % self._num_frames
        self._slider.setValue(next_val)
