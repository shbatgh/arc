#Cap finder Poisson

import open3d as o3d
import numpy as np

def reconstruct_surface_from_points(points, depth=6, trim_percentile=0.01, visualize=True):
    """
    Reconstruct a smooth surface mesh from sparse 3D points using Poisson reconstruction.
    
    Args:
        points (np.ndarray): Nx3 array of 3D point coordinates.
        depth (int): Octree depth for surface detail. Higher = finer (default 6).
        trim_percentile (float): Fraction of lowest-density vertices to remove (default 0.01).
        visualize (bool): Whether to display the reconstructed mesh (default True).
        
    Returns:
        mesh (open3d.geometry.TriangleMesh): Reconstructed surface mesh.
    """
    if not isinstance(points, np.ndarray) or points.shape[1] != 3:
        raise ValueError("Input must be a Nx3 numpy array of 3D points.")

    # Create PointCloud object
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)

    # Estimate normals
    pcd.estimate_normals(search_param=o3d.geometry.KDTreeSearchParamHybrid(
        radius=0.2, max_nn=30))
    pcd.orient_normals_consistent_tangent_plane(10)

    # Run Poisson surface reconstruction
    print("Reconstructing surface...")
    mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
        pcd, depth=depth)

    # Remove low-density vertices (optional cleaning)
    densities = np.asarray(densities)
    keep = densities > np.quantile(densities, trim_percentile)
    mesh = mesh.select_by_index(np.where(keep)[0])

    if visualize:
        o3d.visualization.draw_geometries([mesh], mesh_show_back_face=True)

    return mesh


def generate_sparse_sphere(n_points=2000):
    points = []
    for _ in range(n_points):
        theta = np.random.uniform(0, 2*np.pi)
        phi = np.random.uniform(0, np.pi)
        r = 1 + np.random.normal(scale=0.1)
        x = r * np.sin(phi) * np.cos(theta)
        y = r * np.sin(phi) * np.sin(theta)
        z = r * np.cos(phi)
        points.append([x, y, z])
    return np.array(points)

points = generate_sparse_sphere()
mesh = reconstruct_surface_from_points(points, depth=6)