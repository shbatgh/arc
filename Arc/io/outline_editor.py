"""Read, write, and back up Cellpose _cp_outlines.txt files."""

from __future__ import annotations

import colorsys
import hashlib
import math
import shutil
from pathlib import Path


def cell_color_from_id(cell_id: int | str) -> tuple[float, float, float]:
    """Deterministic RGB color (0.0-1.0) from a cell identifier."""
    if isinstance(cell_id, int):
        h = cell_id
    else:
        h = int(hashlib.md5(str(cell_id).encode()).hexdigest()[:8], 16)
    hue = (h * 0.618033988749895) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.75, 0.90)
    return (r, g, b)


def match_outlines_to_cells(
    outline_files: list[Path],
    dist_multiplier: float = 0.7,
) -> dict[tuple[int, int], int]:
    """Group outlines across Z-slices into cells by centroid proximity.

    Returns: {(slice_idx, outline_idx): cell_id}
    """
    # Read all outlines per slice
    slices: list[list[list[tuple[float, float]]]] = []
    for cp_path in outline_files:
        slices.append(read_outlines(cp_path))

    assignments: dict[tuple[int, int], int] = {}
    next_cell_id = 0

    if not slices:
        return assignments

    # Bottom slice: each outline is a new cell
    prev_centroids: list[tuple[float, float]] = []
    prev_outlines: list[list[tuple[float, float]]] = []
    prev_cell_ids: list[int] = []
    for outline_idx, outline in enumerate(slices[0]):
        cid = next_cell_id
        next_cell_id += 1
        assignments[(0, outline_idx)] = cid
        prev_centroids.append(_centroid(outline))
        prev_outlines.append(outline)
        prev_cell_ids.append(cid)

    # Match subsequent slices
    for slice_idx in range(1, len(slices)):
        cur_outlines = slices[slice_idx]
        if not cur_outlines:
            prev_centroids = []
            prev_outlines = []
            prev_cell_ids = []
            continue

        cur_centroids = [_centroid(o) for o in cur_outlines]

        if not prev_centroids:
            # No previous slice to match against — all new cells
            new_prev_centroids: list[tuple[float, float]] = []
            new_prev_outlines: list[list[tuple[float, float]]] = []
            new_prev_cell_ids: list[int] = []
            for oi, outline in enumerate(cur_outlines):
                cid = next_cell_id
                next_cell_id += 1
                assignments[(slice_idx, oi)] = cid
                new_prev_centroids.append(cur_centroids[oi])
                new_prev_outlines.append(outline)
                new_prev_cell_ids.append(cid)
            prev_centroids = new_prev_centroids
            prev_outlines = new_prev_outlines
            prev_cell_ids = new_prev_cell_ids
            continue

        # Compute all pairwise distances
        pairs: list[tuple[float, int, int]] = []  # (dist, cur_idx, prev_idx)
        for ci, cc in enumerate(cur_centroids):
            for pi, pc in enumerate(prev_centroids):
                pairs.append((math.dist(cc, pc), ci, pi))
        pairs.sort()

        matched_cur: set[int] = set()
        matched_prev: set[int] = set()
        cur_cell_ids: dict[int, int] = {}

        for dist, ci, pi in pairs:
            if ci in matched_cur or pi in matched_prev:
                continue
            # Distance threshold based on bounding-box size
            max_dim_cur = _bbox_max_dim(cur_outlines[ci])
            max_dim_prev = _bbox_max_dim(prev_outlines[pi])
            max_error = max(max_dim_cur, max_dim_prev) * dist_multiplier
            if dist >= max_error:
                continue
            cur_cell_ids[ci] = prev_cell_ids[pi]
            matched_cur.add(ci)
            matched_prev.add(pi)

        # Assign cell IDs
        new_prev_centroids2: list[tuple[float, float]] = []
        new_prev_outlines2: list[list[tuple[float, float]]] = []
        new_prev_cell_ids2: list[int] = []
        for oi, outline in enumerate(cur_outlines):
            if oi in cur_cell_ids:
                cid = cur_cell_ids[oi]
            else:
                cid = next_cell_id
                next_cell_id += 1
            assignments[(slice_idx, oi)] = cid
            new_prev_centroids2.append(cur_centroids[oi])
            new_prev_outlines2.append(outline)
            new_prev_cell_ids2.append(cid)

        prev_centroids = new_prev_centroids2
        prev_outlines = new_prev_outlines2
        prev_cell_ids = new_prev_cell_ids2

    return assignments


def _centroid(outline: list[tuple[float, float]]) -> tuple[float, float]:
    n = len(outline)
    if n == 0:
        return (0.0, 0.0)
    sx = sum(p[0] for p in outline)
    sy = sum(p[1] for p in outline)
    return (sx / n, sy / n)


def _bbox_max_dim(outline: list[tuple[float, float]]) -> float:
    if not outline:
        return 0.0
    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def read_outlines(cp_path: Path) -> list[list[tuple[float, float]]]:
    """Parse _cp_outlines.txt into a list of polygons (list of (x, y) tuples)."""
    outlines: list[list[tuple[float, float]]] = []
    with cp_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            coords = [part for part in line.strip().split(",") if part]
            if len(coords) < 4 or len(coords) % 2 != 0:
                continue
            points = [
                (float(coords[i]), float(coords[i + 1]))
                for i in range(0, len(coords), 2)
            ]
            if len(points) >= 2:
                outlines.append(points)
    return outlines


def write_outlines(cp_path: Path, outlines: list[list[tuple[float, float]]]) -> None:
    """Write outlines back in x,y,x,y,... format (one line per outline)."""
    with cp_path.open("w", encoding="utf-8") as fh:
        for polygon in outlines:
            parts: list[str] = []
            for x, y in polygon:
                parts.append(str(int(x)) if x == int(x) else str(x))
                parts.append(str(int(y)) if y == int(y) else str(y))
            fh.write(",".join(parts) + "\n")


def backup_outlines(cp_path: Path) -> Path:
    """Copy to .bak before editing. Returns backup path."""
    bak_path = cp_path.with_suffix(cp_path.suffix + ".bak")
    shutil.copy2(cp_path, bak_path)
    return bak_path
