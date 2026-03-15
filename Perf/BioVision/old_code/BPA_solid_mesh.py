import open3d as o3d           # Library for 3D geometry processing
import numpy as np             # Library for numerical operations
import trimesh                 # Library for working with triangular meshes

def ball_pivoting_trimesh(points, radii):
    """
    Construct a watertight mesh from a 3D surface point cloud using the Ball Pivoting Algorithm (BPA),
    then convert it to a trimesh.Trimesh object.

    Args:
        points (list or np.ndarray): List or array of shape (N, 3) containing 3D points.
        radii (list of float): List of ball radii to try in BPA. These values determine
                               how tightly or loosely the ball "rolls" around point triplets
                               to form triangles. Using multiple radii helps BPA fill in
                               holes at various scales.
                               -> Too small a radius will miss large gaps.
                               -> Too large will incorrectly bridge distinct surfaces.

    Returns:
        trimesh.Trimesh: A triangular mesh reconstructed from the input points.
    """
    # Convert input points to an Open3D PointCloud object
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(np.array(points))  # Ensure it's a NumPy array and assign to pcd



    # Compute average spacing between points (used to scale radii sensibly)
    distances = pcd.compute_nearest_neighbor_distance()
    avg_dist = np.mean(distances)


        # Estimate surface normals for each point — needed by BPA to orient triangles correctly
    pcd.estimate_normals(
        search_param=o3d.geometry.KDTreeSearchParamHybrid(
            radius=avg_dist*10,   # Look for neighbors within this radius (in the same units as your points)
            max_nn=50      # Limit to at most 30 neighbors per point
        )
    )

    # Scale the BPA radii based on average point spacing to match data scale
    scaled_radii = [r * avg_dist for r in radii]

    # Run Ball Pivoting Algorithm with the given radii
    bpa_mesh = o3d.geometry.TriangleMesh.create_from_point_cloud_ball_pivoting(
        pcd,
        o3d.utility.DoubleVector(scaled_radii)  # Convert Python list to Open3D-compatible vector
    )
    
    bpa_mesh.remove_duplicated_triangles()
    bpa_mesh.remove_degenerate_triangles()
    bpa_mesh.remove_non_manifold_edges()
    bpa_mesh.remove_unreferenced_vertices()

    # Attempt to fill holes
    #bpa_mesh = bpa_mesh.fill_holes()
    
    
    # Extract mesh vertex and face arrays from Open3D mesh
    vertices = np.asarray(bpa_mesh.vertices)
    faces = np.asarray(bpa_mesh.triangles)

    # Create and return a trimesh-compatible mesh
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    return mesh