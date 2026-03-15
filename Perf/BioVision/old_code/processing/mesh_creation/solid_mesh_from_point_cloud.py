import open3d as o3d
import numpy as np
import trimesh
from sklearn.neighbors import NearestNeighbors

from . import seal_mesh

def filter_isolated_points(points, quantile=0.995, k=3, small_cell_quantile = 0.999, small_cell_threshold = 2000):
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
    points = np.asarray(points)
    original_count = len(points)
    points = np.unique(points, axis=0)

    if len(points) < small_cell_threshold:
        quantile = small_cell_quantile

    print("Number of Unique Points: ", len(points), "        Originally ", original_count, end = "      ")
    nbrs = NearestNeighbors(n_neighbors=k+1).fit(points)
    dists, _ = nbrs.kneighbors(points)
    
    # Ignore the first distance (distance to self = 0)
    avg_dists = np.mean(dists[:, 1:], axis=1)

    # Keep points below the isolation threshold
    threshold = np.quantile(avg_dists, quantile)
    keep_mask = avg_dists <= threshold

    print("Fin: ", len(points[keep_mask]))

    return points[keep_mask]




def wrap_blanket_over_point_cloud(points, depth=9) -> trimesh.Trimesh:
    """
    Uses Poisson reconstruction to generate a watertight surface that wraps over 3D points.
    Z is temporarily halved during reconstruction to counteract anisotropic slice
    spacing (slices ~15px apart vs ~1px in XY), then scaled back on the output mesh.
    Input:
        points: (N, 3) numpy array of 3D points
        depth: Poisson tree depth (higher = more detail, slower)
    Output:
        trimesh.Trimesh object representing watertight surface
    """
    points = filter_isolated_points(points)
    num_points = len(points)

    # Halve Z for reconstruction — this matches the proven geometry that
    # produces smooth, closed meshes. The raw Z spacing (3/0.198 per slice)
    # is too large relative to XY for good normal estimation.
    recon_points = points.copy()
    recon_points[:, 2] *= 0.5

    # Create Open3D point cloud
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(recon_points)

    # Scale normal estimation parameters with point count
    if num_points > 5000:
        radius, max_nn, orient_k = 8, 15, 12
    elif num_points > 2000:
        radius, max_nn, orient_k = 7, 12, 10
    else:
        radius, max_nn, orient_k = 6, 10, 8

    # Estimate normals
    pcd.estimate_normals(search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=radius, max_nn=max_nn))
    pcd.orient_normals_consistent_tangent_plane(k=orient_k)

    # Poisson surface reconstruction
    mesh_o3d, _ = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=depth)

    # Scale Z back to correct physical coordinates
    vertices = np.asarray(mesh_o3d.vertices)
    vertices[:, 2] /= 0.5

    faces = np.asarray(mesh_o3d.triangles)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)

    mesh = seal_mesh.seal_mesh(mesh=mesh, verbose = False)

    return mesh
