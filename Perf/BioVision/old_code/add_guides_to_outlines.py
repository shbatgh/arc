#Input: outlines and guide points, and it adds the guide points to the correct outlines
import numpy as np
from typing import List

def add_guides_to_outlines(xz_outlines: List[np.ndarray], yz_outlines: List[np.ndarray], guide_points: np.ndarray, tol=1e-6):
    """
    Adds each guide point to the closest outline in XZ and YZ (by XY position).
    Each guide point is added to one XZ and one YZ outline.
    Returns new lists of outlines with guide points inserted.
    """
    xz_outlines_new = [outline.copy() for outline in xz_outlines]
    yz_outlines_new = [outline.copy() for outline in yz_outlines]

    for guide in guide_points:
        x, y, z = guide

        # Find closest XZ outline by x (and z)
        xz_idx = np.argmin([np.min(np.linalg.norm(outline[:, [0,2]] - np.array([x,z]), axis=1)) for outline in xz_outlines_new])
        # Find closest YZ outline by y (and z)
        yz_idx = np.argmin([np.min(np.linalg.norm(outline[:, [1,2]] - np.array([y,z]), axis=1)) for outline in yz_outlines_new])

        # Insert guide point into XZ outline at correct position (closest by x)
        xz_outline = xz_outlines_new[xz_idx]
        dists = np.linalg.norm(xz_outline[:, [0,2]] - np.array([x,z]), axis=1)
        insert_pos = np.argmin(dists)
        xz_outlines_new[xz_idx] = np.insert(xz_outline, insert_pos, np.array([x, y, z]), axis=0)

        # Insert guide point into YZ outline at correct position (closest by y)
        yz_outline = yz_outlines_new[yz_idx]
        dists = np.linalg.norm(yz_outline[:, [1,2]] - np.array([y,z]), axis=1)
        insert_pos = np.argmin(dists)
        yz_outlines_new[yz_idx] = np.insert(yz_outline, insert_pos, np.array([x, y, z]), axis=0)

    return xz_outlines_new, yz_outlines_new

# Example usage:
# xz_outlines_new, yz_outlines_new = add_guides_to_outlines(xz_outlines,