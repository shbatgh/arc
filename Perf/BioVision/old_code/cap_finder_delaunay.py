import numpy as np
import scipy.spatial
import trimesh
import matplotlib.pyplot as plt

def reconstruct_surface_delaunay(points, alpha=0.2, visualize=True):
    """
    Reconstruct a surface mesh from sparse 3D points using Delaunay triangulation + alpha shapes.
    
    Args:
        points (np.ndarray): Nx3 array of 3D coordinates.
        alpha (float): Alpha shape parameter. Lower = tighter fit. (0.1–0.3 good range)
        visualize (bool): Whether to show the result in a viewer (matplotlib).
        
    Returns:
        mesh (trimesh.Trimesh): Reconstructed mesh.
    """
    if not isinstance(points, np.ndarray) or points.shape[1] != 3:
        raise ValueError("Input must be a Nx3 numpy array of 3D points.")

    # Step 1: Run 3D Delaunay triangulation
    delaunay = scipy.spatial.Delaunay(points)
    tetrahedra = points[delaunay.simplices]

    # Step 2: Use alpha shape to filter triangles that represent the actual surface
    def tet_volume(tet):
        a, b, c, d = tet
        return abs(np.dot(np.cross(b - a, c - a), d - a)) / 6

    faces = set()
    for tet in tetrahedra:
        vol = tet_volume(tet)
        if vol < alpha:  # keep small tets (near surface)
            for i, j, k in [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)]:
                face = tuple(sorted((tuple(tet[i]), tuple(tet[j]), tuple(tet[k]))))
                if face in faces:
                    faces.remove(face)
                else:
                    faces.add(face)

    # Convert face tuples back to indices and build mesh
    face_array = []
    vertex_list = []
    vertex_map = {}

    for face in faces:
        idxs = []
        for vertex in face:
            if vertex not in vertex_map:
                vertex_map[vertex] = len(vertex_list)
                vertex_list.append(vertex)
            idxs.append(vertex_map[vertex])
        face_array.append(idxs)

    vertices = np.array(vertex_list)
    faces = np.array(face_array)

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)

    if visualize:
        mesh.show()

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
mesh = reconstruct_surface_delaunay(points, alpha=0.2, visualize=True)