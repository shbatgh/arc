"""Helpers for BioVision animation bundle export and loading.

The bundle format separates concerns:
  - ``animation_meshes.npz`` stores compact binary mesh arrays
  - ``animation_metadata.json`` stores lightweight dataset metadata
  - ``animation_quant.parquet`` stores tabular quantification data
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator

import numpy as np


BUNDLE_FORMAT = "BioVisionAnimationBundle"
BUNDLE_VERSION = 1
MESH_CONTAINER_FILENAME = "animation_meshes.npz"
METADATA_FILENAME = "animation_metadata.json"
QUANT_TABLE_FILENAME = "animation_quant.parquet"


def bundle_paths(bundle_dir: Path) -> dict[str, Path]:
    """Return the standard file layout for an animation bundle directory."""
    return {
        "bundle_dir": bundle_dir,
        "mesh_container": bundle_dir / MESH_CONTAINER_FILENAME,
        "metadata": bundle_dir / METADATA_FILENAME,
        "quant_table": bundle_dir / QUANT_TABLE_FILENAME,
    }


def resolve_bundle_dir(path: Path) -> Path:
    """Resolve either a bundle directory or metadata JSON file to a bundle dir."""
    if path.is_dir():
        return path
    if path.name == METADATA_FILENAME:
        return path.parent
    raise ValueError(
        "Animation bundle path must be a bundle directory or animation_metadata.json."
    )


class AnimationMeshAccumulator:
    """Growable NumPy-backed accumulator for bundle mesh payloads."""

    def __init__(
        self,
        *,
        vertex_dtype: str = "float16",
        initial_mesh_capacity: int = 256,
        initial_vertex_capacity: int = 16384,
        initial_face_capacity: int = 16384,
    ) -> None:
        self.vertex_dtype = np.dtype(vertex_dtype)
        self.face_dtype = np.dtype("uint32")
        self._vertices = np.empty((initial_vertex_capacity, 3), dtype=self.vertex_dtype)
        self._faces = np.empty((initial_face_capacity, 3), dtype=self.face_dtype)
        self._vertex_offsets = np.zeros(initial_mesh_capacity + 1, dtype=np.int64)
        self._face_offsets = np.zeros(initial_mesh_capacity + 1, dtype=np.int64)
        self._mesh_timepoints = np.empty((initial_mesh_capacity,), dtype=np.int32)
        self._mesh_colors = np.empty((initial_mesh_capacity, 3), dtype=np.uint8)
        self._mesh_cell_ids: list[str] = []
        self.mesh_count = 0
        self.vertex_count = 0
        self.face_count = 0

    def _grow_vertices(self, min_size: int) -> None:
        if min_size <= self._vertices.shape[0]:
            return
        new_size = max(self._vertices.shape[0] * 2, min_size, 1)
        new_vertices = np.empty((new_size, 3), dtype=self.vertex_dtype)
        if self.vertex_count:
            new_vertices[: self.vertex_count] = self._vertices[: self.vertex_count]
        self._vertices = new_vertices

    def _grow_faces(self, min_size: int) -> None:
        if min_size <= self._faces.shape[0]:
            return
        new_size = max(self._faces.shape[0] * 2, min_size, 1)
        new_faces = np.empty((new_size, 3), dtype=self.face_dtype)
        if self.face_count:
            new_faces[: self.face_count] = self._faces[: self.face_count]
        self._faces = new_faces

    def _grow_meshes(self, min_size: int) -> None:
        if min_size <= self._mesh_timepoints.shape[0]:
            return
        new_size = max(self._mesh_timepoints.shape[0] * 2, min_size, 1)
        new_vertex_offsets = np.zeros(new_size + 1, dtype=np.int64)
        new_face_offsets = np.zeros(new_size + 1, dtype=np.int64)
        new_mesh_timepoints = np.empty((new_size,), dtype=np.int32)
        new_mesh_colors = np.empty((new_size, 3), dtype=np.uint8)
        if self.mesh_count:
            new_vertex_offsets[: self.mesh_count + 1] = self._vertex_offsets[
                : self.mesh_count + 1
            ]
            new_face_offsets[: self.mesh_count + 1] = self._face_offsets[
                : self.mesh_count + 1
            ]
            new_mesh_timepoints[: self.mesh_count] = self._mesh_timepoints[
                : self.mesh_count
            ]
            new_mesh_colors[: self.mesh_count] = self._mesh_colors[: self.mesh_count]
        self._vertex_offsets = new_vertex_offsets
        self._face_offsets = new_face_offsets
        self._mesh_timepoints = new_mesh_timepoints
        self._mesh_colors = new_mesh_colors

    def append_mesh(
        self,
        *,
        vertices,
        faces,
        cell_id: str,
        timepoint: int,
        color: tuple[int, int, int],
    ) -> None:
        """Append one mesh to the accumulator."""
        vertices_np = np.asarray(vertices, dtype=self.vertex_dtype)
        faces_np = np.asarray(faces, dtype=self.face_dtype)
        vertex_total = self.vertex_count + int(vertices_np.shape[0])
        face_total = self.face_count + int(faces_np.shape[0])
        mesh_total = self.mesh_count + 1

        self._grow_vertices(vertex_total)
        self._grow_faces(face_total)
        self._grow_meshes(mesh_total)

        self._vertices[self.vertex_count : vertex_total] = vertices_np
        self._faces[self.face_count : face_total] = faces_np
        self._mesh_timepoints[self.mesh_count] = int(timepoint)
        self._mesh_colors[self.mesh_count] = np.asarray(color, dtype=np.uint8)
        self._mesh_cell_ids.append(cell_id)

        self.vertex_count = vertex_total
        self.face_count = face_total
        self.mesh_count = mesh_total
        self._vertex_offsets[self.mesh_count] = self.vertex_count
        self._face_offsets[self.mesh_count] = self.face_count

    def build_payload(self) -> dict[str, object]:
        """Return trimmed arrays ready for serialization."""
        return {
            "vertices": self._vertices[: self.vertex_count].copy(),
            "faces": self._faces[: self.face_count].copy(),
            "vertex_offsets": self._vertex_offsets[: self.mesh_count + 1].copy(),
            "face_offsets": self._face_offsets[: self.mesh_count + 1].copy(),
            "mesh_timepoints": self._mesh_timepoints[: self.mesh_count].copy(),
            "mesh_colors": self._mesh_colors[: self.mesh_count].copy(),
            "mesh_cell_ids": np.asarray(self._mesh_cell_ids, dtype=np.str_),
        }


def write_animation_mesh_container(
    mesh_path: Path,
    *,
    accumulator: AnimationMeshAccumulator,
) -> dict[str, object]:
    """Write the bundle's binary mesh container and return a summary."""
    mesh_path.parent.mkdir(parents=True, exist_ok=True)
    payload = accumulator.build_payload()

    np.savez_compressed(
        mesh_path,
        vertices=payload["vertices"],
        faces=payload["faces"],
        vertex_offsets=payload["vertex_offsets"],
        face_offsets=payload["face_offsets"],
        mesh_cell_ids=payload["mesh_cell_ids"],
        mesh_timepoints=payload["mesh_timepoints"],
        mesh_colors=payload["mesh_colors"],
    )

    return {
        "mesh_count": int(accumulator.mesh_count),
        "vertex_count": int(accumulator.vertex_count),
        "face_count": int(accumulator.face_count),
        "vertex_dtype": str(accumulator.vertex_dtype),
        "face_dtype": str(accumulator.face_dtype),
    }


def write_animation_metadata(
    metadata_path: Path,
    *,
    dataset_name: str,
    num_timepoints: int,
    z_spacing: float,
    mesh_summary: dict[str, object],
    quant_row_count: int,
    quant_table_written: bool,
    legacy_outputs: dict[str, str | None],
) -> dict[str, object]:
    """Write the bundle metadata JSON manifest."""
    metadata = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "dataset_name": dataset_name,
        "num_timepoints": int(num_timepoints),
        "z_spacing": float(z_spacing),
        "mesh_container": {
            "filename": MESH_CONTAINER_FILENAME,
            "mesh_count": int(mesh_summary["mesh_count"]),
            "vertex_count": int(mesh_summary["vertex_count"]),
            "face_count": int(mesh_summary["face_count"]),
            "vertex_dtype": str(mesh_summary["vertex_dtype"]),
            "face_dtype": str(mesh_summary["face_dtype"]),
        },
        "tables": {
            "quant": {
                "filename": QUANT_TABLE_FILENAME,
                "format": "parquet",
                "row_count": int(quant_row_count),
                "written": bool(quant_table_written),
            }
        },
        "legacy_outputs": legacy_outputs,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with metadata_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)
        handle.write("\n")
    return metadata


def load_animation_metadata(path: Path) -> dict[str, object]:
    """Load animation bundle metadata from a bundle dir or metadata JSON file."""
    bundle_dir = resolve_bundle_dir(path)
    metadata_path = bundle_paths(bundle_dir)["metadata"]
    with metadata_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def iter_animation_bundle_meshes(
    path: Path,
) -> Iterator[tuple[int, dict[str, object]]]:
    """Yield frame-centric mesh payloads from an animation bundle."""
    import numpy as np

    bundle_dir = resolve_bundle_dir(path)
    paths = bundle_paths(bundle_dir)

    with np.load(paths["mesh_container"], allow_pickle=False) as payload:
        vertices = payload["vertices"]
        faces = payload["faces"]
        vertex_offsets = payload["vertex_offsets"]
        face_offsets = payload["face_offsets"]
        mesh_cell_ids = payload["mesh_cell_ids"]
        mesh_timepoints = payload["mesh_timepoints"]
        mesh_colors = payload["mesh_colors"]

        order = np.argsort(mesh_timepoints, kind="stable")
        for mesh_idx in order:
            v_start = int(vertex_offsets[mesh_idx])
            v_end = int(vertex_offsets[mesh_idx + 1])
            f_start = int(face_offsets[mesh_idx])
            f_end = int(face_offsets[mesh_idx + 1])
            timepoint = int(mesh_timepoints[mesh_idx])
            cell_id = str(mesh_cell_ids[mesh_idx])
            color = tuple(int(channel) for channel in mesh_colors[mesh_idx].tolist())
            yield timepoint, {
                "name": f"cell_{cell_id}_t{timepoint}",
                "color": color,
                "vertices": vertices[v_start:v_end],
                "faces": faces[f_start:f_end],
            }
