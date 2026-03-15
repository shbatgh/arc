"""
Quantitative Data Extraction (Entry Point)

Takes a WIREFRAME .pkl file, matches cells across timepoints, generates
3D solid meshes, and exports quantitative metrics.

Outputs:
  - CSV with per-cell, per-timepoint position, displacement, distance,
    volume, and surface area.
  - MESH .pkl with solid mesh vertices/faces for Blender rendering.
  - TRACER .pkl with cell center trajectories for Blender rendering.

See README.md for the full pipeline overview.
"""

import pandas as pd
import copy
import multiprocessing
import pickle
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    # Allow `python BioVision/processing/pickled_quant_data.py` from the repo root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from BioVision.processing.mesh_creation import cell_point_filler, contour_stitching_mesh

# ============================================================================
#  USER CONFIGURATION - Change these before running
# ============================================================================

# Decimal places for rounding in CSV output. Set to False for no rounding.
ROUND_DECIMAL_PLACE = 1

# Kochanek-Bartels spline parameters for mesh cap generation.
# Tension: negative values produce rounder dome caps.
TENS = -0.85
CONT = 0
BIAS = 0

# Number of interpolated points per spline segment in wireframe densification.
POINTS_PER_SEGMENT = 8

# Path to the WIREFRAME .pkl file.
PATH_TO_WIREFRAME = r"C:/Users/tajre/OneDrive/Desktop/Amy's Animations/For Talk UPDATED ForTara.pkl"

# Colors list for cell matching, e.g. [(255,0,0), (0,0,255)].
COLORS = [(0, 100, 0), (200, 200, 0), (255, 0, 0), (0, 0, 255), (200, 0, 100), (255, 0, 255), (0, 255, 255), (150, 50, 50), (255, 255, 0), (255, 200, 100)] 

# Minimum outline length (in points) for a cell to pass the noise filter.
# Cells whose largest outline across all timepoints is smaller than this are
# discarded as artifacts.
MIN_OUTLINE_LENGTH = 10

# Maximum distance a cell can travel between timepoints, as a multiple of
# the cell's approximate width. A value of 4 means a cell can move up to
# 4x its own width before being treated as a new cell.
DIST_TRAVEL_MULTIPLIER = 4

#Bypasses waiting for user input, answers yes for everything
AUTO_YES = False

# ============================================================================
#  INTERNAL STATE (set at runtime)
# ============================================================================

num_tps = None  # Total number of timepoints; loaded from pickle in __main__


# ============================================================================
#  QUANTITATIVE FUNCTIONS
# ============================================================================

def get_positions(cell3D):
    """Return a list of 3D center positions, one per timepoint.

    Timepoints where the cell doesn't exist are filled with None.
    """
    res = [None] * cell3D.starting_tp
    res += cell3D.centers3D
    while len(res) < num_tps:
        res.append(None)
    return res


def get_displacement_vecs(positions):
    """Return displacement vectors between consecutive timepoints.

    Each entry is (dx, dy, dz) or None if either endpoint is missing.
    """
    res = [None]
    for i in range(1, len(positions)):
        if positions[i - 1] is None or positions[i] is None:
            res.append(None)
        else:
            x = positions[i][0] - positions[i - 1][0]
            y = positions[i][1] - positions[i - 1][1]
            z = positions[i][2] - positions[i - 1][2]
            res.append((x, y, z))
    return res


def get_distance_travelled(displacements):
    """Return Euclidean distance from each displacement vector."""
    res = []
    for displ in displacements:
        if displ is None:
            res.append(None)
        else:
            res.append(sum(coord ** 2 for coord in displ) ** 0.5)
    return res


def _round_tuple(tup, place):
    """Round each element of a tuple to the given decimal place."""
    if tup is None:
        return None
    return tuple(round(elem, place) for elem in tup)


def _round_num(num, place):
    """Round a number to the given decimal place."""
    if isinstance(num, str) or num is None:
        return num
    return round(num, place)


def cell_filter(cell3D):
    """Return True if the cell is large enough to be real (not noise)."""
    max_outlines = []
    for single_tp_cell in cell3D.cells_list:
        max_outlines.append(max(len(outline) for outline in single_tp_cell.outlines))
    return max(max_outlines) > MIN_OUTLINE_LENGTH


# ============================================================================
#  SOLID MESH CREATION
# ============================================================================


def get_solid_mesh_objs(cell3D):
    """Generate a trimesh solid mesh for each timepoint of a Cell3D.

    Returns a list of trimesh.Trimesh objects (or None for missing timepoints).
    Uses spline interpolation + contour stitching as the primary method,
    falling back to direct contour stitching if splining fails.
    """
    mesh_objs = [None] * cell3D.starting_tp

    for single_tp_cell in cell3D.cells_list:
        # Need at least 2 slices to form a 3D shape
        if len(single_tp_cell.outlines) <= 1:
            mesh_objs.append(None)
            continue

        # Generate splined wireframes for smooth interpolation and dome caps
        try:
            splined_xz, splined_yz = cell_point_filler.point_filler(
                cell=copy.deepcopy(single_tp_cell),
                tens=TENS,
                cont=CONT,
                bias=BIAS,
                points_per_segment=POINTS_PER_SEGMENT,
            )
        except Exception:
            splined_xz, splined_yz = [], []

        # Primary path: use wireframe-based mesh with intermediate contours
        if len(splined_xz) + len(splined_yz) >= 4:
            mesh = contour_stitching_mesh.mesh_from_wireframes(
                splined_xz=splined_xz,
                splined_yz=splined_yz,
                outlines=single_tp_cell.outlines,
                starting_slice=single_tp_cell.starting_slice,
            )
        else:
            # Fallback: stitch raw contours directly
            print("Can't spline correctly", end="  ")
            mesh = contour_stitching_mesh.mesh_from_contours(
                outlines=single_tp_cell.outlines,
                starting_slice=single_tp_cell.starting_slice,
            )

        if mesh:
            print("Created mesh,", len(mesh.vertices), "vertices")
        mesh_objs.append(mesh)

    # Pad with None for timepoints after the cell disappears
    while len(mesh_objs) < num_tps:
        mesh_objs.append(None)
    return mesh_objs


# ---------------------------------------------------------------------------
#  Fork-inherited shared state for parallel mesh workers.
#  Set in the parent before Pool creation; children read via COW — no pickling.
# ---------------------------------------------------------------------------
_pool_cells3D = None
_pool_num_tps = None
_pool_tens = None
_pool_cont = None
_pool_bias = None
_pool_pps = None


def _mesh_worker(cell_idx):
    """Mesh worker that reads inputs from fork-inherited module globals.

    Only the integer *cell_idx* travels through the IPC queue.  The heavy
    Cell3D data and configuration are inherited from the parent's address
    space (copy-on-write after fork).
    """
    cell3D = _pool_cells3D[cell_idx]
    num_tps_local = _pool_num_tps

    mesh_objs = [None] * cell3D.starting_tp

    for single_tp_cell in cell3D.cells_list:
        if len(single_tp_cell.outlines) <= 1:
            mesh_objs.append(None)
            continue

        try:
            splined_xz, splined_yz = cell_point_filler.point_filler(
                cell=copy.deepcopy(single_tp_cell),
                tens=_pool_tens,
                cont=_pool_cont,
                bias=_pool_bias,
                points_per_segment=_pool_pps,
            )
        except Exception:
            splined_xz, splined_yz = [], []

        if len(splined_xz) + len(splined_yz) >= 4:
            mesh = contour_stitching_mesh.mesh_from_wireframes(
                splined_xz=splined_xz,
                splined_yz=splined_yz,
                outlines=single_tp_cell.outlines,
                starting_slice=single_tp_cell.starting_slice,
            )
        else:
            mesh = contour_stitching_mesh.mesh_from_contours(
                outlines=single_tp_cell.outlines,
                starting_slice=single_tp_cell.starting_slice,
            )

        mesh_objs.append(mesh)

    while len(mesh_objs) < num_tps_local:
        mesh_objs.append(None)
    return mesh_objs


def parallel_get_solid_mesh_objs(cells3D, num_tps_val, max_workers=None):
    """Generate solid meshes for all cells in parallel via forked workers.

    Uses multiprocessing.Pool with 'fork' context so that the input Cell3D
    list is shared via copy-on-write — only integer indices are pickled
    through the IPC queue.  Falls back to sequential on failure.
    """
    global _pool_cells3D, _pool_num_tps, _pool_tens, _pool_cont, _pool_bias, _pool_pps

    if len(cells3D) < 2:
        return [get_solid_mesh_objs(cell3D=c) for c in cells3D]

    if max_workers is None:
        max_workers = min(os.cpu_count() or 1, len(cells3D))

    _pool_cells3D = cells3D
    _pool_num_tps = num_tps_val
    _pool_tens = TENS
    _pool_cont = CONT
    _pool_bias = BIAS
    _pool_pps = POINTS_PER_SEGMENT

    try:
        ctx = multiprocessing.get_context("fork")
        with ctx.Pool(max_workers) as pool:
            all_meshes = pool.map(_mesh_worker, range(len(cells3D)))
    except Exception as exc:
        print(f"Parallel mesh generation failed ({exc}), falling back to sequential")
        all_meshes = [get_solid_mesh_objs(cell3D=c) for c in cells3D]
    finally:
        _pool_cells3D = None

    return all_meshes


def get_volumes(meshes):
    """Extract absolute volume from each mesh (or None)."""
    return [abs(m.volume) if m else None for m in meshes]


def get_SAs(meshes):
    """Extract surface area from each mesh (or None)."""
    return [m.area if m else None for m in meshes]


# ============================================================================
#  EXPORT FUNCTIONS
# ============================================================================

def export_csv_data(cells3D, output_path, all_meshes=None):
    """Export per-cell, per-timepoint quantitative data to a CSV file."""
    data = []
    for cell_idx, cell3D in enumerate(cells3D):
        print("\n\nCell ID:", cell3D.id)
        data.append({"Cell ID": cell3D.id})

        positions = get_positions(cell3D=cell3D)
        displacement_vecs = get_displacement_vecs(positions=positions)
        distances = get_distance_travelled(displacement_vecs)

        meshes = all_meshes[cell_idx] if all_meshes else get_solid_mesh_objs(cell3D=cell3D)
        volumes = get_volumes(meshes=meshes)
        SAs = get_SAs(meshes=meshes)

        for timepoint in range(num_tps):
            pos = _round_tuple(positions[timepoint], ROUND_DECIMAL_PLACE)
            displ_vec = _round_tuple(displacement_vecs[timepoint], ROUND_DECIMAL_PLACE)
            dist = _round_num(distances[timepoint], ROUND_DECIMAL_PLACE)
            vol = _round_num(volumes[timepoint], ROUND_DECIMAL_PLACE)
            area = _round_num(SAs[timepoint], ROUND_DECIMAL_PLACE)

            data.append({
                "Timepoint": timepoint,
                "Position": pos,
                "X Pos": pos[0] if pos else None,
                "Y Pos": pos[1] if pos else None,
                "Z Pos": pos[2] if pos else None,
                "Displacement Vector": displ_vec,
                "X Disp": displ_vec[0] if displ_vec else None,
                "Y Disp": displ_vec[1] if displ_vec else None,
                "Z Disp": displ_vec[2] if displ_vec else None,
                "Distance Traveled": dist,
                "Volume": vol,
                "Surface Area": area,
            })

    df = pd.DataFrame(data)
    df.to_csv(output_path, index=False)


def export_solid_meshs(cells3D, output_path, min_size=None, all_meshes=None):
    """Export solid mesh data to a MESH .pkl file for Blender rendering.

    The pickle structure is {timepoint_index: [mesh_obj, ...]} where each
    mesh_obj is a dict with 'vertices', 'faces', 'color', and 'name'.
    """
    mesh_frames_dict = {}

    for cell_idx, cell3D in enumerate(cells3D):
        meshes = (all_meshes[cell_idx] if all_meshes
                  else get_solid_mesh_objs(cell3D=copy.deepcopy(cell3D)))

        for t, mesh in enumerate(meshes):
            if mesh is None:
                continue
            if min_size is not None and abs(mesh.volume) < min_size:
                continue

            mesh_obj = {
                "vertices": mesh.vertices.tolist(),
                "faces": mesh.faces.tolist(),
                "color": cell3D.color,
                "name": f"cell_{cell_idx}_t{t}",
            }

            # Ensure all timepoint keys exist in order
            if t not in mesh_frames_dict:
                for i in range(t):
                    if i not in mesh_frames_dict:
                        mesh_frames_dict[i] = []
                mesh_frames_dict[t] = []

            mesh_frames_dict[t].append(mesh_obj)

    with open(output_path, "wb") as f:
        f.write(b"MESH\n")
        pickle.dump(mesh_frames_dict, f)

    print(f"Exported solid mesh data to {output_path}")
    return mesh_frames_dict


def export_tracers(cells3D, output_path):
    """Export cell center trajectories to a TRACER .pkl file.

    The pickle structure is {(R,G,B): [[pos1, pos2, ...], ...]} where each
    position is an (x, y, z) tuple.
    """
    tracers = {}
    for cell_obj in cells3D:
        col = cell_obj.color
        positions = [p for p in get_positions(cell_obj) if p is not None]
        if col in tracers:
            tracers[col].append(positions)
        else:
            tracers[col] = [positions]

    with open(output_path, "wb") as f:
        f.write(b"TRACER\n")
        pickle.dump(tracers, f)

    return tracers


# ============================================================================
#  MAIN - Interactive script
# ============================================================================

if __name__ == "__main__":
    wireframe_path = PATH_TO_WIREFRAME
    base_name = os.path.splitext(os.path.basename(wireframe_path))[0]
    output_dir = os.path.dirname(wireframe_path) or "."

    matched_cells_path = os.path.join(output_dir, base_name + " matched_cells.pkl")
    matched_cells_tp_path = os.path.join(output_dir, base_name + " matched_cells_tp_num.pkl")

    colors = COLORS

    if AUTO_YES or input("Skip Cell Matching? If you've already ran this once b4 with no changes to input, don't bother rematching. To match, input n (y/n) ").strip().lower() == "n":
        from BioVision.processing import get_matched_cells
        get_matched_cells.get_cells3D(
            path=wireframe_path,
            colors=colors,
            output_path=matched_cells_path,
            tp_path=matched_cells_tp_path,
        )

    with open(matched_cells_path, "rb") as f:
        cells3D = pickle.load(f)

    with open(matched_cells_tp_path, "rb") as f:
        num_tps = pickle.load(f)

    # Export all outputs
    print("Tracers")
    export_tracers(
        cells3D=cells3D,
        output_path=os.path.join(output_dir, base_name + " TRACERS.pkl"),
    )

    print("Computing meshes")
    all_meshes = parallel_get_solid_mesh_objs(cells3D, num_tps)

    print("CSV data")
    export_csv_data(
        cells3D=cells3D,
        output_path=os.path.join(output_dir, base_name + " QUANT DATA.csv"),
        all_meshes=all_meshes,
    )

    print("Meshes")
    export_solid_meshs(
        cells3D=cells3D,
        output_path=os.path.join(output_dir, base_name + " SOLIDS.pkl"),
        all_meshes=all_meshes,
    )
