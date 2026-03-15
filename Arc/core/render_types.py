"""Render data types — Python port of arc-c++/src/render/api/render_types.hpp.

Uses numpy arrays instead of Python lists for mesh data to enable
zero-copy VTK data transfer and fast bundle loading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

import numpy as np


class PrimitiveType(Enum):
    Triangles = auto()
    Lines = auto()


class CameraMode(Enum):
    FreeFly = auto()
    Orbit = auto()


@dataclass
class CellStyle:
    color: tuple[float, float, float] = (0.8, 0.2, 0.2)
    opacity: float = 1.0
    wireframe: bool = False
    visible: bool = True
    line_width: float = 1.5


@dataclass
class MeshGeometry:
    primitive: PrimitiveType = PrimitiveType.Triangles
    vertices: np.ndarray = field(default_factory=lambda: np.empty((0, 3), dtype=np.float32))
    faces: np.ndarray = field(default_factory=lambda: np.empty((0, 3), dtype=np.uint32))


@dataclass
class RenderCellMesh:
    cell_id: str = ""
    track_id: int = -1
    geometry: MeshGeometry = field(default_factory=MeshGeometry)
    style: CellStyle = field(default_factory=CellStyle)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class RenderFrame:
    timepoint: int = 0
    cells: list[RenderCellMesh] = field(default_factory=list)


@dataclass
class RenderScene:
    frames: list[RenderFrame] = field(default_factory=list)


@dataclass
class RenderInitOptions:
    enable_axes: bool = False
    background: tuple[float, float, float] = (0.06, 0.07, 0.08)
