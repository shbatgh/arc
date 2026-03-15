import numpy as np
import trimesh
import pyvista as pv


import numpy as np
from sklearn.neighbors import NearestNeighbors

def filter_isolated_points(points, quantile=0.95, k=5):
    """
    Removes the top `quantile` of most isolated points from a point cloud.

    Parameters:
        points (ndarray): (N, 3) array of 3D points
        quantile (float): Between 0 and 1. Fraction of isolated points to remove.
                          E.g., 0.95 removes the top 5% most isolated points.
        k (int): Number of neighbors to consider for distance

    Returns:
        filtered_points (ndarray): Points after removing isolated ones
    """
    points = np.asarray(points)
    nbrs = NearestNeighbors(n_neighbors=k+1).fit(points)
    dists, _ = nbrs.kneighbors(points)
    
    # Ignore the first distance (distance to self = 0)
    avg_dists = np.mean(dists[:, 1:], axis=1)

    # Keep points below the isolation threshold
    threshold = np.quantile(avg_dists, quantile)
    keep_mask = avg_dists <= threshold

    return points[keep_mask]


def points_to_watertight_trimesh(points_list, alpha=6.1, quantile = 0.99, k = 3):
    """
    Converts 3D surface points into a concave-preserving, watertight trimesh mesh
    using alpha shapes (via pyvista/vtk).

    Parameters:
        points_list (list of lists or (N, 3) ndarray): 3D surface points
        alpha (float): Controls detail vs. smoothness. Lower = more concave preserved.

    Returns:
        mesh (trimesh.Trimesh): Watertight mesh with concavities preserved
    """
    # Convert points to pyvista PolyData
    
    filtered = filter_isolated_points(points=points_list, quantile=quantile, k=k)
    filtered.tolist()
    
    cloud = pv.PolyData(np.array(filtered))

    # Compute alpha shape surface
    surf = cloud.delaunay_3d(alpha=alpha)
    shell = surf.extract_geometry().extract_surface().clean()

    # Get vertices and faces
    vertices = np.array(shell.points)
    faces = shell.faces.reshape((-1, 4))[:, 1:4]  # Remove face size prefix

    # Build trimesh
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)

    if not mesh.is_watertight:
        mesh.fill_holes()
    return mesh