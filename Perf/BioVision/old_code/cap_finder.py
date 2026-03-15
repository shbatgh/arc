import numpy as np
from scipy.interpolate import Rbf
from typing import List

def segment_intersection_2d(A, B, C, D):
    def det(a, b):
        return a[0]*b[1] - a[1]*b[0]
    BA = B - A
    DC = D - C
    AC = A - C
    denominator = det(BA, DC)
    if denominator == 0:
        return None
    t = det(AC, DC) / denominator
    u = det(AC, BA) / denominator
    if 0 <= t <= 1 and 0 <= u <= 1:
        intersection = A + t * BA
        return intersection
    return None

def get_top_points(outline: np.ndarray):
    z_max = np.max(outline[:, 2])
    return outline[np.isclose(outline[:, 2], z_max)]

def get_top_segment(outline: np.ndarray):
    top_points = get_top_points(outline)
    if len(top_points) > 2:
        dists = np.linalg.norm(top_points[:, :2][None, :] - top_points[:, :2][:, None], axis=2)
        i, j = np.unravel_index(np.argmax(dists), dists.shape)
        return top_points[i], top_points[j]
    elif len(top_points) == 2:
        return top_points[0], top_points[1]
    else:
        idxs = np.where(np.isclose(outline[:, 2], np.max(outline[:, 2])))[0]
        return outline[idxs[0]], outline[idxs[1 % len(outline)]]

def compute_cap_points_with_intersections(
    xz_outlines: List[np.ndarray],
    yz_outlines: List[np.ndarray]
) -> np.ndarray:
    # 1. Gather all top-slice boundary points
    all_top_points = []
    for outline in xz_outlines + yz_outlines:
        all_top_points.extend(get_top_points(outline))
    all_top_points = np.array(all_top_points)
    X, Y, Z = all_top_points[:, 0], all_top_points[:, 1], all_top_points[:, 2]

    # 2. Fit a smooth spline surface Z = f(X, Y)
    points = np.column_stack((X, Y))
    _, unique_indices = np.unique(points, axis=0, return_index=True)
    X_unique = X[unique_indices]
    Y_unique = Y[unique_indices]
    Z_unique = Z[unique_indices]
    rbf = Rbf(X_unique, Y_unique, Z_unique, function='thin_plate')

    # 3. Find intersections and estimate Z using the spline
    guide_points = []
    for xz in xz_outlines:
        A, B = get_top_segment(xz)
        for yz in yz_outlines:
            C, D = get_top_segment(yz)
            intersection = segment_intersection_2d(A[:2], B[:2], C[:2], D[:2])
            if intersection is not None:
                x, y = intersection
                z = float(rbf(x, y))
                guide_points.append([x, y, z])

    return np.array(guide_points)