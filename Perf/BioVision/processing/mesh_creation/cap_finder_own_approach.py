"""
Cap Finder

Extends vertical wireframe loops beyond the topmost and bottommost slices
to create dome-shaped caps that close the cell.

Algorithm:
  1. Find which wireframe loops touch the top (or bottom) Z-level.
  2. For each pair of XZ and YZ loops that both touch the cap level, find
     where they intersect in the XY plane.
  3. Estimate the Z value at each intersection using Kochanek-Bartels spline
     interpolation through the 4 points nearest the cap.
  4. Scale cap points so they don't extend more than one slice spacing beyond
     the data.
  5. Insert cap points into their parent wireframe loops as arch extensions.

Called by cell_point_filler.py.
"""

import copy

from . import kochanek_bartels_spline_safe

# Module-level spline parameters (set per call to execute)
tens = 0
cont = 0
bias = 0

# Global arch storage (cleared per call to execute)
arches = []


# ============================================================================
#  ARCH CLASS - represents the dome extension on one wireframe loop
# ============================================================================

class Arch:
    """A set of cap points that extend one wireframe loop beyond the data range.

    Attributes:
        arch:           List of (x, y, z) cap points belonging to this arch.
        XZ_outline:     The parent XZ wireframe loop (or None if YZ).
        YZ_outline:     The parent YZ wireframe loop (or None if XZ).
        top_or_bottom:  "top" or "bottom".
        XZ_or_YZ:       "XZ" or "YZ" indicating which plane this loop lies in.
    """
    def __init__(self, arch, XZ_outline, YZ_outline, top_or_bottom):
        self.arch = arch
        self.XZ_outline = XZ_outline
        self.YZ_outline = YZ_outline
        self.top_or_bottom = top_or_bottom
        self.XZ_or_YZ = "YZ" if XZ_outline is None else "XZ"
        arches.append(self)

    def order_arch(self):
        """Sort cap points along the wireframe's primary axis."""
        sort_idx = 0 if self.XZ_or_YZ == "XZ" else 1
        self.arch = sorted(self.arch, key=lambda e: e[sort_idx])
        if self.top_or_bottom == "bottom":
            self.arch.reverse()

    def add_to_outline(self):
        """Return the parent outline with cap points spliced in.

        For top caps, the arch is inserted at the midpoint of the loop.
        For bottom caps, the arch is appended at the end.
        """
        working_outline = self.XZ_outline if self.XZ_or_YZ == "XZ" else self.YZ_outline
        self.order_arch()

        result = []
        if self.top_or_bottom == "top":
            middle = len(working_outline) // 2
            result.extend(working_outline[:middle])
            result.extend(self.arch)
            result.extend(working_outline[middle:])
        else:
            result.extend(working_outline)
            result.extend(self.arch)
        return result


def _create_arches(XZ_outlines, YZ_outlines, top_or_bottom):
    """Create an Arch object for each wireframe loop that touches the cap level."""
    for outline in XZ_outlines:
        Arch(arch=[], XZ_outline=outline, YZ_outline=None, top_or_bottom=top_or_bottom)
    for outline in YZ_outlines:
        Arch(arch=[], XZ_outline=None, YZ_outline=outline, top_or_bottom=top_or_bottom)


def _identify_arch(outline, top_or_bottom):
    """Find the Arch associated with a given wireframe outline."""
    for arch in arches:
        if arch.top_or_bottom == top_or_bottom and (
            arch.XZ_outline is outline or arch.YZ_outline is outline
        ):
            return arch
    return None


# ============================================================================
#  CAP POINT CLASS - a single point on the dome surface
# ============================================================================

class CapPoint:
    """A single point on the dome cap surface.

    Created at the intersection of an XZ and YZ wireframe loop. The Z
    coordinate is estimated via Kochanek-Bartels spline interpolation.

    Attributes:
        pos: (x, y, z) position of this cap point.
        z:   The estimated Z coordinate (mutable for scaling).
    """
    def __init__(self, XZ_line, YZ_line, top_or_bottom, intersection):
        self.XZ_pts = _four_imp_points(XZ_line, top_or_bottom)
        self.YZ_pts = _four_imp_points(YZ_line, top_or_bottom)
        self.top_or_bottom = top_or_bottom
        self.intersection = intersection
        self.z = _find_z(self.XZ_pts, self.YZ_pts, intersection, top_or_bottom)
        self.pos = (intersection[0], intersection[1], self.z)


# ============================================================================
#  GEOMETRY HELPERS
# ============================================================================

def _find_z(XZ_pts, YZ_pts, intersection, top_or_bottom):
    """Estimate the Z coordinate at an XY intersection using spline interpolation.

    Evaluates the Kochanek-Bartels spline through the 4 nearest points on
    both the XZ and YZ wireframes, then takes the more conservative (lower
    for top, higher for bottom) of the two Z estimates.
    """
    # XZ wireframe: extract (x, z) pairs and evaluate at intersection's x
    xz_2d = [[pt[0], pt[2]] for pt in XZ_pts]
    z1 = kochanek_bartels_spline_safe.v_for_u_nonuniform(
        target_u=intersection[0],
        P0=xz_2d[0], P1=xz_2d[1], P2=xz_2d[2], P3=xz_2d[3],
        tension=tens, continuity=cont, bias=bias,
    )

    # YZ wireframe: extract (y, z) pairs and evaluate at intersection's y
    yz_2d = [[pt[1], pt[2]] for pt in YZ_pts]
    z2 = kochanek_bartels_spline_safe.v_for_u_nonuniform(
        target_u=intersection[1],
        P0=yz_2d[0], P1=yz_2d[1], P2=yz_2d[2], P3=yz_2d[3],
        tension=tens, continuity=cont, bias=bias,
    )

    # Take the extreme Z from each estimate
    if top_or_bottom == "top":
        z1, z2 = max(z1), max(z2)
    else:
        z1, z2 = min(z1), min(z2)

    return min(z1, z2)


def _find_min_max_z(outlines, top_or_bottom):
    """Find the extreme Z value across all wireframe loops."""
    all_z = [pt[2] for outline in outlines for pt in outline]
    return max(all_z) if top_or_bottom == "top" else min(all_z)


def _find_cap_outlines(outlines, cap_lvl):
    """Return only wireframe loops that have a point at the cap Z level."""
    return [
        outline for outline in outlines
        if any(pt[2] == cap_lvl for pt in outline)
    ]


def _four_imp_points(outline, top_or_bottom):
    """Extract the 4 points nearest the cap end of a wireframe loop.

    For "top": the 4 points around the midpoint (where the loop turns around).
    For "bottom": the last 2 points and first 2 points (loop closure region).
    """
    if top_or_bottom == "top":
        mid = len(outline) // 2
        return [outline[mid - 2], outline[mid - 1], outline[mid], outline[mid + 1]]
    else:
        return [outline[-2], outline[-1], outline[0], outline[1]]


def _find_intersection(XZ_line, YZ_line, top_or_bottom):
    """Find the XY intersection point of an XZ and YZ wireframe pair.

    XZ wireframes have constant Y at the cap; YZ wireframes have constant X.
    Returns [x, y] if the intersection is within both segments, else False.
    """
    xz_pts = _four_imp_points(XZ_line, top_or_bottom)
    yz_pts = _four_imp_points(YZ_line, top_or_bottom)
    xz_two = [xz_pts[1], xz_pts[2]]
    yz_two = [yz_pts[1], yz_pts[2]]

    y = xz_two[0][1]
    x1, x2 = xz_two[0][0], xz_two[1][0]
    x = yz_two[0][0]
    y1, y2 = yz_two[0][1], yz_two[1][1]

    if min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2):
        return [x, y]
    return False


# ============================================================================
#  SCALING - constrain cap height to one inter-slice spacing
# ============================================================================

def _find_limit(outlines, top_or_bottom, cap_lvl):
    """Compute the maximum allowed Z extent for cap points.

    The cap shouldn't extend further than one slice spacing beyond the
    topmost (or bottommost) data.
    """
    z_without_cap = [pt[2] for outline in outlines for pt in outline if pt[2] != cap_lvl]
    second_extreme = max(z_without_cap) if top_or_bottom == "top" else min(z_without_cap)
    dist = abs(second_extreme - cap_lvl)
    return cap_lvl + dist if top_or_bottom == "top" else cap_lvl - dist


def _scale_cap_points(cap_points, cap_lvl, limit, top_or_bottom):
    """Scale all cap point Z values to fit within the limit."""
    if not cap_points:
        return

    max_z = max(p.z for p in cap_points)
    min_z = min(p.z for p in cap_points)

    if top_or_bottom == "top" and max_z > limit and max_z != cap_lvl:
        factor = abs((limit - cap_lvl) / (max_z - cap_lvl))
        for p in cap_points:
            p.z = (p.z - cap_lvl) * factor + cap_lvl

    elif top_or_bottom == "bottom" and min_z < limit and min_z != cap_lvl:
        factor = abs((limit - cap_lvl) / (min_z - cap_lvl))
        for p in cap_points:
            p.z = (p.z - cap_lvl) * factor + cap_lvl


# ============================================================================
#  MAIN ENTRY POINT
# ============================================================================

def execute(all_XZ_outlines, all_YZ_outlines, top_or_bottom="top",
            tension_arg=0, continuity_arg=0, bias_arg=0):
    """Find dome cap points and splice them into wireframe loops.

    Args:
        all_XZ_outlines: List of XZ wireframe loops (lists of [x, y, z]).
        all_YZ_outlines: List of YZ wireframe loops.
        top_or_bottom:   "top" or "bottom".
        tension_arg:     Kochanek-Bartels tension.
        continuity_arg:  Kochanek-Bartels continuity.
        bias_arg:        Kochanek-Bartels bias.

    Returns:
        (cap_points, new_XZ_outlines, new_YZ_outlines) where the new outlines
        have cap arches spliced in.
    """
    if len(all_XZ_outlines) == 0 or len(all_YZ_outlines) == 0:
        return [], [], []

    arches.clear()

    global tens, cont, bias
    tens = tension_arg
    cont = continuity_arg
    bias = bias_arg

    # Find which wireframe loops touch the cap Z level
    cap_lvl = _find_min_max_z(all_XZ_outlines + all_YZ_outlines, top_or_bottom)
    XZ_outlines = _find_cap_outlines(all_XZ_outlines, cap_lvl)
    YZ_outlines = _find_cap_outlines(all_YZ_outlines, cap_lvl)

    _create_arches(XZ_outlines, YZ_outlines, top_or_bottom)

    # Create cap points at each XZ/YZ intersection
    cap_points = []
    for XZ_line in XZ_outlines:
        XZ_arch = _identify_arch(XZ_line, top_or_bottom)
        for YZ_line in YZ_outlines:
            intersection = _find_intersection(XZ_line, YZ_line, top_or_bottom)
            if intersection:
                new_cap_point = CapPoint(
                    copy.deepcopy(XZ_line), copy.deepcopy(YZ_line),
                    top_or_bottom, intersection,
                )
                cap_points.append(new_cap_point)
                YZ_arch = _identify_arch(YZ_line, top_or_bottom)
                XZ_arch.arch.append(new_cap_point.pos)
                YZ_arch.arch.append(new_cap_point.pos)

    # If no cap points found, return outlines unchanged
    if len(cap_points) == 0:
        return cap_points, list(all_XZ_outlines), list(all_YZ_outlines)

    # Scale cap points to fit within one slice spacing
    limit = _find_limit(all_XZ_outlines + all_YZ_outlines, top_or_bottom, cap_lvl)
    _scale_cap_points(cap_points, cap_lvl, limit, top_or_bottom)

    # Rebuild outlines with cap arches spliced in
    XZ_res = []
    for outline in all_XZ_outlines:
        arch = _identify_arch(outline, top_or_bottom)
        XZ_res.append(arch.add_to_outline() if arch else outline)

    YZ_res = []
    for outline in all_YZ_outlines:
        arch = _identify_arch(outline, top_or_bottom)
        YZ_res.append(arch.add_to_outline() if arch else outline)

    return cap_points, XZ_res, YZ_res
