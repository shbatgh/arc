"""
Single Stack Cell Matching

Matches cell outlines across Z-slices within a single timepoint to group
them into Cell2D objects. Each Cell2D represents one biological cell's
cross-sections at different heights.

Algorithm:
  1. Start with the bottom slice. Each outline becomes a new Cell2D.
  2. For each subsequent slice:
     a. Compute pairwise distances between outline centers in the current
        and previous slices.
     b. Greedily match the closest pairs within a maximum distance threshold
        proportional to cell size.
     c. Matched outlines are added to the existing Cell2D.
     d. Unmatched outlines become new Cell2D objects.

Called by pickled_animation_cell_matching.py.
"""

from .constants import DIST_MULTIPLIER
from .greedy_matcher import compute_pairwise_distances, greedy_filter

# ============================================================================
#  INTERNAL STATE
# ============================================================================

cell_count = 0
cells = []


# ============================================================================
#  CELL2D CLASS
# ============================================================================

class Cell:
    """Represents a single cell within one timepoint, spanning multiple Z-slices.

    Attributes:
        id:             Unique string identifier.
        color:          (R, G, B) tuple of the cell's drawn color.
        starting_slice: Z-index of the first slice containing this cell.
        top_slice:      Z-index of the last slice containing this cell.
        centers:        List of (x, y) center positions, one per slice.
        outlines:       List of [[x,y], ...] outlines, one per slice.
    """
    def __init__(self, id, starting_slice, initial_outline, c_color):
        self.id = id
        self.color = c_color
        self.starting_slice = starting_slice
        self.top_slice = starting_slice
        self.centers = [_find_center(initial_outline)]
        self.outlines = [initial_outline]

        global cell_count, cells
        cell_count += 1
        cells.append(self)

    def add_outline(self, new_outline):
        """Add an outline from the next slice above."""
        self.top_slice += 1
        self.outlines.append(new_outline)
        self.centers.append(_find_center(new_outline))


# ============================================================================
#  GEOMETRY HELPERS
# ============================================================================

def _find_center(point_list):
    """Compute the (x, y) centroid of an outline."""
    if len(point_list) == 0:
        return None
    x_sum = sum(p[0] for p in point_list)
    y_sum = sum(p[1] for p in point_list)
    n = len(point_list)
    return (x_sum / n, y_sum / n)


def _approx_width(point_list, x_or_y):
    """Approximate the outline's width along X or Y."""
    comp = 1 if x_or_y == "y" else 0
    vals = [p[comp] for p in point_list]
    return max(vals) - min(vals)


# ============================================================================
#  MATCHING ALGORITHM
# ============================================================================

def _find_segs(slice_dict, color):
    """Extract all outlines of a given color from a slice dictionary."""
    if color not in slice_dict:
        return []
    return slice_dict[color].copy()


def _find_max_error(point_list1, point_list2):
    """Compute the maximum allowed distance for two outlines to be the same cell."""
    approx_r1 = max(_approx_width(point_list1, "x"), _approx_width(point_list1, "y"))
    approx_r2 = max(_approx_width(point_list2, "x"), _approx_width(point_list2, "y"))
    return max(approx_r1, approx_r2) * DIST_MULTIPLIER


def _identify_cell(center, color):
    """Find the Cell that owns a given center position and color."""
    for c_obj in cells:
        if c_obj.color == color and center in c_obj.centers:
            return c_obj
    print("No Cell Found with center:", center)
    return None


def _compute_slice(stack_list, slice_num, color):
    """Match outlines in one slice to cells from the slice below."""
    cur_segs = _find_segs(stack_list[slice_num], color)
    prev_segs = _find_segs(stack_list[slice_num - 1], color)

    if len(cur_segs) == 0:
        return
    if len(prev_segs) == 0:
        for seg in cur_segs:
            Cell(
                id="Cell" + str(color) + " " + str(cell_count),
                starting_slice=slice_num,
                initial_outline=seg,
                c_color=color,
            )
        return

    matched_list = compute_pairwise_distances(cur_segs, prev_segs, _find_center)
    filtered_list = greedy_filter(matched_list, _find_max_error)

    for pair in filtered_list:
        cur_outline = pair[0][0][1]
        prev_center = pair[0][1][0]
        cell_obj = _identify_cell(prev_center, color)
        cell_obj.add_outline(new_outline=cur_outline)
        cur_segs.remove(cur_outline)

    for seg in cur_segs:
        Cell(
            id="Cell" + str(color) + " " + str(cell_count),
            starting_slice=slice_num,
            initial_outline=seg,
            c_color=color,
        )


def _first_slice_cells(slice_dict, color):
    """Create initial Cell objects from the bottom slice."""
    for seg in _find_segs(slice_dict, color):
        Cell(
            id="Cell" + str(color) + " " + str(cell_count),
            starting_slice=0,
            initial_outline=seg,
            c_color=color,
        )


def compute_stack(stack_list, color):
    """Match outlines of one color across all slices in a timepoint.

    Args:
        stack_list: List of slice dictionaries (one per Z-slice).
        color:      (R, G, B) tuple to process.

    Returns:
        List of Cell objects for this color in this timepoint.
    """
    global cells
    cells = []
    _first_slice_cells(stack_list[0], color)
    for slice_num in range(1, len(stack_list)):
        _compute_slice(stack_list, slice_num, color)
    return cells
