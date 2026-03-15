"""Load raw Cellpose outline stacks into a RenderScene."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import numpy as np

from Arc.core.render_types import (
    CellStyle,
    MeshGeometry,
    PrimitiveType,
    RenderCellMesh,
    RenderFrame,
    RenderScene,
)
from Arc.io.outline_editor import cell_color_from_id

# 3 um per Z-slice / 0.198 um per XY pixel (matches Perf/BioVision/processing/constants.py)
DEFAULT_Z_SPACING = 3.0 / 0.198
ProgressCallback = Callable[[int, str], None]


def _emit_progress(
    progress_cb: ProgressCallback | None,
    value: int,
    label: str,
) -> None:
    if progress_cb is None:
        return
    progress_cb(max(0, min(100, int(value))), label)


def _parse_int_token(value: str) -> int:
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else 0


def _sorted_timepoint_dirs(dataset_dir: Path) -> list[Path]:
    return sorted(
        [path for path in dataset_dir.iterdir() if path.is_dir()],
        key=lambda path: (_parse_int_token(path.name), path.name),
    )


def load_raw_outlines(
    dataset_dir: Path,
    progress_cb: ProgressCallback | None = None,
) -> tuple[RenderScene, dict]:
    """Parse `_cp_outlines.txt` files directly into line-strip render cells."""
    dataset_dir = dataset_dir.resolve()
    if not dataset_dir.is_dir():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")

    frames: list[RenderFrame] = []
    total_outline_count = 0
    max_slice_count = 0

    timepoint_dirs = _sorted_timepoint_dirs(dataset_dir)
    if not timepoint_dirs:
        raise ValueError(f"No timepoint directories found in {dataset_dir}")

    timepoint_entries: list[tuple[int, Path, list[Path]]] = []
    total_slice_files = 0
    for timepoint_idx, timepoint_dir in enumerate(timepoint_dirs):
        cp_files = sorted(
            timepoint_dir.glob("*_cp_outlines.txt"),
            key=lambda path: (_parse_int_token(path.stem), path.name),
        )
        timepoint_entries.append((timepoint_idx, timepoint_dir, cp_files))
        total_slice_files += len(cp_files)

    _emit_progress(
        progress_cb,
        0,
        f"Scanning raw outlines: {dataset_dir.name}...",
    )

    processed_slice_files = 0
    last_progress = 5
    _emit_progress(progress_cb, last_progress, "Preparing raw outline scene...")

    for timepoint_idx, timepoint_dir, cp_files in timepoint_entries:
        if not cp_files:
            continue

        frame_cells: list[RenderCellMesh] = []
        max_slice_count = max(max_slice_count, len(cp_files))

        for slice_idx, cp_path in enumerate(cp_files):
            z_value = np.float32(slice_idx * DEFAULT_Z_SPACING)
            with cp_path.open("r", encoding="utf-8") as handle:
                for outline_idx, line in enumerate(handle, start=1):
                    coords = [part for part in line.strip().split(",") if part]
                    if len(coords) < 4 or len(coords) % 2 != 0:
                        continue

                    points_2d = [
                        (float(coords[i]), float(coords[i + 1]))
                        for i in range(0, len(coords), 2)
                    ]
                    if len(points_2d) < 2:
                        continue

                    if points_2d[0] != points_2d[-1]:
                        points_2d.append(points_2d[0])

                    vertices = np.array(
                        [[x, y, float(z_value)] for x, y in points_2d],
                        dtype=np.float32,
                    )

                    cell_id_str = (
                        f"t{timepoint_idx + 1}_slice{slice_idx + 1}_"
                        f"outline{outline_idx}"
                    )
                    frame_cells.append(
                        RenderCellMesh(
                            cell_id=cell_id_str,
                            track_id=-1,
                            geometry=MeshGeometry(
                                primitive=PrimitiveType.Lines,
                                vertices=vertices,
                                faces=np.empty((0, 3), dtype=np.uint32),
                            ),
                            style=CellStyle(
                                color=cell_color_from_id(cell_id_str),
                                opacity=1.0,
                                line_width=2.0,
                            ),
                            metadata={
                                "timepoint": str(timepoint_idx),
                                "slice_index": str(slice_idx + 1),
                                "outline_index": str(outline_idx),
                                "point_count": str(len(points_2d) - 1),
                                "source_file": cp_path.name,
                            },
                        )
                    )

            processed_slice_files += 1
            slice_progress = 95
            if total_slice_files > 0:
                slice_progress = 5 + int((processed_slice_files * 90) / total_slice_files)
            if slice_progress > last_progress:
                _emit_progress(
                    progress_cb,
                    slice_progress,
                    (
                        "Parsing raw outlines "
                        f"({processed_slice_files}/{total_slice_files} slices)..."
                    ),
                )
                last_progress = slice_progress

        total_outline_count += len(frame_cells)
        frames.append(RenderFrame(timepoint=timepoint_idx, cells=frame_cells))

    if not frames:
        raise ValueError(
            f"No `_cp_outlines.txt` files with usable outlines were found in {dataset_dir}"
        )

    metadata = {
        "dataset_name": dataset_dir.name,
        "format": "raw_cp_outlines",
        "num_timepoints": len(frames),
        "outline_count": total_outline_count,
        "max_slices": max_slice_count,
        "z_spacing": DEFAULT_Z_SPACING,
    }
    _emit_progress(progress_cb, 100, f"Loaded raw outlines: {dataset_dir.name}")
    return RenderScene(frames=frames), metadata
