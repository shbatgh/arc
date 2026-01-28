from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from Arc.core.cell import Cell


@dataclass
class Scene:
    timepoint: int = 0
    cells: Dict[str, Cell] = field(default_factory=dict)

    def add_cell(self, cell: Cell) -> None:
        self.cells[cell.cell_id] = cell

    def meshes(self) -> List:
        return [cell.mesh for cell in self.cells.values()]

    def __iter__(self) -> Iterable[Cell]:
        return iter(self.cells.values())
