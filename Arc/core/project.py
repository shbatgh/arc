from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from Arc.core.scene import Scene


@dataclass
class Project:
    name: str = "Untitled"
    scenes: Dict[int, Scene] = field(default_factory=dict)

    def get_or_create_scene(self, timepoint: int = 0) -> Scene:
        if timepoint not in self.scenes:
            self.scenes[timepoint] = Scene(timepoint=timepoint)
        return self.scenes[timepoint]
