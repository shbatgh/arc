"""
Animation Cell Matching

Tracks cells across timepoints to produce Cell3D objects that represent
a single biological cell's trajectory through time.

Algorithm:
  1. Create initial Cell3D objects from the first timepoint.
  2. For each subsequent timepoint:
     a. Compute pairwise distances between all cells in the current and
        previous timepoints.
     b. Greedily match the closest pairs, filtering by a maximum travel
        distance proportional to cell size.
     c. Unmatched cells in the current timepoint become new Cell3D objects
        (cell division or new appearance).

Called by get_matched_cells.py.
"""

import math
import copy
import multiprocessing
import os
import pickle

from . import single_stack_cell_matching

# ============================================================================
#  CONFIGURATION
# ============================================================================

# Maximum distance a cell can travel between timepoints, as a multiple of
# the cell's approximate width. A value of 4 means a cell can move up to
# 4x its own width before being treated as a new cell.
DIST_TRAVEL_MULTIPLIER = 6

# Physical Z spacing per slice (microns converted to coordinate units).
Z_PER_SLICE = 3 / 0.198

# ============================================================================
#  INTERNAL STATE
# ============================================================================

cell3D_count = 0
cells3D = []

# Fork-inherited shared state for parallel workers.
_pool_wf_data = None
_pool_wf_color = None
_pool_raw_cells = None
_pool_match_color = None


# ============================================================================
#  CELL3D CLASS
# ============================================================================

class Cell3D:
    """Represents a single cell tracked across multiple timepoints.

    Attributes:
        id:          Unique string identifier.
        color:       (R, G, B) tuple of the cell's drawn color.
        starting_tp: Index of the first timepoint where this cell appears.
        final_tp:    Index of the last timepoint where this cell appears.
        centers3D:   List of (x, y, z) center positions, one per timepoint.
        cells_list:  List of Cell2D objects, one per timepoint.
    """
    def __init__(self, id, starting_tp, initial_cell_obj, c_color):
        self.id = id
        self.color = c_color
        self.starting_tp = starting_tp
        self.final_tp = starting_tp
        self.centers3D = [_find_3D_center(initial_cell_obj)]
        self.cells_list = [initial_cell_obj]

        global cell3D_count, cells3D
        cell3D_count += 1
        cells3D.append(self)

    def add_cell(self, new_cell_obj):
        """Add a Cell2D from the next timepoint to this Cell3D."""
        self.final_tp += 1
        self.cells_list.append(new_cell_obj)
        self.centers3D.append(_find_3D_center(new_cell_obj))


# ============================================================================
#  GEOMETRY HELPERS
# ============================================================================

def _find_3D_center(cell_obj):
    """Compute the 3D center of a Cell2D.

    X and Y are the average of all outline points across all slices.
    Z is the midpoint between the starting and top slice.
    """
    total_points = 0
    x_sum, y_sum = 0, 0

    for point_list in cell_obj.outlines:
        total_points += len(point_list)
        for x, y in point_list:
            x_sum += x
            y_sum += y

    z = (cell_obj.top_slice + cell_obj.starting_slice) * 0.5 * Z_PER_SLICE
    return (x_sum / total_points, y_sum / total_points, z)


def _approx_width(cell_obj, axis):
    """Approximate the cell's width along a given axis (x, y, or z)."""
    if axis == "z":
        return len(cell_obj.outlines) * Z_PER_SLICE

    comp = 0 if axis == "x" else 1
    res_min = cell_obj.outlines[0][0][comp]
    res_max = cell_obj.outlines[0][0][comp]

    for point_list in cell_obj.outlines:
        for p in point_list:
            if p[comp] < res_min:
                res_min = p[comp]
            elif p[comp] > res_max:
                res_max = p[comp]
        return res_max - res_min


# ============================================================================
#  MATCHING ALGORITHM
# ============================================================================

def _match_cells(cur_cells, prev_cells):
    """Compute all pairwise distances between cells in adjacent timepoints.

    Returns a list of [((center1, cell1), (center2, cell2)), distance] sorted
    by distance (closest first).

    A plain dict cannot be used here because two cells can legitimately share
    the same center coordinates. Dict key collisions would silently erase one
    side of the candidate pair and corrupt the matching pass.
    """
    matched_list = []
    for cur_c in cur_cells:
        cur_center = _find_3D_center(cur_c)
        for prev_c in prev_cells:
            prev_center = _find_3D_center(prev_c)
            matched_list.append([
                ((cur_center, cur_c), (prev_center, prev_c)),
                math.dist(cur_center, prev_center),
            ])
    matched_list.sort(key=lambda e: e[1])
    return matched_list


def _remove_pairs(matched_list, center):
    """Remove all pairs that involve a given center point."""
    return [
        pair
        for pair in matched_list
        if center not in (pair[0][0][0], pair[0][1][0])
    ]


def _find_max_error(cell_obj1, cell_obj2):
    """Compute the maximum allowed distance for two cells to be considered the same.

    Based on the average of the two cells' approximate widths in x, y, z.
    """
    approx_r1 = (_approx_width(cell_obj1, "x") + _approx_width(cell_obj1, "y") +
                 _approx_width(cell_obj1, "z")) / 3
    approx_r2 = (_approx_width(cell_obj2, "x") + _approx_width(cell_obj2, "y") +
                 _approx_width(cell_obj2, "z")) / 3
    return (approx_r1 + approx_r2) * 0.5 * DIST_TRAVEL_MULTIPLIER


def _appears_before(matched_list, center, loc):
    """Check if a center appears in any pair before index loc."""
    for e in matched_list[:loc]:
        if center in (e[0][0][0], e[0][1][0]):
            return True
    return False


def _tag_centers(matched_list, center, starting_idx):
    """Find all partner centers that haven't been matched yet."""
    tagged = []
    for cur_idx in range(starting_idx, len(matched_list)):
        pair = matched_list[cur_idx]
        c_centers = [pair[0][0][0], pair[0][1][0]]
        if center in c_centers:
            c_centers.remove(center)
            center_pos_tag = c_centers[0]
            if not _appears_before(matched_list, center_pos_tag, cur_idx):
                tagged.append(center_pos_tag)
    return tagged


def _filter_pairs(matched_list):
    """Greedily select the best non-conflicting matches within distance threshold.

    Iterates through pairs (sorted by distance). For each accepted pair, removes
    all other pairs involving either cell. Then filters by max travel distance.
    """
    filtered = []
    idx = 0
    while idx < len(matched_list):
        filtered.append(matched_list[idx])

        paired_centers = [matched_list[idx][0][0][0], matched_list[idx][0][1][0]]
        tagged = [paired_centers[0], paired_centers[1]]
        tagged += _tag_centers(matched_list, paired_centers[0], idx + 1)
        tagged += _tag_centers(matched_list, paired_centers[1], idx + 1)

        for center in tagged:
            matched_list = _remove_pairs(matched_list, center)

    # Apply distance threshold
    result = []
    for pair in filtered:
        cell_objs = [pair[0][0][1], pair[0][1][1]]
        max_error = _find_max_error(cell_objs[0], cell_objs[1])
        if pair[1] < max_error:
            result.append(pair)
    return result


def _identify_cell(center, color):
    """Find the Cell3D that has the given center position and color."""
    for c_obj in cells3D:
        if c_obj.color == color and center in c_obj.centers3D:
            return c_obj
    print("No Cell Found with center:", center)
    return None


def _compute_tp(all_raw_cells, tp_num, color):
    """Process one timepoint: match current cells to previous, create new Cell3Ds for unmatched."""
    cur_cells = [c for c in copy.deepcopy(all_raw_cells[tp_num]) if c.color == color]
    prev_cells = [c for c in copy.deepcopy(all_raw_cells[tp_num - 1]) if c.color == color]

    if len(cur_cells) == 0:
        return
    if len(prev_cells) == 0:
        for cell_obj in cur_cells:
            Cell3D(
                id=str(cell3D_count) + "_" + str(color) + "_Cell3D",
                starting_tp=tp_num,
                initial_cell_obj=cell_obj,
                c_color=color,
            )
        return

    matched_list = _match_cells(cur_cells, prev_cells)
    filtered_list = _filter_pairs(matched_list)

    # Link matched cells to their existing Cell3D
    for pair in filtered_list:
        cur_cell_obj = pair[0][0][1]
        prev_center = pair[0][1][0]
        cell_3D_obj = _identify_cell(prev_center, color)
        cell_3D_obj.add_cell(new_cell_obj=cur_cell_obj)
        cur_cells.remove(cur_cell_obj)

    # Remaining unmatched cells are new or divided
    for cell_obj in cur_cells:
        print("Cell divided or new cell found, timepoint:", tp_num)
        Cell3D(
            id=str(cell3D_count) + "_" + str(color) + "_Cell3D",
            starting_tp=tp_num,
            initial_cell_obj=cell_obj,
            c_color=color,
        )


def _first_timepoint_cells(first_tp_cells, color):
    """Create initial Cell3D objects from the first timepoint."""
    for cell in first_tp_cells:
        if cell.color == color:
            Cell3D(
                id=str(cell3D_count) + "_" + str(color) + "_Cell3D",
                starting_tp=0,
                initial_cell_obj=cell,
                c_color=color,
            )


def compute_animation(all_raw_cells, color):
    """Match cells of a given color across all timepoints.

    Args:
        all_raw_cells: List of lists of Cell2D objects, one list per timepoint.
        color:         (R, G, B) tuple to process.

    Returns:
        List of Cell3D objects for this color.
    """
    global cells3D
    cells3D = []
    _first_timepoint_cells(all_raw_cells[0], color)
    for tp in range(1, len(all_raw_cells)):
        _compute_tp(all_raw_cells, tp, color)
    print("Number of cells:", cell3D_count)
    return cells3D


# ============================================================================
#  PARALLEL ANIMATION MATCHING
# ============================================================================

def _transition_match_worker(tp_num):
    """Compute matching between tp_num-1 and tp_num. Returns (matched, unmatched).

    Runs in a forked child process. Reads all_raw_cells via COW global.
    """
    cur_cells = [c for c in _pool_raw_cells[tp_num] if c.color == _pool_match_color]
    prev_cells = [c for c in _pool_raw_cells[tp_num - 1] if c.color == _pool_match_color]

    if not cur_cells:
        return ([], [])
    if not prev_cells:
        return ([], cur_cells)

    matched_list = _match_cells(cur_cells, prev_cells)
    filtered_list = _filter_pairs(matched_list)

    matched = []
    matched_cur = set()
    for pair in filtered_list:
        cur_cell = pair[0][0][1]
        prev_center = pair[0][1][0]
        idx = next(i for i, c in enumerate(cur_cells) if c is cur_cell)
        matched.append((cur_cell, prev_center))
        matched_cur.add(idx)

    unmatched = [c for i, c in enumerate(cur_cells) if i not in matched_cur]
    return (matched, unmatched)


def compute_animation_parallel(all_raw_cells, color, max_workers=None):
    """Like compute_animation but parallelizes matching computation across transitions.

    Phase A: Pre-compute all transition matchings in parallel (O(n²) pairwise distances).
    Phase B: Sequentially assemble Cell3D objects from pre-computed results.
    """
    global _pool_raw_cells, _pool_match_color, cells3D

    num_tps = len(all_raw_cells)
    if num_tps < 3:
        return compute_animation(all_raw_cells, color)

    if max_workers is None:
        max_workers = min(os.cpu_count() or 1, num_tps - 1)

    # Phase A: Pre-compute all transition matchings in parallel
    _pool_raw_cells = all_raw_cells
    _pool_match_color = color
    try:
        ctx = multiprocessing.get_context("fork")
        with ctx.Pool(max_workers) as pool:
            transition_results = pool.map(_transition_match_worker, range(1, num_tps))
    except Exception as exc:
        print(f"Parallel animation matching failed ({exc}), falling back to sequential")
        return compute_animation(all_raw_cells, color)
    finally:
        _pool_raw_cells = None
        _pool_match_color = None

    # Phase B: Sequential Cell3D assembly from pre-computed matchings
    cells3D = []
    _first_timepoint_cells(all_raw_cells[0], color)

    for tp_num, (matched, unmatched) in enumerate(transition_results, start=1):
        for cur_cell, prev_center in matched:
            cell_3D = _identify_cell(prev_center, color)
            if cell_3D is not None:
                cell_3D.add_cell(cur_cell)
        for cell_obj in unmatched:
            Cell3D(
                id=str(cell3D_count) + "_" + str(color) + "_Cell3D",
                starting_tp=tp_num,
                initial_cell_obj=cell_obj,
                c_color=color,
            )

    print("Number of cells:", cell3D_count)
    return cells3D


# ============================================================================
#  DATA LOADING
# ============================================================================

def get_raw_cell_data(path, color):
    """Load a WIREFRAME pickle and extract Cell2D objects for one color.

    For each timepoint, runs the single-stack cell matching algorithm to
    group outlines into Cell2D objects.

    Returns:
        List of lists of Cell2D objects, one list per timepoint.
    """
    with open(path, "rb") as f:
        f.readline()  # skip header
        data = pickle.load(f)

    all_raw_cells = []
    for tp in range(len(data.keys())):
        cur_cell_objs = single_stack_cell_matching.compute_stack(
            stack_list=copy.deepcopy(data[tp]),
            color=color,
        )
        all_raw_cells.append(cur_cell_objs)

    return all_raw_cells


# ============================================================================
#  PARALLEL DATA LOADING
# ============================================================================

def _stack_tp_worker(tp):
    """Process one timepoint's Z-slice matching. Reads data via fork COW."""
    return single_stack_cell_matching.compute_stack(
        stack_list=_pool_wf_data[tp],
        color=_pool_wf_color,
    )


def get_raw_cell_data_parallel(path, color, max_workers=None):
    """Like get_raw_cell_data but parallelizes across timepoints.

    Each timepoint's Z-slice matching is completely independent. Uses fork
    so children inherit the unpickled data via COW without re-serialization.
    """
    global _pool_wf_data, _pool_wf_color

    with open(path, "rb") as f:
        f.readline()  # skip header
        data = pickle.load(f)

    num_tps = len(data)
    if max_workers is None:
        max_workers = min(os.cpu_count() or 1, num_tps)

    _pool_wf_data = data
    _pool_wf_color = color
    try:
        ctx = multiprocessing.get_context("fork")
        with ctx.Pool(max_workers) as pool:
            all_raw_cells = pool.map(_stack_tp_worker, range(num_tps))
    except Exception as exc:
        print(f"Parallel stack matching failed ({exc}), falling back to sequential")
        all_raw_cells = [
            single_stack_cell_matching.compute_stack(data[tp], color)
            for tp in range(num_tps)
        ]
    finally:
        _pool_wf_data = None
        _pool_wf_color = None

    return all_raw_cells
