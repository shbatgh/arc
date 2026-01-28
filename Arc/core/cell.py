from __future__ import annotations

from dataclasses import dataclass, field

from vedo import Mesh


@dataclass
class Cell:
    cell_id: str
    mesh: Mesh
    metadata: dict = field(default_factory=dict)

    @property
    def volume(self) -> float:
        return self.mesh.volume()

    @property
    def area(self) -> float:
        return self.mesh.area()
    
    @property
    def center(self) -> tuple[float, float, float]:
        return tuple(self.mesh.center_of_mass())
