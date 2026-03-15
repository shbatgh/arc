"""
New attempt at cap finder

Code inputs:
- xz_outlines: List of 2D numpy arrays representing the XZ plane outlines
- yz_outlines: List of 2D numpy arrays representing the YZ plane outlines

"""

import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import Rbf

def find_min_max_z(outlines, top_or_bottom="top"):
    all_z = []
    for outline in outlines:
        all_z.extend([pt[2] for pt in outline])

    res = max(all_z)
    if top_or_bottom == "bottom":
        res = min(all_z)
    
    return(res)

def unique_points(points):
    """
    Removes duplicate 3D points from a list or array of [x, y, z].
    Returns a NumPy array of unique points.
    """
    points = np.asarray(points)
    # Use np.unique on rows (axis=0)
    unique_pts = np.unique(points, axis=0)
    return unique_pts



def find_cap_outlines(outlines, top_or_bottom="top"):   #Do I need to add uncertainty?
    cap_lvl = find_min_max_z(outlines, top_or_bottom)
    cap_outlines = []
    for outline in outlines:
        for pt in outline:
            if pt[2] == cap_lvl:
                cap_outlines.append(outline)
                break
    return cap_outlines


def four_spline_points(outline, top_or_bottom="top"):
    if top_or_bottom == "top":
        middle = len(outline) // 2
        return([outline[middle-2], outline[middle-1], outline[middle], outline[middle+1]])
    
    if top_or_bottom == "bottom":
        return([outline[-2], outline[-1], outline[0], outline[1]])


def create_tps(points):
    #Creates a thin plate spline (TPS) object from a list of 3D points.
    points = np.asarray(points)
    x, y, z = points[:, 0], points[:, 1], points[:, 2]
    tps = Rbf(x, y, z, function='multiquadric')
    return tps

def visualize_tps(tps, points, grid_size=50):
    """
    Visualizes the TPS surface.
    Args:
        tps (Rbf): Thin plate spline interpolator object.
        points (np.ndarray): Original points used for TPS.
        grid_size (int): Resolution of the grid for visualization.
    """
    points = np.asarray(points, dtype=float)
    print(points[:,2])
    x_min, x_max = points[:, 0].min(), points[:, 0].max()
    y_min, y_max = points[:, 1].min(), points[:, 1].max()
    xi, yi = np.meshgrid(
        np.linspace(x_min, x_max, grid_size),
        np.linspace(y_min, y_max, grid_size)
    )
    zi = tps(xi, yi)
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')
    ax.plot_surface(xi, yi, zi, cmap='viridis', alpha=0.7)
    ax.scatter(points[:, 0], points[:, 1], points[:, 2], color='r', s=20)
    ax.set_xlabel('X')
    ax.set_ylabel('Y')
    ax.set_zlabel('Z')
    plt.show()


def execute(xz_outlines, yz_outlines, top_or_bottom="top"):
    tot_outlines = xz_outlines + yz_outlines
    cap_outlines = find_cap_outlines(tot_outlines, top_or_bottom)

    all_tps_points = []
    for outline in cap_outlines:
        all_tps_points.extend(four_spline_points(outline, top_or_bottom))

    all_tps_points = unique_points(all_tps_points)
    #print(all_tps_points)
    print()
    print(all_tps_points.shape)

    # Create TPS
    tps = create_tps(all_tps_points)

    # Visualize the TPS surface
    visualize_tps(tps, all_tps_points)
    
    return tps