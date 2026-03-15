import numpy as np
from skimage.draw import polygon
from skimage.measure import marching_cubes
import trimesh

import numpy as np
import trimesh
from scipy.interpolate import splprep, splev
from shapely.geometry import Polygon

def resample_outline(outline, num_points):
    outline = np.array(outline)
    # Ensure closed
    if not np.allclose(outline[0], outline[-1]):
        outline = np.vstack([outline, outline[0]])
    tck, u = splprep([outline[:,0], outline[:,1]], s=0, per=True)
    u_new = np.linspace(0, 1, num_points)
    x_new, y_new = splev(u_new, tck)
    return np.vstack([x_new, y_new]).T

def build_concave_mesh_from_outlines(outlines, z_spacing, num_interp=10, num_points=100, slice_start=0):
    # Resample all outlines to the same number of points
    outlines_rs = [resample_outline(outline, num_points) for outline in outlines]
    zs = (np.arange(len(outlines)) + slice_start) * z_spacing

    # Interpolate intermediate slices for smoothness
    outlines_stack = np.stack(outlines_rs)  # shape: (num_slices, num_points, 2)
    interp_zs = np.linspace(zs[0], zs[-1], num=len(outlines)*num_interp)
    interp_outlines = []
    for i in range(num_points):
        x = np.interp(interp_zs, zs, outlines_stack[:,i,0])
        y = np.interp(interp_zs, zs, outlines_stack[:,i,1])
        interp_outlines.append(np.vstack([x, y]).T)
    interp_outlines = np.stack(interp_outlines, axis=1)  # (num_interp_slices, num_points, 2)

    # Build vertices
    vertices = []
    for z_idx, z in enumerate(interp_zs):
        for pt in interp_outlines[z_idx]:
            vertices.append([pt[0], pt[1], z])
    vertices = np.array(vertices)

    # Build faces between slices
    faces = []
    n_slices = len(interp_zs)
    for i in range(n_slices-1):
        for j in range(num_points):
            a = i*num_points + j
            b = i*num_points + (j+1)%num_points
            c = (i+1)*num_points + (j+1)%num_points
            d = (i+1)*num_points + j
            faces.append([a, b, d])
            faces.append([b, c, d])

    # Cap bottom
    bottom = vertices[:num_points, :2]
    poly = Polygon(bottom)
    if poly.is_valid and poly.area > 0:
        cap_vertices, cap_faces = trimesh.creation.triangulate_polygon(poly)
        # The cap vertices are local to the cap, so you need to index them relative to the main mesh
        # For bottom cap, the first num_points vertices are already in the mesh
        for f in cap_faces:
            faces.append([f[0], f[1], f[2]])
    # Cap top
    top = vertices[-num_points:, :2]
    poly = Polygon(top)
    if poly.is_valid and poly.area > 0:
        cap_vertices, cap_faces = trimesh.creation.triangulate_polygon(poly)
        offset = len(vertices) - num_points
        for f in cap_faces:
            faces.append([offset+f[0], offset+f[1], offset+f[2]])

    return trimesh.Trimesh(vertices=vertices, faces=faces)