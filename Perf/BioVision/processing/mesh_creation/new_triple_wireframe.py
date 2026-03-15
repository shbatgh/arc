"""
Triple Wireframe Creation

Creates vertical wireframe loops through a cell by slicing 2D outlines
with evenly spaced cutting planes along the X or Y axis.

Each cutting plane intersects each slice's outline at two points: one on the
"top" side and one on the "bottom" side (relative to the perpendicular axis).
These points are chained bottom-to-top and then top-to-bottom to form a
closed vertical loop through the cell.

Called by cell_point_filler.py.
"""

# Physical Z spacing per slice (microns to coordinate units)
Z_PER_SLICE = 3 / 0.198

# Module-level state (set per call to triple_wireframe_creation)
comp = 0        # 0 for X-axis, 1 for Y-axis
wf_dist = 0     # Spacing between cutting planes
wf_offset = 0   # Tolerance for intersection detection


def _find_min_and_width(outline_list):
    """Find the minimum value and total width of the cell along the active axis."""
    min_val = outline_list[0][0][comp]
    max_val = outline_list[0][0][comp]
    for slice_outline in outline_list:
        for coord in slice_outline:
            if coord[comp] < min_val:
                min_val = coord[comp]
            elif coord[comp] > max_val:
                max_val = coord[comp]
    return min_val, max_val - min_val


def _find_num_wfs(width):
    """Determine how many cutting planes fit across the cell."""
    return round(width / wf_dist) - 1


def _find_planes(min_val, width, num_wfs):
    """Compute the positions of evenly spaced cutting planes."""
    first_plane = (width / 2) - (((num_wfs - 1) / 2) * wf_dist) + min_val
    return [first_plane + i * wf_dist for i in range(num_wfs)]


def _find_dividing_line(outline):
    """Find the average position along the perpendicular axis.

    This divides the outline into a "top" half and "bottom" half.
    """
    switched_comp = (comp + 1) % 2
    return sum(coord[switched_comp] for coord in outline) / len(outline)


def _new_sorted_outlines(outline_list):
    """Create a doubled list: original outlines followed by their reverse.

    The first half is traversed going "up" (bottom to top slice),
    the second half is traversed going "down" (top to bottom).
    """
    result = outline_list.copy()
    for idx in range(len(outline_list) - 1, -1, -1):
        result.append(outline_list[idx])
    return result


def _find_point(point_list, plane_val, min_or_max):
    """Find the outline point closest to a cutting plane.

    Among all points within wf_offset of the plane, returns the one with
    the min or max value on the perpendicular axis.
    """
    valids = [p for p in point_list if abs(plane_val - p[comp]) < wf_offset]
    if len(valids) == 0:
        return -1

    switched_comp = (comp + 1) % 2
    if min_or_max == "min":
        return min(valids, key=lambda p: p[switched_comp])
    else:
        return max(valids, key=lambda p: p[switched_comp])


def _create_wf_list(sorted_outlines, plane_val, z_start):
    """Build one vertical wireframe loop at a given cutting plane position.

    Traverses the "top" points going up (bottom to top slice), then the
    "bottom" points going back down. Only includes slices where both sides
    have valid intersection points.
    """
    num_slices = len(sorted_outlines) // 2

    # Going up: find the "min" side point at each slice
    up_dict = {}
    for idx in range(num_slices):
        point = _find_point(sorted_outlines[idx], plane_val, "min")
        if point == -1:
            continue
        point.append(z_start + idx * Z_PER_SLICE)
        up_dict[idx] = point

    # Going down: find the "max" side point at each slice
    down_dict = {}
    for idx in range(num_slices, 2 * num_slices):
        z = z_start + (2 * num_slices - idx - 1) * Z_PER_SLICE
        point = _find_point(sorted_outlines[idx], plane_val, "max")
        if point == -1:
            continue
        if len(point) < 3:
            point.append(z)
        down_dict[2 * num_slices - idx - 1] = point

    # Only keep slices where both up and down points exist
    up_list = []
    down_list = []
    for idx in up_dict:
        if idx in down_dict:
            up_list.append(up_dict[idx])
            down_list.append(down_dict[idx])

    return up_list + down_list[::-1]


def triple_wireframe_creation(outline_list, x_or_y, starting_slice, wf_dist_arg, wf_offset_arg):
    """Create vertical wireframe loops through the cell.

    Args:
        outline_list:  List of 2D outlines, one per slice.
        x_or_y:        "x" to slice along X-axis, "y" for Y-axis.
        starting_slice: Z-index of the first slice.
        wf_dist_arg:   Spacing between cutting planes.
        wf_offset_arg: Tolerance for intersection detection.

    Returns:
        List of wireframe loops, each a list of [x, y, z] points.
    """
    global comp, wf_dist, wf_offset
    comp = 0 if x_or_y == "x" else 1
    wf_dist = wf_dist_arg
    wf_offset = wf_offset_arg

    min_val, width = _find_min_and_width(outline_list)
    num_wfs = _find_num_wfs(width)
    plane_vals = _find_planes(min_val, width, num_wfs)
    sorted_outlines = _new_sorted_outlines(outline_list)

    wfs = []
    for val in plane_vals:
        wf_list = _create_wf_list(
            sorted_outlines=sorted_outlines,
            plane_val=val,
            z_start=starting_slice * Z_PER_SLICE,
        )
        # Need at least 4 points for spline interpolation
        if len(wf_list) >= 4:
            wfs.append(wf_list)
    return wfs
