#!/usr/bin/env python3
"""Convert BioVision mesh sources into ARC C++ cache JSON.

This handles both legacy mesh payloads with ``vertices`` / ``faces`` and the
new compact payloads with flattened geometry arrays. ANIMATION pickles and
animation bundles are pivoted into frame-centric layout. The output schema
matches what ARC C++ expects when loading cache JSON through the GUI.
"""

from __future__ import annotations

import gc
import json
import pickle
import sys
from pathlib import Path

from BioVision.animation_bundle import (
    METADATA_FILENAME,
    iter_animation_bundle_meshes,
    load_animation_metadata,
)


def _expand_geometry(
    mesh_obj: dict, vertex_dtype: str = "float32"
) -> tuple[list[list[float]], list[list[int]]]:
    """Return nested ``vertices`` and ``faces`` lists from any mesh schema.

    Supported schemas:
    - Legacy: ``vertices`` / ``faces`` as nested lists
    - Compact: ``vertices_flat`` / ``faces_flat`` as typed arrays + shape
    - Bytes: ``vertices`` / ``faces`` as raw bytes + shape (ANIMATION pkl)

    For ANIMATION v2 pickles, ``vertex_dtype`` should be ``"float16"``.
    """
    import struct
    import numpy as np

    # Typed-array compact format (MESH pkl).
    if "vertices_flat" in mesh_obj:
        vertices_flat = mesh_obj["vertices_flat"]
        faces_flat = mesh_obj["faces_flat"]
        vertices_shape = mesh_obj["vertices_shape"]
        faces_shape = mesh_obj["faces_shape"]

        vw = int(vertices_shape[1])
        fw = int(faces_shape[1])
        vertices = [
            [float(c) for c in vertices_flat[i : i + vw]]
            for i in range(0, len(vertices_flat), vw)
        ]
        faces = [
            [int(c) for c in faces_flat[i : i + fw]]
            for i in range(0, len(faces_flat), fw)
        ]
        return vertices, faces

    raw_verts = mesh_obj["vertices"]
    raw_faces = mesh_obj["faces"]

    # Raw bytes format (ANIMATION pkl).
    if isinstance(raw_verts, (bytes, bytearray)):
        vs = mesh_obj["vertices_shape"]
        fs = mesh_obj["faces_shape"]

        verts_np = np.frombuffer(raw_verts, dtype=vertex_dtype).reshape(vs)
        vertices = [[float(c) for c in row] for row in verts_np]

        n_idx = fs[0] * fs[1]
        fmt = "H" if len(raw_faces) == n_idx * 2 else "I"
        fflat = struct.unpack(f"<{n_idx}{fmt}", raw_faces)
        faces = [
            [int(c) for c in fflat[i : i + fs[1]]]
            for i in range(0, n_idx, fs[1])
        ]
        return vertices, faces

    # Legacy nested-list format.
    return (
        [[float(c) for c in v] for v in raw_verts],
        [[int(c) for c in f] for f in raw_faces],
    )


def convert_mesh_pickle(input_path: Path, output_path: Path) -> None:
    """Read a MESH pickle and stream ARC C++ cache JSON to disk.

    Full A1-sized mesh pickles expand into multi-gigabyte JSON. Writing the
    JSON incrementally avoids building that entire structure in memory on top
    of the already large unpickled mesh payload.
    """
    with input_path.open("rb") as handle:
        header = handle.readline().strip().decode("utf-8", errors="ignore")
        payload = pickle.load(handle)

    if header != "MESH":
        raise ValueError(f"Expected MESH pickle header, got {header!r}")
    if not isinstance(payload, dict):
        raise ValueError("MESH pickle payload must be a dict of timepoints.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("{")
        handle.write('"source_file":')
        json.dump(str(input_path), handle)
        handle.write(',"header":"MESH","payload":{')

        first_timepoint = True
        timepoint_keys = sorted(payload.keys(), key=int)
        for timepoint in timepoint_keys:
            mesh_list = payload.pop(timepoint)
            if not isinstance(mesh_list, list):
                continue

            if not first_timepoint:
                handle.write(",")
            first_timepoint = False

            json.dump(str(int(timepoint)), handle)
            handle.write(":[")

            first_mesh = True
            mesh_count = 0
            for mesh_obj in mesh_list:
                if not isinstance(mesh_obj, dict):
                    continue

                vertices, faces = _expand_geometry(mesh_obj)
                converted_mesh = {
                    "name": str(mesh_obj.get("name", f"t{timepoint}_cell")),
                    "color": [
                        int(channel)
                        for channel in mesh_obj.get("color", (255, 255, 255))
                    ],
                    "vertices": vertices,
                    "faces": faces,
                }

                if not first_mesh:
                    handle.write(",")
                first_mesh = False
                json.dump(converted_mesh, handle, separators=(",", ":"))
                mesh_count += 1

            handle.write("]")
            del mesh_list
            gc.collect()
            print(f"Wrote timepoint {timepoint} with {mesh_count} meshes")

        handle.write("}}")


def _simplify_mesh(
    vertices: list[list[float]], faces: list[list[int]], target_faces: int
) -> tuple[list[list[float]], list[list[int]]]:
    """Decimate a mesh to approximately ``target_faces`` triangles.

    Uses trimesh + fast_simplification for quadric decimation. Falls back to
    the original mesh if the library is unavailable or the mesh is already
    small enough.
    """
    if len(faces) <= target_faces:
        return vertices, faces
    try:
        import numpy as np
        import trimesh

        m = trimesh.Trimesh(
            vertices=np.asarray(vertices, dtype="float64"),
            faces=np.asarray(faces, dtype="int32"),
            process=False,
        )
        s = m.simplify_quadric_decimation(face_count=target_faces)
        return (
            [[float(c) for c in v] for v in s.vertices],
            [[int(c) for c in f] for f in s.faces],
        )
    except Exception:
        return vertices, faces


def _write_animation_frames_json(
    *,
    source_path: Path,
    output_path: Path,
    frames: dict[int, list[dict]],
    vertex_dtype: str,
    target_faces: int,
) -> None:
    """Write frame-centric ARC cache JSON from an animation mesh mapping."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("{")
        handle.write('"source_file":')
        json.dump(str(source_path), handle)
        handle.write(',"header":"ANIMATION","payload":{')

        first_timepoint = True
        for timepoint in sorted(frames.keys()):
            mesh_list = frames.pop(timepoint)

            if not first_timepoint:
                handle.write(",")
            first_timepoint = False

            json.dump(str(timepoint), handle)
            handle.write(":[")

            first_mesh = True
            mesh_count = 0
            for mesh_obj in mesh_list:
                vertices, faces = _expand_geometry(mesh_obj, vertex_dtype=vertex_dtype)
                vertices, faces = _simplify_mesh(vertices, faces, target_faces)
                converted_mesh = {
                    "name": str(mesh_obj.get("name", f"t{timepoint}_cell")),
                    "color": [int(c) for c in mesh_obj.get("color", (255, 255, 255))],
                    "vertices": vertices,
                    "faces": faces,
                }

                if not first_mesh:
                    handle.write(",")
                first_mesh = False
                json.dump(converted_mesh, handle, separators=(",", ":"))
                mesh_count += 1

            handle.write("]")
            gc.collect()
            print(f"Wrote timepoint {timepoint} with {mesh_count} meshes")

        handle.write("}}")


def convert_animation_pickle(
    input_path: Path, output_path: Path, *, target_faces: int = 2000
) -> None:
    """Read an ANIMATION pickle and write frame-centric ARC C++ cache JSON.

    The ANIMATION format is cell-centric and zlib-compressed. This pivots it
    into per-timepoint mesh lists matching the same JSON schema that
    ``convert_mesh_pickle`` produces, so ARC can consume either format
    transparently.

    Each cell mesh is decimated to approximately ``target_faces`` triangles
    so the resulting JSON stays small enough for Qt's in-memory JSON parser.
    """
    import zlib

    with input_path.open("rb") as handle:
        header = handle.readline().strip().decode("utf-8", errors="ignore")
        raw = handle.read()

    if header != "ANIMATION":
        raise ValueError(f"Expected ANIMATION pickle header, got {header!r}")

    payload = pickle.loads(zlib.decompress(raw))
    del raw

    cells = payload["cells"]
    vertex_dtype = payload.get("vertex_dtype", "float32")

    # Pivot cell-centric data into per-timepoint mesh lists.
    frames: dict[int, list[dict]] = {}
    for cell_id, cell in cells.items():
        color = cell["color"]
        for tp, tp_data in cell["timepoints"].items():
            tp_int = int(tp)
            if tp_int not in frames:
                frames[tp_int] = []
            frames[tp_int].append({
                "name": f"cell_{cell_id}_t{tp}",
                "color": color,
                "vertices": tp_data["vertices"],
                "vertices_shape": tp_data["vertices_shape"],
                "faces": tp_data["faces"],
                "faces_shape": tp_data["faces_shape"],
            })
    del payload, cells

    _write_animation_frames_json(
        source_path=input_path,
        output_path=output_path,
        frames=frames,
        vertex_dtype=vertex_dtype,
        target_faces=target_faces,
    )


def convert_animation_bundle(
    input_path: Path, output_path: Path, *, target_faces: int = 2000
) -> None:
    """Read an animation bundle and write frame-centric ARC cache JSON."""
    metadata = load_animation_metadata(input_path)
    mesh_summary = metadata.get("mesh_container", {})
    vertex_dtype = str(mesh_summary.get("vertex_dtype", "float16"))

    frames: dict[int, list[dict]] = {}
    for timepoint, mesh_obj in iter_animation_bundle_meshes(input_path):
        if timepoint not in frames:
            frames[timepoint] = []
        frames[timepoint].append(mesh_obj)

    _write_animation_frames_json(
        source_path=input_path,
        output_path=output_path,
        frames=frames,
        vertex_dtype=vertex_dtype,
        target_faces=target_faces,
    )


def main(argv: list[str]) -> int:
    """CLI entrypoint."""
    if len(argv) != 3:
        print(
            "Usage: convert_mesh_pkl_to_arc_json.py "
            "<input.pkl|animation_bundle_dir|animation_metadata.json> <output.json>"
        )
        return 1

    input_path = Path(argv[1])
    output_path = Path(argv[2])

    if not input_path.exists():
        print(f"Input not found: {input_path}")
        return 1

    if input_path.is_dir() or input_path.name == METADATA_FILENAME:
        convert_animation_bundle(input_path, output_path)
        print(f"Converted {input_path} -> {output_path}")
        return 0

    # Peek at header to dispatch.
    with input_path.open("rb") as handle:
        header = handle.readline().strip().decode("utf-8", errors="ignore")

    if header == "ANIMATION":
        convert_animation_pickle(input_path, output_path)
    elif header == "MESH":
        convert_mesh_pickle(input_path, output_path)
    else:
        print(f"Unsupported pickle header: {header!r}")
        return 1

    print(f"Converted {input_path} -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
