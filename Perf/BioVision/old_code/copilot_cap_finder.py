#New cap finder, using copilot instead of chatgpt
import numpy as np
from typing import List

def useful_four(outline: np.ndarray, top_or_bottom: str) -> List[np.ndarray]:
    """
    Extract four key points from an outline (top or bottom), assuming it wraps around.
    Middle two points are on top or bottom slice.
    """
    n = len(outline)
    if top_or_bottom == "top":
        middle = n // 2
        return [outline[(middle - 2) % n], outline[(middle - 1) % n], outline[middle % n], outline[(middle + 1) % n]]
    else:  # bottom
        return [outline[-2], outline[-1], outline[0], outline[1]]

def outlines_intersect(outline1: np.ndarray, outline2: np.ndarray, top_or_bottom: str) -> bool:
    """
    Check if the center segments of two outlines intersect in XY.
    Only uses the middle two points (assumed to be top slice) of each outline.
    """
    [A, B] = useful_four(outline1, top_or_bottom)[1:3]
    [C, D] = useful_four(outline2, top_or_bottom)[1:3]

    def ccw(P, Q, R):
        return (R[1] - P[1]) * (Q[0] - P[0]) > (Q[1] - P[1]) * (R[0] - P[0])

    return ccw(A, C, D) != ccw(B, C, D) and ccw(A, B, C) != ccw(A, B, D)

def segment_intersection_2d(A, B, C, D):
    """
    Find intersection point of segments AB and CD in 2D, if they intersect.
    Returns None if no intersection.
    """
    def det(a, b):
        return a[0]*b[1] - a[1]*b[0]
    BA = B - A
    DC = D - C
    AC = A - C
    denominator = det(BA, DC)
    if denominator == 0:
        return None  # Parallel
    t = det(AC, DC) / denominator
    u = det(AC, BA) / denominator
    if 0 <= t <= 1 and 0 <= u <= 1:
        intersection = A + t * BA
        return intersection
    return None

def compute_cap_points_with_intersections(
    xz_outlines: List[np.ndarray],
    yz_outlines: List[np.ndarray],
    z_top: float,
    z_ceil: float
) -> np.ndarray:
    """
    Computes cap points only at actual intersections of top-slice segments from XZ and YZ outlines.
    """
    def estimate_tangent_3d(points: np.ndarray) -> np.ndarray:
        return points[3] - points[1]

    xz_tangents = [estimate_tangent_3d(useful_four(p, "top")) for p in xz_outlines]
    yz_tangents = [estimate_tangent_3d(useful_four(p, "top")) for p in yz_outlines]

    guide_points = []

    for xi, xz in enumerate(xz_outlines):
        xz_four = useful_four(xz, "top")
        A, B = xz_four[1], xz_four[2]
        dx, _, dz_dx = xz_tangents[xi]

        for yi, yz in enumerate(yz_outlines):
            yz_four = useful_four(yz, "top")
            C, D = yz_four[1], yz_four[2]
            _, dy, dz_dy = yz_tangents[yi]

            # Only process if top outlines intersect
            if outlines_intersect(xz, yz, "top"):
                intersection = segment_intersection_2d(A[:2], B[:2], C[:2], D[:2])
                if intersection is not None:
                    x, y = intersection
                    x_base = A[0]
                    y_base = C[1]
                    grad_dx = dz_dx / dx if dx != 0 else 0
                    grad_dy = dz_dy / dy if dy != 0 else 0

                    zx_est = z_top + grad_dx * (x - x_base)
                    zy_est = z_top + grad_dy * (y - y_base)
                    z_est = (zx_est + zy_est) / 2

                    guide_points.append([x, y, z_est])

    guide_points = np.array(guide_points)

    # Global Z scaling if needed
    if len(guide_points) > 0:
        z_est_vals = guide_points[:, 2]
        z_max = np.max(z_est_vals)

        if z_max > z_ceil:
            alpha = (z_ceil - z_top) / (z_max - z_top)
            guide_points[:, 2] = z_top + alpha * (z_est_vals - z_top)

    return guide_points