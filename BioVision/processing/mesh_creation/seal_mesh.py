##Takes meshes and makes sure they are watertight
import open3d as o3d
import trimesh
import numpy as np

def make_trimesh_watertight(mesh: trimesh.Trimesh,
                            merge_epsilon: float = 1e-6,
                            verbose: bool = False) -> trimesh.Trimesh:
    mesh = mesh.copy()

    # Basic cleaning
    mesh.remove_degenerate_faces()
    mesh.remove_duplicate_faces()
    mesh.remove_infinite_values()
    mesh.remove_unreferenced_vertices()

    # Merge very close vertices
    mesh.merge_vertices(merge_epsilon)

    # Manually detect boundary edges
    edges_sorted = np.sort(mesh.edges, axis=1)
    edges_unique, edges_count = np.unique(edges_sorted, axis=0, return_counts=True)
    boundary_edges = edges_unique[edges_count == 1]

    if verbose:
        print(f"Initial boundary edges: {len(boundary_edges)}")

    # Fill small holes
    mesh.fill_holes()

    # Recheck for remaining boundaries
    edges_sorted = np.sort(mesh.edges, axis=1)
    edges_unique, edges_count = np.unique(edges_sorted, axis=0, return_counts=True)
    boundary_edges = edges_unique[edges_count == 1]

    if verbose:
        print(f"Remaining boundary edges after fill: {len(boundary_edges)}")

    # Check for non-manifold edges (edges with >2 incident faces)
    non_manifold_edges = edges_unique[edges_count > 2]
    if verbose and len(non_manifold_edges) > 0:
        print(f"Non-manifold edges detected: {len(non_manifold_edges)}")

    # Fix normals and reorient faces consistently
    mesh.fix_normals()


    if not mesh.is_watertight:
        submeshes = mesh.split(only_watertight=False)
        if submeshes:
            mesh = max(submeshes, key=lambda m: m.volume if m.is_volume else len(m.faces))
            
        # Final check
    if verbose:
        print(f"Watertight: {mesh.is_watertight}")
    return mesh



def remove_nonmanifold_edges(mesh: trimesh.Trimesh, verbose: bool = False) -> trimesh.Trimesh:
    mesh = mesh.copy()

    # Sort edges to detect duplicates
    edges_sorted = np.sort(mesh.edges, axis=1)
    edges_unique, edges_count = np.unique(edges_sorted, axis=0, return_counts=True)

    # Find non-manifold edges
    non_manifold_edges = edges_unique[edges_count > 2]

    if verbose:
        print(f"Removing {len(non_manifold_edges)} non-manifold edges...")

    # Mark all faces that touch any non-manifold edge
    face_mask = np.full(len(mesh.faces), True)
    edge_to_face = mesh.face_adjacency_edges
    adjacency = mesh.face_adjacency

    for i, edge in enumerate(mesh.edges):
        if np.any(np.all(non_manifold_edges == np.sort(edge), axis=1)):
            # Remove any face using this edge
            mask = np.any(mesh.faces == edge[0], axis=1) & np.any(mesh.faces == edge[1], axis=1)
            face_mask &= ~mask

    mesh.update_faces(face_mask)
    mesh.remove_unreferenced_vertices()
    
    if verbose:
        print(f"After removing non-manifold, Watertight: {mesh.is_watertight}")

    return mesh


def robust_mesh_repair(mesh, verbose=True):
    def remove_non_manifold_faces(mesh: trimesh.Trimesh, verbose=False) -> trimesh.Trimesh:
        mesh = mesh.copy()

        edges_sorted = np.sort(mesh.edges, axis=1)
        edges_unique, edges_count = np.unique(edges_sorted, axis=0, return_counts=True)
        non_manifold_edges = edges_unique[edges_count > 2]

        if verbose:
            print(f"Non-manifold edges count: {len(non_manifold_edges)}")

        # Find faces that contain any non-manifold edge
        faces_to_remove = set()
        edge_set = set(map(tuple, non_manifold_edges))

        for face_idx, face in enumerate(mesh.faces):
            face_edges = [
                tuple(sorted((face[0], face[1]))),
                tuple(sorted((face[1], face[2]))),
                tuple(sorted((face[2], face[0]))),
            ]
            if any(edge in edge_set for edge in face_edges):
                faces_to_remove.add(face_idx)

        if verbose:
            print(f"Removing {len(faces_to_remove)} faces with non-manifold edges")

        mask = np.ones(len(mesh.faces), dtype=bool)
        mask[list(faces_to_remove)] = False

        mesh.update_faces(mask)
        mesh.remove_unreferenced_vertices()

        return mesh

    def trimesh_to_o3d(mesh):
        o3d_mesh = o3d.geometry.TriangleMesh()
        o3d_mesh.vertices = o3d.utility.Vector3dVector(mesh.vertices)
        o3d_mesh.triangles = o3d.utility.Vector3iVector(mesh.faces)
        o3d_mesh.compute_vertex_normals()
        return o3d_mesh

    def o3d_to_trimesh(o3d_mesh):
        return trimesh.Trimesh(
            vertices=np.asarray(o3d_mesh.vertices),
            faces=np.asarray(o3d_mesh.triangles),
            process=False
        )

    # Step 1: Remove non-manifold faces
    mesh = remove_non_manifold_faces(mesh, verbose=verbose)

    # Step 2: Remove unreferenced vertices
    mesh.remove_unreferenced_vertices()

    # Step 3: Remesh via voxel clustering and midpoint subdivision (Open3D)
    o3d_mesh = trimesh_to_o3d(mesh)
    bbox = o3d_mesh.get_max_bound() - o3d_mesh.get_min_bound()
    voxel_size = 0.01 * np.linalg.norm(bbox)

    try:
        simplified = o3d_mesh.simplify_vertex_clustering(
            voxel_size=voxel_size,
            contraction=o3d.geometry.SimplificationContraction.Average
        )
        remeshed = simplified.subdivide_midpoint(1)
        mesh = o3d_to_trimesh(remeshed)
    except Exception as e:
        if verbose:
            print("Remeshing failed:", e)

    # Final watertight check
    if verbose:
        print("Final watertight:", mesh.is_watertight)

    return mesh


def voxel_repair(mesh, pitch=0.5):
    vox = mesh.voxelized(pitch=pitch)
    repaired = vox.as_boxes()
    return repaired

def keep_largest_component(mesh: trimesh.Trimesh, verbose=False) -> trimesh.Trimesh:
    components = mesh.split(only_watertight=False)
    if not components:
        return mesh
    largest = max(components, key=lambda m: m.volume if m.is_volume else len(m.faces))
    if verbose:
        print(f"Kept largest component: {len(largest.faces)} faces")
    return largest


def seal_mesh(mesh, verbose = False):
    mesh = make_trimesh_watertight(mesh = mesh, verbose = verbose)
    if not mesh.is_watertight:
        mesh = remove_nonmanifold_edges(mesh=mesh, verbose=verbose)
    if not mesh.is_watertight:
        mesh = robust_mesh_repair(mesh=mesh, verbose=verbose)
        mesh = keep_largest_component(mesh, verbose=verbose)
    
    return(mesh)