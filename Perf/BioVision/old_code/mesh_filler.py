#----This script is supposed to take a sparse outline and fill in the gaps, making it a nice cell.
import numpy as np
from scipy.interpolate import splprep, splev

def smooth_loop_3D(points, num_interp=40):
    """
    Takes a looped list of sparse 3D points and returns a smoother, denser loop.
    
    Args:
        points: List of [x, y, z] points (must be a loop).
        num_interp: Number of interpolated points to return.

    Returns:
        List of [x, y, z] interpolated points forming a smooth closed loop.
    """
    points = np.array(points)
    if len(points) < 3:
        raise ValueError("Need at least 3 points to form a loop.")

    # Ensure loop closure by appending the first point at the end
    if not np.allclose(points[0], points[-1]):
        points = np.vstack([points, points[0]])

    # Fit a parametric spline through the 3D loop
    tck, _ = splprep(points.T, s=0, per=True)

    # Resample with many more points to get a smooth loop
    u_fine = np.linspace(0, 1, num_interp)
    smooth_coords = splev(u_fine, tck)
    
    return np.vstack(smooth_coords).T.tolist()