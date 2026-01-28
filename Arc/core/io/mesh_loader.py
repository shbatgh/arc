from __future__ import annotations
import pickle

import concurrent.futures
from pathlib import Path
import re
from typing import Dict, List, Tuple, Optional
import random

import matplotlib.cm
from vedo import Mesh, load

from Arc.core.cell import Cell
from Arc.core.project import Project
from Arc.core.scene import Scene

from BioVision.processing import single_stack_cell_matching
from BioVision.processing import solid_mesh_from_3D_outlines
from BioVision.processing.mesh_creation import cell_point_filler

SUPPORTED_EXTENSIONS = {'.obj', '.stl', '.ply'}
DEFAULT_COLOR = (255, 0, 0)
Z_SPACING = (3 / 0.198) * 0.5
MIN_OUTLINE_POINTS = 16
POINTS_PER_SEGMENT = 6
TENSION = -0.75
CONTINUITY = 0
BIAS = 0
CMAP = matplotlib.cm.get_cmap("tab20")


def load_meshes_from_folder(folder: str | Path) -> Dict[str, Mesh]:
    folder_path = Path(folder)
    meshes: Dict[str, Mesh] = {}
    if not folder_path.exists() or not folder_path.is_dir():
        return meshes

    for path in sorted(folder_path.iterdir()):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            mesh = load(str(path))
        except Exception as exc:  # pragma: no cover - IO/format errors
            print(f"Failed to load mesh {path.name}: {exc}")
            continue

        if isinstance(mesh, list):
            candidates = [m for m in mesh if isinstance(m, Mesh)]
            if not candidates:
                continue
            mesh = candidates[0]

        cell_id = path.stem
        mesh.name = cell_id
        mesh.cell_id = cell_id
        try:
            mesh.pickable(True)
        except Exception:
            pass

        meshes[cell_id] = mesh

    return meshes


def load_dataset_from_root(root_folder: str | Path, mode: str = "mesh") -> Tuple[Project, List[int]]:
    """
    Load dataset from root folder.

    Modes:
        - "raw": XY wireframes only (horizontal contours at each Z-slice)
        - "mesh": Full wireframe with XY + splined XZ/YZ curves (like Blender WIREFRAME)
        - "solid": Convex hull mesh (like Blender MESH)
    """
    root_path = Path(root_folder)
    project = Project(name=root_path.name)
    timepoints: List[int] = []

    # Try loading from cache first
    cache_file = root_path.parent / f"{root_path.name}_{mode}.pkl"
    if cache_file.exists():
        print(f"Loading from cache: {cache_file}")
        try:
            if mode == "solid":
                project, timepoints = _load_solid_cache(cache_file, project)
            else:
                # Both "raw" and "mesh" are wireframe/curves
                project, timepoints = _load_wireframe_cache(cache_file, project)
            return project, timepoints
        except Exception as e:
            print(f"Failed to load cache: {e}")
            # Fallback to normal loading

    has_cells = False
    if not root_path.exists() or not root_path.is_dir():
        return project, timepoints

    timepoint_dirs = [d for d in root_path.iterdir() if d.is_dir()]

    # Identify valid timepoints
    valid_dirs = []
    for tp_dir in sorted(timepoint_dirs, key=_timepoint_sort_key):
        tp_num = _parse_timepoint_number(tp_dir.name)
        if tp_num is not None:
            valid_dirs.append((tp_dir, tp_num))

    if not valid_dirs:
        return project, []

    # Process timepoints in parallel
    # BioVision relies on global state, so we use ProcessPoolExecutor for isolation.
    with concurrent.futures.ProcessPoolExecutor() as executor:
        future_to_tp = {
            executor.submit(_process_timepoint_task, tp_dir, tp_num, mode): tp_num
            for tp_dir, tp_num in valid_dirs
        }

        for future in concurrent.futures.as_completed(future_to_tp):
            tp_num = future_to_tp[future]
            try:
                cell_data_list = future.result()
                if mode == "solid":
                    scene = _create_scene_from_solid_data(tp_num, cell_data_list)
                elif mode == "mesh":
                    # Full wireframe with tubes (like Blender WIREFRAME with bevel)
                    scene = _create_scene_from_wireframe_data(tp_num, cell_data_list, use_tubes=True)
                else:
                    # Raw mode: thin lines only
                    scene = _create_scene_from_wireframe_data(tp_num, cell_data_list, use_tubes=False)
                project.scenes[tp_num] = scene
                timepoints.append(tp_num)
                if scene.cells:
                    has_cells = True
                print(f"Timepoint {tp_num} done rendering")
            except Exception as exc:
                print(f"Timepoint {tp_num} generated an exception: {exc}")

    timepoints.sort()

    if has_cells:
        try:
            if mode == "solid":
                _save_solid_cache(project, cache_file)
            else:
                # Both "raw" and "mesh" are wireframe/curves
                _save_wireframe_cache(project, cache_file, mode)
        except Exception as e:
             print(f"Failed to save cache: {e}")

    if not has_cells:
        return project, []
    return project, timepoints


def _save_wireframe_cache(project: Project, cache_file: Path, mode: str) -> None:
    """Save wireframe cache for both 'raw' and 'mesh' modes."""
    frames_dict = {}
    for tp, scene in project.scenes.items():
        frames_dict[tp] = []
        slice_dict = {}

        for cell in scene.cells.values():
            idx = cell.metadata.get("id", 0)
            color_idx = (idx * 17) % 20
            rgba = CMAP(color_idx)
            color_tuple = (int(rgba[0]*255), int(rgba[1]*255), int(rgba[2]*255))

            curves = cell.metadata.get("curves", [])
            if not curves:
                continue

            if color_tuple not in slice_dict:
                slice_dict[color_tuple] = []

            slice_dict[color_tuple].extend(curves)

        frames_dict[tp].append(slice_dict)

    header = b"WIREFRAME\n" if mode == "mesh" else b"RAW\n"
    with open(cache_file, 'wb') as f:
        f.write(header)
        pickle.dump(frames_dict, f)
    print(f"Saved {mode} cache to {cache_file}")


def _load_wireframe_cache(cache_file: Path, project: Project) -> Tuple[Project, List[int]]:
    """Load wireframe cache for both 'raw' and 'mesh' modes."""
    from vedo import Tube, Lines

    with open(cache_file, 'rb') as f:
        header = f.readline().strip()
        frames_dict = pickle.load(f)

    # Determine if this is full wireframe (mesh) or raw XY only
    is_mesh_mode = (header == b"WIREFRAME")

    timepoints = sorted(frames_dict.keys())
    for tp in timepoints:
        scene = Scene(timepoint=tp)
        cell_idx = 0
        for slice_dict in frames_dict[tp]:
            for color, groups in slice_dict.items():
                lines = [curve for curve in groups if len(curve) > 1]

                if not lines:
                    continue

                # For mesh mode, render as tubes; for raw, render as thin lines
                if is_mesh_mode:
                    mesh = _create_tube_from_curves(lines, color)
                else:
                    mesh = Lines(lines, c=[c/255 for c in color])

                cell_id = f"t{tp}_cell_{cell_idx:03d}"
                mesh.name = cell_id
                mesh.cell_id = cell_id

                metadata = {"id": cell_idx, "curves": groups}

                scene.add_cell(Cell(cell_id=cell_id, mesh=mesh, metadata=metadata))
                cell_idx += 1

        project.scenes[tp] = scene

    return project, timepoints


def _save_solid_cache(project: Project, cache_file: Path) -> None:
    """Save solid mesh cache (convex hull meshes)."""
    mesh_frames_dict = {}
    for tp, scene in project.scenes.items():
        mesh_frames_dict[tp] = []
        for cell in scene.cells.values():
            idx = cell.metadata.get("id", 0)
            color_idx = (idx * 17) % 20
            rgba = CMAP(color_idx)
            color_tuple = (int(rgba[0]*255), int(rgba[1]*255), int(rgba[2]*255))

            mesh_obj = {
                'vertices': cell.mesh.points.tolist(),
                'faces': cell.mesh.cells,
                'color': color_tuple,
                'name': cell.cell_id,
                'metadata': cell.metadata
            }
            mesh_frames_dict[tp].append(mesh_obj)

    with open(cache_file, 'wb') as f:
        f.write(b"MESH\n")
        pickle.dump(mesh_frames_dict, f)
    print(f"Saved solid cache to {cache_file}")


def _load_solid_cache(cache_file: Path, project: Project) -> Tuple[Project, List[int]]:
    """Load solid mesh cache (convex hull meshes)."""
    with open(cache_file, 'rb') as f:
        header = f.readline()
        mesh_frames_dict = pickle.load(f)

    timepoints = sorted(mesh_frames_dict.keys())
    for tp in timepoints:
        scene = Scene(timepoint=tp)
        for mesh_obj in mesh_frames_dict[tp]:
            vertices = mesh_obj['vertices']
            faces = mesh_obj['faces']
            cell_id = mesh_obj.get('name', f"t{tp}_unknown")
            metadata = mesh_obj.get('metadata', {})

            mesh = Mesh([vertices, faces])
            mesh.name = cell_id
            mesh.cell_id = cell_id

            # Color
            color = mesh_obj.get('color', DEFAULT_COLOR)
            if isinstance(color, (list, tuple)) and len(color) >= 3:
                if any(c > 1 for c in color):
                    c_float = (color[0]/255, color[1]/255, color[2]/255)
                else:
                    c_float = color[:3]
                mesh.c(c_float)

            try:
                mesh.pickable(True)
            except Exception:
                pass

            scene.add_cell(Cell(cell_id=cell_id, mesh=mesh, metadata=metadata))
        project.scenes[tp] = scene

    return project, timepoints


def _process_timepoint_task(timepoint_dir: Path, timepoint: int, mode: str = "mesh") -> List[dict]:
    """
    Task to be executed in a separate process.
    Loads outlines, computes cell matches, and generates mesh geometry data.

    Modes:
        - "raw": XY wireframes only (curves)
        - "mesh": Full wireframe XY + splined XZ/YZ (curves)
        - "solid": Convex hull mesh (vertices + faces)
    """
    stack_list = _load_stack_from_timepoint(timepoint_dir)
    if not stack_list:
        return []

    # Reset globals in the worker process to avoid contamination
    single_stack_cell_matching.cell_count = 0
    single_stack_cell_matching.cells = []

    cells = single_stack_cell_matching.compute_stack(stack_list=stack_list, color=DEFAULT_COLOR)

    results = []
    for idx, cell in enumerate(cells):
        mesh_data = _compute_mesh_data_from_cell(cell, mode=mode)
        if mesh_data is None:
            continue

        cell_id = f"t{timepoint}_cell_{idx:03d}"

        if mode == "solid":
            # mesh_data is (vertices, faces)
            results.append({
                "cell_id": cell_id,
                "vertices": mesh_data[0],
                "faces": mesh_data[1],
                "metadata": {"id": idx, "timepoint": timepoint}
            })
        else:
            # Both "raw" and "mesh" return curves (list of polylines)
            results.append({
                "cell_id": cell_id,
                "curves": mesh_data,
                "metadata": {"id": idx, "timepoint": timepoint}
            })
    return results


def _compute_mesh_data_from_cell(cell, mode: str = "mesh") -> Tuple[List, List] | List[List[List[float]]] | None:
    """
    Generates geometry data for a given cell object.

    Modes:
        - "raw": XY wireframes only (horizontal contours at each Z-slice) -> returns curves
        - "mesh": Full wireframe with XY + splined XZ/YZ curves -> returns curves
        - "solid": Convex hull mesh from all outlines -> returns (vertices, faces)
    """
    # Build XY outlines (horizontal contours at each Z-slice)
    xy_outlines: List[List[List[float]]] = []
    for idx, outline_2d in enumerate(cell.outlines):
        z_val = (cell.starting_slice + idx) * Z_SPACING
        xy_outlines.append([[coord[0], coord[1], z_val] for coord in outline_2d])

    # For "raw" mode, return only the XY wireframes (horizontal contours)
    if mode == "raw":
        xy_outlines = [outline for outline in xy_outlines if len(outline) > MIN_OUTLINE_POINTS]
        if not xy_outlines:
            return None
        return xy_outlines

    # For "mesh" and "solid" modes, generate splined XZ/YZ wireframes
    outlines_3d = list(xy_outlines)
    try:
        splined_xz, splined_yz = cell_point_filler.point_filler(
            cell=cell,
            tens=TENSION,
            cont=CONTINUITY,
            bias=BIAS,
            points_per_segment=POINTS_PER_SEGMENT,
        )
        outlines_3d.extend(splined_xz + splined_yz)
    except Exception as exc:
        print(f"Wireframe fill failed for cell {getattr(cell, 'id', 'unknown')}: {exc}")

    outlines_3d = [outline for outline in outlines_3d if len(outline) > MIN_OUTLINE_POINTS]
    if not outlines_3d:
        return None

    # For "mesh" mode, return the full wireframe curves
    if mode == "mesh":
        return outlines_3d

    # For "solid" mode, build convex hull mesh
    num_points = min(len(outline) for outline in outlines_3d)
    try:
        tri_mesh = solid_mesh_from_3D_outlines.build_mesh(
            outlines_3D=outlines_3d,
            num_points=num_points,
            visualize_true=False,
        )
    except Exception as exc:
        print(f"Failed to build mesh for cell {getattr(cell, 'id', 'unknown')}: {exc}")
        return None
    if tri_mesh is None:
        return None

    return tri_mesh.vertices, tri_mesh.faces

def _create_tube_from_curves(curves: List[List[List[float]]], color: Tuple[int, int, int]) -> "Mesh":
    """
    Create a tube-like mesh from curves (like Blender's bevel on NURBS curves).
    Uses vedo's Tube to create 3D tubes from polylines.
    """
    from vedo import Tube, merge

    tubes = []
    c_float = (color[0]/255, color[1]/255, color[2]/255)

    for curve in curves:
        if len(curve) < 2:
            continue
        try:
            # Create tube with small radius (like Blender's bevel_depth)
            tube = Tube(curve, r=0.4, n=8, c=c_float)
            tubes.append(tube)
        except Exception:
            continue

    if not tubes:
        return None

    # Merge all tubes into a single mesh
    if len(tubes) == 1:
        return tubes[0]
    return merge(tubes)


def _create_scene_from_wireframe_data(timepoint: int, cell_data_list: List[dict], use_tubes: bool = True) -> Scene:
    """
    Reconstructs a Scene object from wireframe data (both 'raw' and 'mesh' modes).

    For 'mesh' mode (use_tubes=True): renders as tubes (like Blender WIREFRAME with bevel)
    For 'raw' mode (use_tubes=False): renders as thin lines
    """
    from vedo import Lines

    scene = Scene(timepoint=timepoint)
    for data in cell_data_list:
        curves = data["curves"]
        lines = [c for c in curves if len(c) > 1]

        if not lines:
            continue

        idx = data["metadata"].get("id", 0)
        color_idx = (idx * 17) % 20
        rgba = CMAP(color_idx)
        color = (int(rgba[0]*255), int(rgba[1]*255), int(rgba[2]*255))

        if use_tubes:
            mesh = _create_tube_from_curves(lines, color)
            if mesh is None:
                # Fallback to lines if tube creation fails
                mesh = Lines(lines, c=[c/255 for c in color])
        else:
            mesh = Lines(lines, c=[c/255 for c in color])

        mesh.name = data["cell_id"]
        mesh.cell_id = data["cell_id"]

        data["metadata"]["curves"] = curves

        try:
            mesh.pickable(True)
        except Exception:
            pass
        scene.add_cell(Cell(cell_id=data["cell_id"], mesh=mesh, metadata=data["metadata"]))
    return scene


def _create_scene_from_solid_data(timepoint: int, cell_data_list: List[dict]) -> Scene:
    """
    Reconstructs a Scene object from solid mesh data (convex hull meshes).
    """
    scene = Scene(timepoint=timepoint)
    for data in cell_data_list:
        mesh = Mesh([data["vertices"], data["faces"]])
        mesh.name = data["cell_id"]
        mesh.cell_id = data["cell_id"]

        # Color assignment
        idx = data["metadata"].get("id", 0)
        color_idx = (idx * 17) % 20
        rgba = CMAP(color_idx)
        mesh.c(rgba[:3])

        try:
            mesh.pickable(True)
        except Exception:
            pass
        scene.add_cell(Cell(cell_id=data["cell_id"], mesh=mesh, metadata=data["metadata"]))
    return scene


def _load_stack_from_timepoint(timepoint_dir: Path) -> List[dict]:
    outline_files = _collect_outline_files(timepoint_dir)
    if not outline_files:
        return []

    stack_list: List[dict] = []
    for outline_path in outline_files:
        outlines = _parse_outline_file(outline_path)
        if outlines:
            stack_list.append({DEFAULT_COLOR: outlines})
        else:
            stack_list.append({})
    return stack_list


def _collect_outline_files(timepoint_dir: Path) -> List[Path]:
    outlines = []
    for file_path in timepoint_dir.iterdir():
        if not file_path.is_file():
            continue
        if file_path.name.endswith("_cp_outlines.txt") or file_path.name.endswith("_outlines.txt"):
            outlines.append(file_path)
    return sorted(outlines, key=_slice_sort_key)


def _parse_outline_file(path: Path) -> List[List[List[int]]]:
    outlines: List[List[List[int]]] = []
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return outlines

    if not text:
        return outlines

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        values = [v for v in line.split(",") if v.strip() != ""]
        coords: List[List[int]] = []
        for i in range(0, len(values) - 1, 2):
            try:
                x = int(float(values[i]))
                y = int(float(values[i + 1]))
            except ValueError:
                continue
            coords.append([x, y])
        if len(coords) >= 3:
            coords.extend([coords[0], coords[1], coords[2]])
        if coords:
            outlines.append(coords)
    return outlines


def _parse_timepoint_number(name: str) -> int | None:
    match = re.search(r"(\d+)", name)
    if not match:
        return None
    return int(match.group(1))


def _timepoint_sort_key(path: Path) -> Tuple[int, str]:
    num = _parse_timepoint_number(path.name)
    if num is None:
        return (10**9, path.name)
    return (num, path.name)


def _slice_sort_key(path: Path) -> Tuple[int, str]:
    num = _parse_timepoint_number(path.stem)
    if num is None:
        return (10**9, path.name)
    return (num, path.name)