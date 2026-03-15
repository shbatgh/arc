import numpy as np
from scipy.interpolate import CubicHermiteSpline


def kochanek_bartels_spline(points, tension=0, continuity=0, bias=0):
    """
    Create a Kochanek–Bartels spline from four (u, v) points.
    Returns a function f(u) that gives v for any u in the range.
    """
    points = np.array(sorted(points, key=lambda pt: pt[0]))
    u = points[:, 0]
    v = points[:, 1]

    # Calculate tangents for each point
    def tangent(i):
        p0, p1, p2 = points[i-1], points[i], points[i+1]
        t = tension
        c = continuity
        b = bias
        dt1 = p1[0] - p0[0]
        dt2 = p2[0] - p1[0]
        # Avoid division by zero
        dt1 = dt1 if dt1 != 0 else 1
        dt2 = dt2 if dt2 != 0 else 1
        term1 = (1-t)*(1+c)*(1+b)*(p1[1]-p0[1])/dt1
        term2 = (1-t)*(1-c)*(1-b)*(p2[1]-p1[1])/dt2
        return 0.5 * (term1 + term2)

    # Tangents for the four points
    tangents = []
    tangents.append(tangent(1))  # for point 1
    tangents.append(tangent(2))  # for point 2

    # Spline only uses inner points for tangents
    # CubicHermiteSpline expects u, v, and derivatives at each point
    # We'll use the four points, but only two tangents (for inner points)
    # For endpoints, set tangents to zero or extrapolate
    m = [0, tangents[0], tangents[1], 0]

    spline = CubicHermiteSpline(u, v, m)

    def spline_func(query_u):
        return spline(query_u)

    return spline_func

# Example usage:
# points = [(0, 1), (1, 2), (2, 1.5), (3, 3)]
# spline = kochanek_bartels_spline(points, tension=0, continuity=0, bias=0)
# v = spline(1.5)  # Get v for u=1.5
