"""Render backend protocol — Python port of arc-c++/src/render/api/irender_backend.hpp."""

from __future__ import annotations

from typing import Callable, Protocol

from PySide6.QtWidgets import QWidget

from Arc.core.render_types import (
    CameraMode,
    CellStyle,
    RenderInitOptions,
    RenderScene,
)


class IRenderBackend(Protocol):
    on_cell_picked: Callable[[str], None] | None
    on_frame_ready: Callable[[int], None] | None

    def initialize(self, host: QWidget, options: RenderInitOptions) -> bool: ...
    def shutdown(self) -> None: ...
    def set_scene(self, scene: RenderScene) -> None: ...
    def set_timepoint(self, timepoint: int) -> None: ...
    def update_cell_style(self, cell_id: str, style: CellStyle) -> None: ...
    def set_wireframe(self, enabled: bool) -> None: ...
    def set_camera_mode(self, mode: CameraMode) -> None: ...
    def fit_scene(self) -> None: ...
