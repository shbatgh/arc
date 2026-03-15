import numpy as np
from scipy.interpolate import CubicHermiteSpline


def chord_lengths(P0, P1, P2, P3):
    P = [np.array(P0), np.array(P1), np.array(P2), np.array(P3)]
    ts = [0]
    for i in range(1, 4):
        ts.append(ts[-1] + np.linalg.norm(P[i] - P[i - 1]))
    return ts

def kochanek_bartels_spline_nonuniform(P0, P1, P2, P3, tension=0.0, continuity=0.0, bias=0.0, num_points=1000):
    P0, P1, P2, P3 = map(np.array, [P0, P1, P2, P3])
    ts = chord_lengths(P0, P1, P2, P3)
    t0, t1, t2, t3 = ts

    # Tangents with real spacing
    def compute_tangent(P_prev, P_curr, P_next, t_prev, t_curr, t_next, T, C, B, outgoing=True):
        dt1 = t_curr - t_prev
        dt2 = t_next - t_curr
        d1 = (P_curr - P_prev) / dt1
        d2 = (P_next - P_curr) / dt2

        if outgoing:
            return (1 - T) * (1 + C) * (1 + B) / 2 * d1 + \
                   (1 - T) * (1 - C) * (1 - B) / 2 * d2
        else:
            return (1 - T) * (1 - C) * (1 + B) / 2 * d1 + \
                   (1 - T) * (1 + C) * (1 - B) / 2 * d2

    T1 = compute_tangent(P0, P1, P2, t0, t1, t2, tension, continuity, bias, outgoing=True)
    T2 = compute_tangent(P1, P2, P3, t1, t2, t3, tension, continuity, bias, outgoing=False)

    # Hermite spline in [t1, t2]
    t = np.linspace(t1, t2, num_points)

    u_spline = CubicHermiteSpline([t1, t2], [P1[0], P2[0]], [T1[0], T2[0]])
    v_spline = CubicHermiteSpline([t1, t2], [P1[1], P2[1]], [T1[1], T2[1]])

    u_vals = u_spline(t)
    v_vals = v_spline(t)
    return u_vals, v_vals





def v_for_u_nonuniform(target_u, P0, P1, P2, P3, tension=0.0, continuity=0.0, bias=0.0, tol=1e-1):
    u_vals, v_vals = kochanek_bartels_spline_nonuniform(P0, P1, P2, P3, tension, continuity, bias)
    matches = np.abs(u_vals - target_u) < tol
    return v_vals[matches].tolist()