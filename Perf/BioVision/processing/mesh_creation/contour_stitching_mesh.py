"""Contour stitching mesh creation.

Builds watertight meshes from 2D cell outlines by:
1. Resampling each outline to a uniform point count
2. Stitching adjacent contours with triangle strips
3. Adding domed caps at top and bottom

mesh_from_wireframes (preferred) uses splined wireframe loops to derive
smooth intermediate contours between original slices and curved dome caps.
mesh_from_contours (fallback) uses only the raw outlines with simple caps.
"""

import numpy as np
import trimesh


def _resample_outline(outline, num_points):
    """Resample a closed 2D outline to num_points evenly spaced along its perimeter."""
    pts = np.array(outline, dtype=float)
    pts = np.vstack([pts, pts[0]])

    diffs = np.diff(pts, axis=0)
    seg_lengths = np.sqrt((diffs ** 2).sum(axis=1))
    cum_length = np.concatenate([[0], np.cumsum(seg_lengths)])
    total_length = cum_length[-1]

    if total_length == 0:
        return np.tile(pts[0], (num_points, 1))

    target_lengths = np.linspace(0, total_length, num_points, endpoint=False)

    resampled = np.zeros((num_points, 2))
    for i, t in enumerate(target_lengths):
        idx = np.searchsorted(cum_length, t, side='right') - 1
        idx = min(idx, len(seg_lengths) - 1)
        frac = (t - cum_length[idx]) / seg_lengths[idx] if seg_lengths[idx] > 0 else 0
        resampled[i] = pts[idx] * (1 - frac) + pts[idx + 1] * frac

    return resampled


def _ensure_ccw(outline):
    """Ensure outline has counter-clockwise winding (positive signed area)."""
    pts = np.array(outline, dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    area = np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
    if area < 0:
        return pts[::-1].copy()
    return pts


def _align_start(ref, target):
    """Rotate target's starting index to minimize distance to ref[0]."""
    dists = np.sqrt(((target - ref[0]) ** 2).sum(axis=1))
    best = np.argmin(dists)
    return np.roll(target, -best, axis=0)


def _smooth_contour(contour, iterations=3, factor=0.5):
    """Apply Laplacian smoothing to a closed contour.

    Each point is shifted toward the midpoint of its two neighbours.
    Multiple iterations progressively remove sharp juts while preserving
    overall shape.
    """
    pts = contour.copy()
    for _ in range(iterations):
        prev = np.roll(pts, 1, axis=0)
        nxt = np.roll(pts, -1, axis=0)
        pts = pts + factor * (0.5 * (prev + nxt) - pts)
    return pts


def _slice_wireframes_at_z(all_wireframes, z_target):
    """Find where wireframe loops cross a given Z level.

    Each splined wireframe loop runs vertically through the cell. By finding
    segments that straddle z_target, we linearly interpolate to get boundary
    crossing points in (x, y).

    Returns list of [x, y] crossing points.
    """
    crossings = []
    for loop in all_wireframes:
        if len(loop) < 4:
            continue
        # Loops have first 3 points appended as closure; skip duplicated
        # segments at the end to avoid double-counting crossings.
        n_seg = len(loop) - 3
        for i in range(n_seg):
            z0 = loop[i][2]
            z1 = loop[i + 1][2]
            dz = z1 - z0
            if abs(dz) < 1e-9:
                continue
            # Check if segment straddles z_target (strict crossing)
            if (z0 - z_target) * (z1 - z_target) < 0:
                t = (z_target - z0) / dz
                x = loop[i][0] + t * (loop[i + 1][0] - loop[i][0])
                y = loop[i][1] + t * (loop[i + 1][1] - loop[i][1])
                crossings.append([x, y])
    return crossings


def _crossings_to_contour(crossings, num_points):
    """Convert unordered crossing points into a resampled contour.

    Computes centroid, sorts points by angle from centroid, then resamples
    to num_points evenly spaced along the resulting polygon perimeter.
    """
    pts = np.array(crossings, dtype=float)
    centroid = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - centroid[1], pts[:, 0] - centroid[0])
    order = np.argsort(angles)
    sorted_pts = pts[order]
    return _resample_outline(sorted_pts, num_points)


def mesh_from_wireframes(splined_xz, splined_yz, outlines, starting_slice,
                         z_scale=3/0.198, num_points=96, interp_per_gap=7,
                         num_cap_levels=5, smooth_iters=3):
    """Build a smooth watertight mesh using wireframe data and original outlines.

    At original slice Z levels the high-detail 2D outlines are used directly.
    Between slices, the splined wireframe loops are sliced horizontally to
    derive smooth intermediate contours.  Above and below the slice range,
    progressively smaller contours extracted from the wireframe cap regions
    form rounded dome caps.

    Parameters
    ----------
    splined_xz : list of list of [x,y,z]
        Splined XZ wireframe loops from cell_point_filler.
    splined_yz : list of list of [x,y,z]
        Splined YZ wireframe loops from cell_point_filler.
    outlines : list of list of [x,y]
        Original 2D cell outlines, one per slice.
    starting_slice : int
        Z-index of the first outline.
    z_scale : float
        Z units per slice (default 3/0.198).
    num_points : int
        Resampling resolution per contour ring.
    interp_per_gap : int
        Number of wireframe-derived contours inserted between each pair of
        consecutive original slices.
    num_cap_levels : int
        Number of wireframe-derived contour rings in each dome cap region.

    Returns
    -------
    trimesh.Trimesh or None
    """
    all_wireframes = splined_xz + splined_yz

    if len(all_wireframes) == 0 or len(outlines) < 2:
        return None

    # Determine wireframe Z extent (includes cap dome regions)
    wf_zs = [pt[2] for loop in all_wireframes for pt in loop]
    wf_z_min = min(wf_zs)
    wf_z_max = max(wf_zs)

    num_slices = len(outlines)
    original_zs = [(starting_slice + i) * z_scale for i in range(num_slices)]

    # Pre-compute aligned original contours.  Center each contour before
    # alignment so that positional offset between slices doesn't bias
    # the point correspondence — shape matching and position interpolation
    # are handled independently.
    centroids = []
    original_contours = []  # centered (centroid-subtracted)
    for i in range(num_slices):
        pts = _ensure_ccw(outlines[i])
        contour = _resample_outline(pts, num_points)
        if smooth_iters > 0:
            contour = _smooth_contour(contour, iterations=smooth_iters)
        centroid = contour.mean(axis=0)
        centroids.append(centroid)
        original_contours.append(contour - centroid)
    for i in range(1, num_slices):
        original_contours[i] = _align_start(original_contours[i - 1], original_contours[i])

    # --- Build Z sampling plan: (z_value, source, data) ---
    z_plan = []

    # Bottom cap levels (wireframe dome below the first slice)
    bot_range = original_zs[0] - wf_z_min
    if bot_range > 0:
        for i in range(1, num_cap_levels + 1):
            frac = i / (num_cap_levels + 1)
            z_plan.append((wf_z_min + frac * bot_range, 'wireframe', None))

    # Body: original slices interleaved with blended intermediate levels
    for i in range(num_slices):
        z_plan.append((original_zs[i], 'original', i))
        if i < num_slices - 1:
            gap = original_zs[i + 1] - original_zs[i]
            for j in range(1, interp_per_gap + 1):
                frac = j / (interp_per_gap + 1)
                z_plan.append((original_zs[i] + frac * gap, 'body', (i, i + 1, frac)))

    # Top cap levels (wireframe dome above the last slice)
    top_range = wf_z_max - original_zs[-1]
    if top_range > 0:
        for i in range(1, num_cap_levels + 1):
            frac = i / (num_cap_levels + 1)
            z_plan.append((original_zs[-1] + frac * top_range, 'wireframe', None))

    z_plan.sort(key=lambda x: x[0])

    # --- Build contours at each Z level ---
    contours = []  # list of (z, 2D contour array)
    for z, source, data in z_plan:
        if source == 'original':
            contours.append((z, original_contours[data] + centroids[data]))
        elif source == 'body':
            # Catmull-Rom spline through centered original contours —
            # each point index is independently splined across slices,
            # preserving concavity without wireframe crossing noise.
            # Centroids are interpolated separately so positional offset
            # between slices never distorts the shape correspondence.
            idx_a, idx_b, frac = data
            P1 = original_contours[idx_a]
            P2 = original_contours[idx_b]
            # Duplicate at boundaries (not reflect)
            P0 = original_contours[idx_a - 1] if idx_a > 0 else P1
            P3 = original_contours[idx_b + 1] if idx_b < num_slices - 1 else P2
            t = frac
            t2 = t * t
            t3 = t2 * t
            # Spline the centered shapes
            shape = 0.5 * ((2 * P1) +
                           (-P0 + P2) * t +
                           (2 * P0 - 5 * P1 + 4 * P2 - P3) * t2 +
                           (-P0 + 3 * P1 - 3 * P2 + P3) * t3)
            # Linearly interpolate the centroid position
            center = (1 - t) * centroids[idx_a] + t * centroids[idx_b]
            contours.append((z, shape + center))
        else:  # wireframe (caps)
            crossings = _slice_wireframes_at_z(all_wireframes, z)
            if len(crossings) < 4:
                continue
            contour = _crossings_to_contour(crossings, num_points)
            if smooth_iters > 0:
                contour = _smooth_contour(contour, iterations=smooth_iters)
            contours.append((z, contour))

    if len(contours) < 2:
        return None

    # Align starting points between adjacent contour rings
    for i in range(1, len(contours)):
        contours[i] = (contours[i][0], _align_start(contours[i - 1][1], contours[i][1]))

    # --- Assemble mesh ---
    all_verts = []
    all_faces = []
    n = num_points

    # Ring vertices
    for z, contour in contours:
        for pt in contour:
            all_verts.append([pt[0], pt[1], z])

    # Stitch adjacent rings with triangle strips
    for i in range(len(contours) - 1):
        a = i * n
        b = (i + 1) * n
        for j in range(n):
            nj = (j + 1) % n
            all_faces.append([a + j, b + j, a + nj])
            all_faces.append([a + nj, b + j, b + nj])

    # Bottom cap tip — fan-triangulate from first ring to center vertex
    bot_contour = contours[0][1]
    bot_center = bot_contour.mean(axis=0)
    bot_center_idx = len(all_verts)
    all_verts.append([bot_center[0], bot_center[1], wf_z_min])
    for j in range(n):
        nj = (j + 1) % n
        all_faces.append([j, nj, bot_center_idx])

    # Top cap tip — fan-triangulate from last ring to center vertex
    last_off = (len(contours) - 1) * n
    top_contour = contours[-1][1]
    top_center = top_contour.mean(axis=0)
    top_center_idx = len(all_verts)
    all_verts.append([top_center[0], top_center[1], wf_z_max])
    for j in range(n):
        nj = (j + 1) % n
        all_faces.append([last_off + nj, last_off + j, top_center_idx])

    mesh = trimesh.Trimesh(
        vertices=np.array(all_verts),
        faces=np.array(all_faces),
        process=True
    )
    mesh.fix_normals()
    return mesh


def mesh_from_contours(outlines, starting_slice, num_points=64, z_scale=3/0.198,
                       smooth_iters=5):
    """
    Build a watertight mesh from stacked 2D cell outlines.

    Parameters:
        outlines: list of outlines, each a list of [x, y] points
        starting_slice: Z-index of the first outline
        num_points: resampling resolution per contour
        z_scale: Z units per slice
    Returns:
        trimesh.Trimesh or None
    """
    if len(outlines) < 2:
        return None

    # Resample, enforce consistent winding, smooth, and align
    resampled = []
    for o in outlines:
        pts = _ensure_ccw(o)
        contour = _resample_outline(pts, num_points)
        if smooth_iters > 0:
            contour = _smooth_contour(contour, iterations=smooth_iters)
        resampled.append(contour)

    for i in range(1, len(resampled)):
        resampled[i] = _align_start(resampled[i - 1], resampled[i])

    all_verts = []
    all_faces = []
    n = num_points

    # --- Contour ring vertices ---
    for i, contour in enumerate(resampled):
        z = (starting_slice + i) * z_scale
        for pt in contour:
            all_verts.append([pt[0], pt[1], z])

    # --- Stitch adjacent rings ---
    for i in range(len(resampled) - 1):
        a = i * n
        b = (i + 1) * n
        for j in range(n):
            nj = (j + 1) % n
            all_faces.append([a + j, b + j, a + nj])
            all_faces.append([a + nj, b + j, b + nj])

    # --- Dome caps ---
    dome_height = z_scale

    # Bottom dome
    bot_contour = resampled[0]
    bot_center = bot_contour.mean(axis=0)
    bot_z = starting_slice * z_scale

    # Intermediate ring at 50% scale
    bot_ring_off = len(all_verts)
    for j in range(n):
        xy = bot_center + 0.5 * (bot_contour[j] - bot_center)
        all_verts.append([xy[0], xy[1], bot_z - 0.5 * dome_height])

    for j in range(n):
        nj = (j + 1) % n
        all_faces.append([j, nj, bot_ring_off + j])
        all_faces.append([nj, bot_ring_off + nj, bot_ring_off + j])

    # Bottom center vertex
    bot_center_idx = len(all_verts)
    all_verts.append([bot_center[0], bot_center[1], bot_z - dome_height])

    for j in range(n):
        nj = (j + 1) % n
        all_faces.append([bot_ring_off + j, bot_ring_off + nj, bot_center_idx])

    # Top dome
    top_contour = resampled[-1]
    top_center = top_contour.mean(axis=0)
    top_z = (starting_slice + len(resampled) - 1) * z_scale
    top_off = (len(resampled) - 1) * n

    # Intermediate ring at 50% scale
    top_ring_off = len(all_verts)
    for j in range(n):
        xy = top_center + 0.5 * (top_contour[j] - top_center)
        all_verts.append([xy[0], xy[1], top_z + 0.5 * dome_height])

    for j in range(n):
        nj = (j + 1) % n
        all_faces.append([top_off + nj, top_off + j, top_ring_off + j])
        all_faces.append([top_off + nj, top_ring_off + j, top_ring_off + nj])

    # Top center vertex
    top_center_idx = len(all_verts)
    all_verts.append([top_center[0], top_center[1], top_z + dome_height])

    for j in range(n):
        nj = (j + 1) % n
        all_faces.append([top_ring_off + j, top_center_idx, top_ring_off + nj])

    mesh = trimesh.Trimesh(
        vertices=np.array(all_verts),
        faces=np.array(all_faces),
        process=True
    )
    mesh.fix_normals()

    return mesh
