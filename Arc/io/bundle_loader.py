"""Load a BioVision animation bundle (.npz) into a RenderScene.

Reference: Perf/BioVision/animation_bundle.py
"""

from __future__ import annotations

import json
from collections.abc import Callable
from collections import defaultdict
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

MESH_CONTAINER_FILENAME = "animation_meshes.npz"
METADATA_FILENAME = "animation_metadata.json"
QUANT_TABLE_FILENAME = "animation_quant.parquet"
ProgressCallback = Callable[[int, str], None]


def _emit_progress(
    progress_cb: ProgressCallback | None,
    value: int,
    label: str,
) -> None:
    if progress_cb is None:
        return
    progress_cb(max(0, min(100, int(value))), label)


def resolve_bundle_dir(path: Path) -> Path:
    """Resolve a path to a bundle directory.

    Accepts:
    - A bundle directory directly
    - The animation_meshes.npz file
    - The animation_metadata.json file
    """
    if path.is_dir():
        return path
    if path.name in (MESH_CONTAINER_FILENAME, METADATA_FILENAME):
        return path.parent
    raise ValueError(
        f"Cannot resolve bundle from {path}. "
        "Provide the bundle directory, .npz file, or metadata JSON."
    )


def load_metadata(bundle_dir: Path) -> dict:
    """Load animation_metadata.json from a bundle directory."""
    metadata_path = bundle_dir / METADATA_FILENAME
    if not metadata_path.exists():
        return {}
    with metadata_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_quant_table(bundle_dir: Path) -> dict[tuple[str, int], dict] | None:
    """Load animation_quant.parquet keyed by (cell_id, timepoint).

    Returns None if file is missing or pyarrow is unavailable.
    """
    quant_path = bundle_dir / QUANT_TABLE_FILENAME
    if not quant_path.exists():
        return None
    try:
        import pandas as pd
        df = pd.read_parquet(quant_path)
    except Exception:
        return None

    cell_ids = df["cell_id"].astype(str).tolist()
    timepoints = df["timepoint"].astype(int).tolist()
    records = df.to_dict("records")
    return {
        (cid, tp): rec
        for cid, tp, rec in zip(cell_ids, timepoints, records)
    }


def load_bundle(
    path: Path,
    progress_cb: ProgressCallback | None = None,
) -> tuple[RenderScene, dict, dict[tuple[str, int], dict] | None]:
    """Load a bundle and return (RenderScene, metadata, quant_table).

    The quant_table is keyed by (cell_id, timepoint) and may be None.
    """
    _emit_progress(progress_cb, 0, "Resolving animation bundle...")
    bundle_dir = resolve_bundle_dir(path)
    _emit_progress(progress_cb, 5, f"Loading bundle metadata: {bundle_dir.name}...")
    metadata = load_metadata(bundle_dir)

    npz_path = bundle_dir / MESH_CONTAINER_FILENAME
    if not npz_path.exists():
        raise FileNotFoundError(f"Mesh container not found: {npz_path}")

    frames_dict: dict[int, list[RenderCellMesh]] = defaultdict(list)

    _emit_progress(progress_cb, 10, f"Reading mesh container: {npz_path.name}...")
    with np.load(npz_path, allow_pickle=False) as payload:
        vertices_all = payload["vertices"]          # float16, Nx3
        faces_all = payload["faces"]                # uint32, Mx3
        vertex_offsets = payload["vertex_offsets"]
        face_offsets = payload["face_offsets"]
        mesh_cell_ids = payload["mesh_cell_ids"]
        mesh_timepoints = payload["mesh_timepoints"]
        mesh_colors = payload["mesh_colors"]        # uint8, Kx3

        # Bulk convert float16 -> float32
        vertices_f32 = vertices_all.astype(np.float32)

        mesh_count = len(mesh_timepoints)
        _emit_progress(progress_cb, 20, f"Building meshes (0/{mesh_count})...")
        last_mesh_progress = 20
        for mesh_idx in range(mesh_count):
            v_start = int(vertex_offsets[mesh_idx])
            v_end = int(vertex_offsets[mesh_idx + 1])
            f_start = int(face_offsets[mesh_idx])
            f_end = int(face_offsets[mesh_idx + 1])

            # Slice numpy arrays (zero-copy views where possible)
            mesh_verts = np.ascontiguousarray(vertices_f32[v_start:v_end])
            mesh_faces = np.ascontiguousarray(faces_all[f_start:f_end])

            # Color: uint8 0-255 -> float 0.0-1.0
            r, g, b = mesh_colors[mesh_idx]
            color = (float(r) / 255.0, float(g) / 255.0, float(b) / 255.0)

            timepoint = int(mesh_timepoints[mesh_idx])
            cell_id = str(mesh_cell_ids[mesh_idx])

            cell_mesh = RenderCellMesh(
                cell_id=cell_id,
                track_id=-1,
                geometry=MeshGeometry(
                    primitive=PrimitiveType.Triangles,
                    vertices=mesh_verts,
                    faces=mesh_faces,
                ),
                style=CellStyle(color=color, opacity=1.0),
                metadata={"timepoint": str(timepoint)},
            )
            frames_dict[timepoint].append(cell_mesh)

            mesh_progress = 20
            if mesh_count > 0:
                mesh_progress = 20 + int(((mesh_idx + 1) * 70) / mesh_count)
            if mesh_progress > last_mesh_progress:
                _emit_progress(
                    progress_cb,
                    mesh_progress,
                    f"Building meshes ({mesh_idx + 1}/{mesh_count})...",
                )
                last_mesh_progress = mesh_progress

    frames = [
        RenderFrame(timepoint=tp, cells=cells)
        for tp, cells in sorted(frames_dict.items())
    ]

    # If all cells share the same color (e.g. hardcoded red from cp_outlines),
    # override with deterministic per-cell colors.
    all_colors = {cell.style.color for frame in frames for cell in frame.cells}
    if len(all_colors) <= 1 and frames:
        from Arc.io.outline_editor import cell_color_from_id

        for frame in frames:
            for cell in frame.cells:
                cell.style = CellStyle(
                    color=cell_color_from_id(cell.cell_id),
                    opacity=cell.style.opacity,
                )

    scene = RenderScene(frames=frames)

    _emit_progress(progress_cb, 92, "Loading quant table...")
    quant = load_quant_table(bundle_dir)
    _emit_progress(progress_cb, 100, f"Loaded bundle: {bundle_dir.name}")
    return scene, metadata, quant
