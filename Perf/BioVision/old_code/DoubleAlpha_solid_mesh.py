import numpy as np
import trimesh
import pyvista as pv


import numpy as np
from sklearn.neighbors import NearestNeighbors

def filter_isolated_points(points, quantile=0.95, k=5):
    """
    Removes the top `quantile` of most isolated points from a point cloud. ALSO REMOVES REPEATS

    Parameters:
        points (ndarray): (N, 3) array of 3D points
        quantile (float): Between 0 and 1. Fraction of isolated points to remove.
                          E.g., 0.95 removes the top 5% most isolated points.
        k (int): Number of neighbors to consider for distance

    Returns:
        filtered_points (ndarray): Points after removing isolated ones
    """
    
    #Removes repeats
    unique_points = []
    for p in points:
        if p not in unique_points:
            unique_points.append(p)
    
    points = np.asarray(unique_points)
    nbrs = NearestNeighbors(n_neighbors=k+1).fit(points)
    dists, _ = nbrs.kneighbors(points)
    
    # Ignore the first distance (distance to self = 0)
    avg_dists = np.mean(dists[:, 1:], axis=1)

    # Keep points below the isolation threshold
    threshold = np.quantile(avg_dists, quantile)
    keep_mask = avg_dists <= threshold

    return points[keep_mask]




def alpha_shape_mesh(points, alpha):
    cloud = pv.PolyData(np.array(points))
    surf = cloud.delaunay_3d(alpha=alpha)
    shell = surf.extract_geometry().extract_surface().clean()
    return shell



def multi_alpha_preserving_concavity(points, alpha_fine=4, alpha_coarse=7, quantile = 0.990, k = 3):    #Add another intermediate alpha value and another after. Increase points per segment maybe
    
    filtered = filter_isolated_points(points=points, quantile=quantile, k=k)
    points = filtered.tolist()
    
    mesh_fine = alpha_shape_mesh(points, alpha_fine)
    mesh_coarse = alpha_shape_mesh(points, alpha_coarse)

    # Convert both to trimesh
    print("Fine Trimesh...", end = " ")
    fine_tri = trimesh.Trimesh(vertices=np.array(mesh_fine.points),
                               faces=mesh_fine.faces.reshape((-1, 4))[:, 1:4],
                               process=True)

    print("Coarse Trimesh...", end = " ")
    coarse_tri = trimesh.Trimesh(vertices=np.array(mesh_coarse.points),
                                 faces=mesh_coarse.faces.reshape((-1, 4))[:, 1:4],
                                 process=True)

    # Step 1: Identify vertices in coarse mesh that are NOT inside fine mesh
    print("Filtering...", end="")
    mask = ~fine_tri.contains(coarse_tri.vertices)

    print("Filtering...", end="")
    # Step 2: Keep only faces whose all 3 vertices are outside fine mesh
    keep_faces = [face for face in coarse_tri.faces if all(mask[vid] for vid in face)]
    print("Filtering...", end="")
    patch_tri = trimesh.Trimesh(vertices=coarse_tri.vertices, faces=keep_faces, process=True)

    # Step 3: Merge the fine mesh with the patch
    print("Combining...")
    combined = trimesh.util.concatenate([fine_tri, patch_tri]).process(validate=True)

    # Final watertight cleanup
    if not combined.is_watertight:
        combined.fill_holes()

    return combined
