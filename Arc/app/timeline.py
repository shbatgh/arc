from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QWidget
from PySide6.QtCore import Qt, QTimer


class Timeline(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        title = QLabel("Timeline")
        title.setObjectName("TimelineTitle")
        layout.addWidget(title)

        self.play_button = QPushButton("Play")
        self.play_button.setObjectName("TimelinePlayButton")
        self.play_button.clicked.connect(self._toggle_play)
        layout.addWidget(self.play_button)

        self.timepoint_label = QLabel("t0")
        self.timepoint_label.setObjectName("TimelineTimepointLabel")
        layout.addWidget(self.timepoint_label)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("TimelineSlider")
        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        layout.addWidget(self.slider, stretch=1)

        # Playback timer
        self._playing = False
        self._timer = QTimer(self)
        self._timer.setInterval(250)  # 100ms per frame = 10 fps
        self._timer.timeout.connect(self._advance_frame)

    def _toggle_play(self) -> None:
        if self._playing:
            self._stop()
        else:
            self._play()

    def _play(self) -> None:
        if self.slider.maximum() == 0:
            return
        self._playing = True
        self.play_button.setText("Pause")
        self._timer.start()

    def _stop(self) -> None:
        self._playing = False
        self.play_button.setText("Play")
        self._timer.stop()

    def _advance_frame(self) -> None:
        current = self.slider.value()
        max_val = self.slider.maximum()
        if current >= max_val:
            # Loop back to start
            self.slider.setValue(0)
        else:
            self.slider.setValue(current + 1)

    def set_range(self, count: int) -> None:
        self._stop()
        count = max(0, count)
        self.slider.setMinimum(0)
        self.slider.setMaximum(max(0, count - 1))
        self.slider.setValue(0)

    def set_timepoint_label(self, text: str) -> None:
        self.timepoint_label.setText(text)
