"""
Adjustment Algorithm

Translates and rotates 2D outline points to correct for specimen drift
and rotation between timepoints.

Called by v10manual_segmentation_formatter.py and
v10manual_segmentation_formatter_SVG.py.
"""

import math


def adjust_group(group, reference_point, rotation_point, should_rotate):
    """Translate an outline to the reference point origin, then optionally rotate.

    Steps:
      1. Subtract the reference point from every coordinate (centers the specimen).
      2. If should_rotate is True, compute the angle to the rotation point and
         apply a 2D rotation matrix to align the specimen consistently.
      3. If the rotation point is to the left of the reference point, flip both
         axes to maintain correct orientation.

    Args:
        group:           List of [x, y] outline coordinates.
        reference_point: [x, y] position of the reference marker.
        rotation_point:  [x, y] position of the rotation marker.
        should_rotate:   Whether to apply rotation correction.

    Returns:
        Adjusted list of [x, y] coordinates with the loop closed (first two
        points appended at the end).
    """
    ox, oy = reference_point[0], reference_point[1]

    # Translation only
    if not should_rotate:
        return [[coord[0] - ox, coord[1] - oy] for coord in group]

    # Compute rotation angle from the reference-to-rotation vector
    angle = -math.atan((rotation_point[1] - oy) / (rotation_point[0] - ox))
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)

    result = []
    for coord in group:
        # Translate to origin
        adj_x = coord[0] - ox
        adj_y = coord[1] - oy
        # Rotate
        qx = cos_a * adj_x - sin_a * adj_y
        qy = sin_a * adj_x + cos_a * adj_y
        # Flip if rotation point is left of reference point
        if ox - rotation_point[0] < 0:
            qx, qy = -qx, -qy
        result.append([qx, qy])

    # Close the loop
    result.append(result[0])
    result.append(result[1])
    return result
