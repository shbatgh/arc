from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import math

from Arc.core.cell import Cell


@dataclass
class Cell4D:
    """
    A 4D cell that tracks a single cell across multiple timepoints.

    Attributes:
        track_id: Unique identifier for this cell track
        cells: Dictionary mapping timepoint -> Cell instance
        t_start: First timepoint where this cell appears
        t_end: Last timepoint where this cell appears
    """
    track_id: int
    cells: Dict[int, Cell] = field(default_factory=dict)

    @property
    def t_start(self) -> int:
        """First timepoint where this cell appears."""
        if not self.cells:
            return 0
        return min(self.cells.keys())

    @property
    def t_end(self) -> int:
        """Last timepoint where this cell appears."""
        if not self.cells:
            return 0
        return max(self.cells.keys())

    @property
    def display_id(self) -> str:
        """Display ID in format tstart-tend_idnumber."""
        return f"t{self.t_start}-t{self.t_end}_{self.track_id:03d}"

    @property
    def timepoints(self) -> List[int]:
        """List of timepoints where this cell exists."""
        return sorted(self.cells.keys())

    @property
    def lifespan(self) -> int:
        """Number of timepoints this cell exists."""
        return len(self.cells)

    def add_cell(self, timepoint: int, cell: Cell) -> None:
        """Add a cell observation at a timepoint."""
        self.cells[timepoint] = cell
        # Update cell metadata with track info
        cell.metadata["track_id"] = self.track_id
        cell.metadata["t_start"] = self.t_start
        cell.metadata["t_end"] = self.t_end

    def get_cell(self, timepoint: int) -> Optional[Cell]:
        """Get the cell at a specific timepoint."""
        return self.cells.get(timepoint)

    def get_center_at(self, timepoint: int) -> Optional[Tuple[float, float, float]]:
        """Get the cell center at a specific timepoint."""
        cell = self.cells.get(timepoint)
        if cell:
            return cell.center
        return None

    def update_all_metadata(self) -> None:
        """Update metadata for all cells with current track info."""
        for cell in self.cells.values():
            cell.metadata["track_id"] = self.track_id
            cell.metadata["t_start"] = self.t_start
            cell.metadata["t_end"] = self.t_end
            cell.metadata["display_id"] = self.display_id


class CellTracker:
    """
    Tracks cells across timepoints by matching based on spatial proximity.
    """

    def __init__(self, max_distance: float = 50.0):
        """
        Initialize the cell tracker.

        Args:
            max_distance: Maximum distance (in spatial units) to consider
                         two cells as the same cell between timepoints.
        """
        self.max_distance = max_distance
        self.tracks: Dict[int, Cell4D] = {}
        self._next_track_id = 0

    def _distance(self, p1: Tuple[float, float, float], p2: Tuple[float, float, float]) -> float:
        """Euclidean distance between two 3D points."""
        return math.sqrt(
            (p1[0] - p2[0]) ** 2 +
            (p1[1] - p2[1]) ** 2 +
            (p1[2] - p2[2]) ** 2
        )

    def _create_new_track(self, cell: Cell, timepoint: int) -> Cell4D:
        """Create a new track for an unmatched cell."""
        track = Cell4D(track_id=self._next_track_id)
        track.add_cell(timepoint, cell)
        self.tracks[self._next_track_id] = track
        self._next_track_id += 1
        return track

    def track_cells(self, scenes: Dict[int, "Scene"]) -> Dict[int, Cell4D]:
        """
        Track cells across all scenes/timepoints.

        Args:
            scenes: Dictionary mapping timepoint -> Scene

        Returns:
            Dictionary mapping track_id -> Cell4D
        """
        from Arc.core.scene import Scene

        self.tracks.clear()
        self._next_track_id = 0

        if not scenes:
            return self.tracks

        # Process timepoints in order
        sorted_timepoints = sorted(scenes.keys())

        # First timepoint: create new tracks for all cells
        first_tp = sorted_timepoints[0]
        first_scene = scenes[first_tp]

        for cell in first_scene.cells.values():
            self._create_new_track(cell, first_tp)

        # Process subsequent timepoints
        for i in range(1, len(sorted_timepoints)):
            current_tp = sorted_timepoints[i]
            prev_tp = sorted_timepoints[i - 1]
            current_scene = scenes[current_tp]

            # Get cells from current timepoint that need to be matched
            unmatched_cells = list(current_scene.cells.values())

            # Get active tracks (tracks that had a cell in the previous timepoint)
            active_tracks = [
                track for track in self.tracks.values()
                if prev_tp in track.cells
            ]

            # Build cost matrix based on distances
            matches = []
            for cell in unmatched_cells:
                try:
                    cell_center = cell.center
                except Exception:
                    continue

                best_track = None
                best_distance = self.max_distance

                for track in active_tracks:
                    prev_center = track.get_center_at(prev_tp)
                    if prev_center is None:
                        continue

                    dist = self._distance(cell_center, prev_center)
                    if dist < best_distance:
                        best_distance = dist
                        best_track = track

                if best_track is not None:
                    matches.append((cell, best_track, best_distance))

            # Sort matches by distance (greedy assignment)
            matches.sort(key=lambda x: x[2])

            # Assign cells to tracks
            matched_tracks = set()
            matched_cells = set()

            for cell, track, dist in matches:
                cell_id = id(cell)
                if track.track_id not in matched_tracks and cell_id not in matched_cells:
                    track.add_cell(current_tp, cell)
                    matched_tracks.add(track.track_id)
                    matched_cells.add(cell_id)

            # Create new tracks for unmatched cells
            for cell in unmatched_cells:
                if id(cell) not in matched_cells:
                    self._create_new_track(cell, current_tp)

        # Update all metadata after tracking is complete
        for track in self.tracks.values():
            track.update_all_metadata()

        return self.tracks

    def get_track_for_cell(self, cell: Cell) -> Optional[Cell4D]:
        """Find the track that contains a given cell."""
        for track in self.tracks.values():
            if cell in track.cells.values():
                return track
        return None
