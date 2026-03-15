##----This should make solid mesh objects from wireframes, which would allow us to find area and volume

import trimesh          # Library to build and analyze 3D meshes
import numpy as np      # For numerical operations

def downsample_outline(outline, num_points):
    """Reduces outline to a fixed number of points by skipping evenly."""
    if len(outline) < num_points:
        raise ValueError("Outline has fewer points than requested.")
    step = len(outline) / num_points
    return [outline[int(i * step) % len(outline)] for i in range(num_points)]

def build_mesh_from_slices(slices, num_points=32, z_spacing=3/0.198 * 0.5):
    """
    Converts stacked 2D outlines into a 3D mesh.
    slices: list of outlines (each is a list of [x, y] points)
    """
    vertices = []    # All vertices of the mesh
    faces = []       # All triangular faces
    n_slices = len(slices)

    # Go through each outline slice
    for i, outline in enumerate(slices):
        downsampled = downsample_outline(outline, num_points)
        z = i * z_spacing     # Z-position for this slice
        for x, y in downsampled:
            vertices.append([x, y, z])   # Add 3D vertex

    vertices = np.array(vertices)   # Convert to NumPy array

    # Build faces between slices (quads split into two triangles)
    for i in range(n_slices - 1):
        for j in range(num_points):
            a = i * num_points + j
            b = i * num_points + (j + 1) % num_points
            c = (i + 1) * num_points + (j + 1) % num_points
            d = (i + 1) * num_points + j
            faces.append([a, b, c])  # First triangle
            faces.append([a, c, d])  # Second triangle

    # Add caps to close the top and bottom of the mesh
    def cap(start_idx, reverse=False):
        nonlocal vertices
        center = np.mean(vertices[start_idx:start_idx+num_points], axis=0)  # Average center
        center_idx = len(vertices)  # New vertex index
        vertices = np.vstack([vertices, center])  # Add center point to vertices

        # Create triangle fan around the center
        for i in range(num_points):
            a = start_idx + i
            b = start_idx + (i + 1) % num_points
            if reverse:
                faces.append([a, b, center_idx])  # Bottom cap (inward normal)
            else:
                faces.append([b, a, center_idx])  # Top cap (outward normal)
        return vertices

    vertices = cap(0, reverse=True)  # Bottom cap (first slice)
    vertices = cap((n_slices - 1) * num_points, reverse=False)  # Top cap

    # Build and return Trimesh object
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    return mesh




#-------For Matplotlib visualization
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

def visualize_mesh(mesh):
    """
    Visualize a trimesh object using matplotlib 3D.
    """
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






def build_mesh(slices, visualize_true):
    mesh = build_mesh_from_slices(slices)
    volume = mesh.volume                   # Volume in cubic units
    area = mesh.area                       # Surface area
    is_closed = mesh.is_watertight         # Check if the mesh is watertight
    is_consistent = mesh.is_winding_consistent  # Check if face winding is consistent

    # Output results
    print(f"Volume: {volume:.2f}")
    print(f"Surface Area: {area:.2f}")
    print(f"Watertight: {is_closed}")
    print(f"Winding Consistent: {is_consistent}")

    if visualize_true:
        visualize_mesh(mesh)
    
    return(mesh)


# Build mesh and analyze it
