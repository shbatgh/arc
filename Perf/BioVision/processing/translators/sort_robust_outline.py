"""
Robust outline point ordering algorithm.

Given a set of pixels forming a cell outline (possibly thick, possibly
with small gaps), extracts the ordered outer contour using two strategies:

  Primary (contour approach):
    1. Rasterize pixels onto a binary grid
    2. Dilate to close gaps (matching BFS loose neighborhood reach)
    3. Flood-fill from the border to identify the cell interior
    4. Trace the outer boundary via Moore neighborhood tracing
    → Produces pre-ordered points, zero crossings, handles thick outlines.

  Fallback (trace approach):
    Used when the contour approach fails (outline has large gaps where
    flood fill leaks through even after dilation).
    1. Build pixel adjacency graph
    2. Walk with direction preference
    3. Chunked 2-opt to fix crossings
"""

import numpy as np
from collections import deque

# Precomputed dilation offsets matching BFS loose neighborhood (distance <= sqrt(8)).
# Stored as (row_offset, col_offset) for numpy grid indexing.
_DILATION_OFFSETS = []
for _dx in range(-2, 3):
    for _dy in range(-2, 3):
        if _dx == 0 and _dy == 0:
            continue
        if _dx * _dx + _dy * _dy <= 8:
            _DILATION_OFFSETS.append((_dy, _dx))


# ============================================================================
#  PRIMARY: Contour approach (flood fill + Moore trace)
# ============================================================================

def _contour_approach(group):
    """Extract ordered contour via dilation + flood-fill + Moore trace."""
    coords = np.array(group, dtype=np.int32)
    min_x, min_y = int(coords[:, 0].min()), int(coords[:, 1].min())
    max_x, max_y = int(coords[:, 0].max()), int(coords[:, 1].max())

    pad = 4
    w = max_x - min_x + 1 + 2 * pad
    h = max_y - min_y + 1 + 2 * pad
    grid = np.zeros((h, w), dtype=np.uint8)
    grid[coords[:, 1] - min_y + pad, coords[:, 0] - min_x + pad] = 1

    # Dilate to close gaps — same reach as BFS loose neighborhood (sqrt(8))
    dilated = grid.copy()
    for dy, dx in _DILATION_OFFSETS:
        src_y = slice(max(0, -dy), h - max(0, dy))
        src_x = slice(max(0, -dx), w - max(0, dx))
        dst_y = slice(max(0, dy), h - max(0, -dy))
        dst_x = slice(max(0, dx), w - max(0, -dx))
        dilated[dst_y, dst_x] |= grid[src_y, src_x]

    # 4-connected flood fill from border on dilated grid
    outside = np.zeros((h, w), dtype=bool)
    q = deque()
    for y in range(h):
        if not dilated[y, 0]:
            outside[y, 0] = True
            q.append((y, 0))
        if not dilated[y, w - 1]:
            outside[y, w - 1] = True
            q.append((y, w - 1))
    for x in range(1, w - 1):
        if not dilated[0, x]:
            outside[0, x] = True
            q.append((0, x))
        if not dilated[h - 1, x]:
            outside[h - 1, x] = True
            q.append((h - 1, x))

    while q:
        cy, cx = q.popleft()
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny, nx = cy + dy, cx + dx
            if 0 <= ny < h and 0 <= nx < w and not outside[ny, nx] and not dilated[ny, nx]:
                outside[ny, nx] = True
                q.append((ny, nx))

    filled = (~outside).astype(np.uint8)

    # Erode back by the same kernel to undo the dilation expansion.
    # Erosion = a pixel survives only if ALL neighbors in the kernel are filled.
    eroded = filled.copy()
    for dy, dx in _DILATION_OFFSETS:
        src_y = slice(max(0, -dy), h - max(0, dy))
        src_x = slice(max(0, -dx), w - max(0, dx))
        dst_y = slice(max(0, dy), h - max(0, -dy))
        dst_x = slice(max(0, dx), w - max(0, -dx))
        eroded[dst_y, dst_x] &= filled[src_y, src_x]

    # Use eroded if it still has pixels, otherwise keep filled (tiny cells)
    if np.any(eroded):
        filled = eroded

    # Moore boundary trace
    start = None
    for y in range(h):
        for x in range(w):
            if filled[y, x]:
                start = (y, x)
                break
        if start:
            break

    if start is None:
        return []

    # 8 directions clockwise: E, SE, S, SW, W, NW, N, NE
    dirs = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]
    contour = []
    cy, cx = start
    prev_dir = 4  # west (pixel to left of topmost-leftmost is outside)
    max_iters = 2 * (w + h) + len(group) * 4

    for step in range(max_iters):
        contour.append([cx - pad + min_x, cy - pad + min_y])
        found = False
        for i in range(1, 9):
            d = (prev_dir + i) % 8
            ny, nx = cy + dirs[d][0], cx + dirs[d][1]
            if 0 <= ny < h and 0 <= nx < w and filled[ny, nx]:
                prev_dir = (d + 4) % 8
                cy, cx = ny, nx
                if (cy, cx) == start and step >= 2:
                    return contour
                found = True
                break
        if not found:
            break

    return contour


# ============================================================================
#  FALLBACK: Adjacency trace approach (for outlines with large gaps)
# ============================================================================

def _build_adjacency(group):
    """Build adjacency lists from pixel connectivity, sorted by distance."""
    n = len(group)
    coord_to_idx = {}
    for i, p in enumerate(group):
        coord_to_idx[(p[0], p[1])] = i

    offsets = []
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            if dx == 0 and dy == 0:
                continue
            if dx * dx + dy * dy <= 8:
                offsets.append((dx, dy))

    adj = [[] for _ in range(n)]
    for i, p in enumerate(group):
        x, y = p[0], p[1]
        neighbors = []
        for dx, dy in offsets:
            key = (x + dx, y + dy)
            if key in coord_to_idx:
                j = coord_to_idx[key]
                if j != i:
                    neighbors.append((dx * dx + dy * dy, j, dx, dy))
        neighbors.sort()
        adj[i] = neighbors

    return adj


def _trace_outline(group, adj):
    """Walk along pixel adjacency with direction preference."""
    n = len(group)
    start = min(range(n), key=lambda i: (group[i][0], group[i][1]))
    visited = [False] * n
    order = [start]
    visited[start] = True
    prev_dx, prev_dy = 0.0, 1.0

    for _ in range(n - 1):
        cur = order[-1]
        best = -1
        best_score = float('inf')
        best_dx, best_dy = 0, 0

        for dist_sq, nb, dx, dy in adj[cur]:
            if visited[nb]:
                continue
            prev_len = (prev_dx * prev_dx + prev_dy * prev_dy) ** 0.5
            cur_len = dist_sq ** 0.5
            if prev_len > 0 and cur_len > 0:
                cos_sim = (dx * prev_dx + dy * prev_dy) / (cur_len * prev_len)
            else:
                cos_sim = 0
            score = dist_sq + (1.0 - cos_sim) * 2.0
            if score < best_score:
                best_score = score
                best = nb
                best_dx, best_dy = dx, dy

        if best == -1:
            cx, cy = group[cur][0], group[cur][1]
            best_dist = float('inf')
            for j in range(n):
                if not visited[j]:
                    dx = group[j][0] - cx
                    dy = group[j][1] - cy
                    d = dx * dx + dy * dy
                    if d < best_dist:
                        best_dist = d
                        best = j
                        best_dx, best_dy = dx, dy

        prev_dx, prev_dy = float(best_dx), float(best_dy)
        order.append(best)
        visited[best] = True

    return order


def _fix_crossings(points, order):
    """Fix edge crossings using chunked vectorized 2-opt."""
    CHUNK = 64
    n = len(order)
    pts = np.array([points[order[k]] for k in range(n)], dtype=np.float64)
    pts_next = np.roll(pts, -1, axis=0)
    j_all = np.arange(n)

    improved = True
    while improved:
        improved = False
        for cs in range(0, n - 1, CHUNK):
            ce = min(cs + CHUNK, n - 1)
            Ax = pts[cs:ce, 0:1]
            Ay = pts[cs:ce, 1:2]
            Bx = pts_next[cs:ce, 0:1]
            By = pts_next[cs:ce, 1:2]
            Cx = pts[:, 0]
            Cy = pts[:, 1]
            Dx = pts_next[:, 0]
            Dy = pts_next[:, 1]
            ccw1 = (Dy - Ay) * (Cx - Ax) > (Cy - Ay) * (Dx - Ax)
            ccw2 = (Dy - By) * (Cx - Bx) > (Cy - By) * (Dx - Bx)
            ccw3 = (Cy - Ay) * (Bx - Ax) > (By - Ay) * (Cx - Ax)
            ccw4 = (Dy - Ay) * (Bx - Ax) > (By - Ay) * (Dx - Ax)
            crossings = (ccw1 != ccw2) & (ccw3 != ccw4)
            i_abs = np.arange(cs, ce)[:, None]
            crossings &= (j_all > i_abs + 1)
            if cs == 0:
                crossings[0, n - 1] = False
            if np.any(crossings):
                flat = int(np.argmax(crossings))
                k, j = divmod(flat, n)
                i = cs + k
                order[i + 1:j + 1] = order[i + 1:j + 1][::-1]
                pts[i + 1:j + 1] = pts[i + 1:j + 1][::-1]
                pts_next = np.roll(pts, -1, axis=0)
                improved = True
                break

    return order


# ============================================================================
#  PUBLIC API
# ============================================================================

def sort_group(group):
    """Extract ordered contour from outline pixels.

    Primary: flood-fill + Moore trace (handles thick outlines, no crossings).
    Fallback: adjacency trace + 2-opt (handles large gaps in outline).
    """
    if len(group) <= 3:
        return list(group)

    import time
    t0 = time.time()

    contour = _contour_approach(group)

    # Validate: contour should span the component's full extent.
    # If flood fill leaked through gaps, the contour only covers a fragment.
    if len(contour) >= 4:
        c = np.array(contour)
        g = np.array(group)
        c_span = (c[:, 0].max() - c[:, 0].min()) + (c[:, 1].max() - c[:, 1].min())
        g_span = (g[:, 0].max() - g[:, 0].min()) + (g[:, 1].max() - g[:, 1].min())

        if g_span == 0 or c_span >= g_span * 0.7:
            t1 = time.time()
            if t1 - t0 > 0.3:
                print(f"      [SORT DETAIL] {len(group)} pts -> "
                      f"{len(contour)} contour: {t1-t0:.3f}s")
            return contour

    # Fallback: trace approach for outlines with large gaps
    adj = _build_adjacency(group)
    order = _trace_outline(group, adj)
    order = _fix_crossings(group, order)

    t1 = time.time()
    if t1 - t0 > 0.3:
        print(f"      [SORT DETAIL] {len(group)} pts, trace fallback: {t1-t0:.3f}s")
    return [group[i] for i in order]
