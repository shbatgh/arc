import numpy as np

def compute_angle(p1, p2, p3):
    """Returns signed angle in radians between the vectors p1->p2 and p2->p3."""
    v1 = np.array(p1) - np.array(p2)
    v2 = np.array(p3) - np.array(p2)
    angle = np.arctan2(np.cross(v1, v2)[-1], np.dot(v1, v2))
    return angle

def inject_points_curved_arc(outline, num_points_between=2, curvature_scale=0.2, exclude_caps=False):
    """
    Injects points between every pair of outline points using curvature-aware arcs.

    Parameters:
    - outline: List of 3D points (looped).
    - num_points_between: Number of points to insert between each segment.
    - curvature_scale: Controls arc bend intensity based on angle.
    - exclude_caps: Whether to skip top/bottom of the loop.
    """

    injected = []
    n = len(outline)
    midpoint_idx = n // 2

    for i in range(n):
        p1 = np.array(outline[i - 1])
        p2 = np.array(outline[i])
        p3 = np.array(outline[(i + 1) % n])

        # Determine if this is a cap
        if exclude_caps:
            if (i == 0 and (i + 1) % n == n - 1) or (i == midpoint_idx or (i + 1) % n == midpoint_idx):
                continue

        # Compute curvature angle
        angle = compute_angle(p1, p2, p3)
        angle_factor = curvature_scale * angle

        # Inject points along a curved arc
        injected.append(p2.tolist())
        direction = np.array(p3) - np.array(p2)

        # Get normal direction to curve (approx)
        normal = np.cross(direction, np.array([0, 0, 1]))
        normal = normal / (np.linalg.norm(normal) + 1e-8)

        for j in range(1, num_points_between + 1):
            t = j / (num_points_between + 1)
            base = (1 - t) * np.array(p2) + t * np.array(p3)
            offset = angle_factor * np.sin(np.pi * t) * normal
            injected.append((base + offset).tolist())

    return injected
