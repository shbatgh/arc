"""
Kochanek-Bartels Spline (Safe)

Non-uniform Kochanek-Bartels spline interpolation with chord-length
parameterization. Used by cap_finder_own_approach.py to estimate Z values
at wireframe intersection points.

The Kochanek-Bartels spline generalizes Catmull-Rom with three parameters:
  - Tension:    Controls curve tightness (negative = rounder).
  - Continuity: Controls smoothness at control points (0 = smooth).
  - Bias:       Controls asymmetry toward previous/next point (0 = symmetric).
"""

import numpy as np
from scipy.interpolate import CubicHermiteSpline


def chord_lengths(P0, P1, P2, P3):
    """Compute cumulative chord lengths between 4 control points.

    Used for non-uniform parameterization so that unevenly spaced
    control points are handled correctly.
    """
    P = [np.array(P0), np.array(P1), np.array(P2), np.array(P3)]
    ts = [0]
    for i in range(1, 4):
        ts.append(ts[-1] + np.linalg.norm(P[i] - P[i - 1]))
    return ts


def kochanek_bartels_spline_nonuniform(P0, P1, P2, P3,
                                        tension=0.0, continuity=0.0, bias=0.0,
                                        num_points=1000):
    """Evaluate a Kochanek-Bartels spline between P1 and P2.

    Args:
        P0, P1, P2, P3: 2D control points [u, v].
        tension:         Spline tension parameter.
        continuity:      Spline continuity parameter.
        bias:            Spline bias parameter.
        num_points:      Number of sample points to generate.

    Returns:
        (u_vals, v_vals) arrays of the spline evaluated at num_points positions.
    """
    P0, P1, P2, P3 = map(np.array, [P0, P1, P2, P3])
    ts = chord_lengths(P0, P1, P2, P3)
    t0, t1, t2, t3 = ts

    # Degenerate case: P1 and P2 are the same point
    if np.isclose(t2, t1):
        return np.full(num_points, P1[0]), np.full(num_points, P1[1])

    def compute_tangent(P_prev, P_curr, P_next, t_prev, t_curr, t_next,
                        T, C, B, outgoing=True):
        dt1 = t_curr - t_prev
        dt2 = t_next - t_curr
        d1 = (P_curr - P_prev) / dt1 if dt1 != 0 else np.zeros(2)
        d2 = (P_next - P_curr) / dt2 if dt2 != 0 else np.zeros(2)

        if outgoing:
            return ((1 - T) * (1 + C) * (1 + B) / 2 * d1 +
                    (1 - T) * (1 - C) * (1 - B) / 2 * d2)
        else:
            return ((1 - T) * (1 - C) * (1 + B) / 2 * d1 +
                    (1 - T) * (1 + C) * (1 - B) / 2 * d2)

    T1 = compute_tangent(P0, P1, P2, t0, t1, t2, tension, continuity, bias, outgoing=True)
    T2 = compute_tangent(P1, P2, P3, t1, t2, t3, tension, continuity, bias, outgoing=False)

    t = np.linspace(t1, t2, num_points)
    u_spline = CubicHermiteSpline([t1, t2], [P1[0], P2[0]], [T1[0], T2[0]])
    v_spline = CubicHermiteSpline([t1, t2], [P1[1], P2[1]], [T1[1], T2[1]])

    return u_spline(t), v_spline(t)


def v_for_u_nonuniform(target_u, P0, P1, P2, P3,
                        tension=0.0, continuity=0.0, bias=0.0, tol=1e-0):
    """Find the V values where the spline's U coordinate equals target_u.

    Evaluates the full spline and returns all V values where U is within
    tol of target_u. Used by cap_finder to find Z at a given X or Y.
    """
    u_vals, v_vals = kochanek_bartels_spline_nonuniform(
        P0, P1, P2, P3, tension, continuity, bias,
    )
    matches = np.abs(u_vals - target_u) < tol
    return v_vals[matches].tolist()
