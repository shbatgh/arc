##----This should make solid mesh objects from wireframes, which would allow us to find area and volume

import trimesh          # Library to build and analyze 3D meshes
import numpy as np      # For numerical operations

def downsample_outline(outline, num_points):
    """Reduces outline to a fixed number of points by skipping evenly."""
    if len(outline) < num_points:
        raise ValueError("Outline has fewer points than requested.")
    step = len(outline) / num_points
    return [outline[int(i * step) % len(outline)] for i in range(num_points)]

def build_mesh_from_3d_outlines(outlines_3D, num_points=32):
    """
    Build a mesh from 3D outlines (each a list of [x, y, z] points).
    - All outlines should be sorted (no jumps).
    - Each outline will be downsampled to the same number of points.
    - A convex hull is generated from all points.


    outlines_3d = [
    [[x1, y1, z1], [x2, y2, z2], ...],  # Outline 1
    [[x1, y1, z1], [x2, y2, z2], ...],  # Outline 2
    ...
    ]
    Args:
        outlines_3d: list of 3D outlines (each is a list of [x, y, z])
        num_points: number of points to keep per outline
    """
    all_points = []
    for outline in outlines_3D:
        step = len(outline) / num_points
        sampled = [outline[int(i * step) % len(outline)] for i in range(num_points)]
        all_points.extend(sampled)

    all_points = np.array(all_points)
    mesh = trimesh.convex.convex_hull(all_points)
    return mesh


#-------For Matplotlib visualization
def visualize_mesh(mesh):
    """
    Visualize a trimesh object using matplotlib 3D.
    """
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    fig = plt.figure(figsize=(8, 6))
    ax = fig.add_subplot(111, projection='3d')

    # Extract vertices and faces
    vertices = mesh.vertices
    faces = mesh.faces

    # Build 3D polygon collection
    mesh_collection = Poly3DCollection(vertices[faces], alpha=0.7)
    mesh_collection.set_facecolor('lightblue')
    mesh_collection.set_edgecolor('gray')
    ax.add_collection3d(mesh_collection)

    # Set plot limits
    scale = vertices.flatten()
    ax.auto_scale_xyz(scale, scale, scale)
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    ax.set_title("3D Mesh Visualization")

    plt.tight_layout()
    plt.show()

# Visualize the earlier mesh






def build_mesh(outlines_3D, num_points, visualize_true):
    mesh = build_mesh_from_3d_outlines(outlines_3D = outlines_3D, num_points=num_points)
    #volume = mesh.volume                   # Volume in cubic units
    #area = mesh.area                       # Surface area
    #is_closed = mesh.is_watertight         # Check if the mesh is watertight
    #is_consistent = mesh.is_winding_consistent  # Check if face winding is consistent

    # Output results
    #print(f"Volume: {volume:.2f}")
    #print(f"Surface Area: {area:.2f}\n")
    #print(f"Watertight: {is_closed}")
    #print(f"Winding Consistent: {is_consistent}")

    if visualize_true:
        visualize_mesh(mesh)
    
    return(mesh)


# Build mesh and analyze it
