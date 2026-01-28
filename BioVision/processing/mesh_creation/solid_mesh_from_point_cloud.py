import open3d as o3d
import numpy as np
import trimesh
from sklearn.neighbors import NearestNeighbors

import seal_mesh

def filter_isolated_points(points, quantile=0.995, k=3):
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




def wrap_blanket_over_point_cloud(points, depth=9) -> trimesh.Trimesh:
    """
    Uses Poisson reconstruction to generate a watertight surface that wraps over 3D points.
    Input:
        points: (N, 3) numpy array of 3D points
        depth: Poisson tree depth (higher = more detail, slower)
    Output:
        trimesh.Trimesh object representing watertight surface
    """
    points = filter_isolated_points(points).tolist()
    points = np.asarray(points)
    
    # Create Open3D point cloud
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)

    # Estimate normals
    pcd.estimate_normals(search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=6, max_nn=10))
    pcd.orient_normals_consistent_tangent_plane(k=8)

    # Poisson surface reconstruction
    mesh_o3d, _ = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=depth)

    # Crop to original bounding box to remove far-away artifacts
    #bbox = pcd.get_axis_aligned_bounding_box().scale(1.05, pcd.get_center())
    #mesh_o3d = mesh_o3d.crop(bbox)


    # Convert to Trimesh
    vertices = np.asarray(mesh_o3d.vertices)
    faces = np.asarray(mesh_o3d.triangles)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)

    mesh = seal_mesh.seal_mesh(mesh=mesh, verbose = False)

    return mesh
