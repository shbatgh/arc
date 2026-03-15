"""
Catmull-Rom Spline Injecter

Densifies 3D wireframe loops by inserting interpolated points between
each pair of consecutive points using Catmull-Rom spline interpolation.

Called by cell_point_filler.py.
"""

import numpy as np


def catmull_rom_spline(P0, P1, P2, P3, n_points):
    """Compute n_points interpolated points between P1 and P2.

    Uses the standard Catmull-Rom spline formula with 4 control points.
    Points are evenly spaced in parameter space (not arc length).
    """
    t = np.linspace(0, 1, n_points + 2)[1:-1]  # exclude endpoints
    points = []
    for tt in t:
        tt2 = tt * tt
        tt3 = tt2 * tt
        x = 0.5 * ((2 * P1[0]) +
                    (-P0[0] + P2[0]) * tt +
                    (2 * P0[0] - 5 * P1[0] + 4 * P2[0] - P3[0]) * tt2 +
                    (-P0[0] + 3 * P1[0] - 3 * P2[0] + P3[0]) * tt3)
        y = 0.5 * ((2 * P1[1]) +
                    (-P0[1] + P2[1]) * tt +
                    (2 * P0[1] - 5 * P1[1] + 4 * P2[1] - P3[1]) * tt2 +
                    (-P0[1] + 3 * P1[1] - 3 * P2[1] + P3[1]) * tt3)
        z = 0.5 * ((2 * P1[2]) +
                    (-P0[2] + P2[2]) * tt +
                    (2 * P0[2] - 5 * P1[2] + 4 * P2[2] - P3[2]) * tt2 +
                    (-P0[2] + 3 * P1[2] - 3 * P2[2] + P3[2]) * tt3)
        points.append([x, y, z])
    return points


def inject_catmull_rom_points(point_list, points_per_segment, top_spline=True):
    """Densify a closed 3D wireframe loop with Catmull-Rom interpolation.

    For each consecutive pair of points, inserts points_per_segment new points
    using the surrounding 4 points (wrapping around the loop) as control points.

    Args:
        point_list:         List of [x, y, z] points forming a closed loop.
        points_per_segment: Number of new points to insert per segment.
        top_spline:         If False, skip interpolation on segments at the
                            extreme Z levels (top/bottom caps).

    Returns:
        Densified list of [x, y, z] points.
    """
    max_z = max(p[2] for p in point_list)
    min_z = min(p[2] for p in point_list)

    n = len(point_list)
    new_points = []
    for i in range(n):
        P0 = point_list[(i - 1) % n]
        P1 = point_list[i]
        P2 = point_list[(i + 1) % n]
        P3 = point_list[(i + 2) % n]
        new_points.append(P1)

        # Optionally skip interpolation at the cap level (flat top/bottom)
        if not top_spline:
            if (P1[2] == max_z and P2[2] == max_z) or (P1[2] == min_z and P2[2] == min_z):
                continue

        extra = catmull_rom_spline(P0, P1, P2, P3, points_per_segment)
        new_points.extend(extra)

    return new_points
