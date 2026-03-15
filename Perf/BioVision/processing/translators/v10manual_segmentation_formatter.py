"""
Manual Segmentation Formatter (PNG)

Converts manually segmented PNG slice images into structured wireframe data.
For each slice image, traces colored pixel outlines using flood-fill, sorts
the outline points into a clean polygon order, and applies reference/rotation
corrections.

Called by pickled_pre_visualization_phase.py.
"""

import time
from PIL import Image
import numpy as np
from collections import deque
import sys
import os
import math

from . import adjust_algorithm, sort_robust_outline

# Whether to downsample outlines (take every Nth point). Keeps data smaller.
sparse = True

sys.setrecursionlimit(1500)

# Module-level state (set by prepare_manual_data)
width = 0
height = 0
sort = True
should_rotate = True
timepoint_folders = []

# Precomputed neighbor offsets for loose flood fill (8-connected + 2-step ring).
_LOOSE_OFFSETS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
    (-2, -2), (-2, -1), (-2, 0), (-2, 1), (-2, 2),
    (2, -2),  (2, -1),  (2, 0),  (2, 1),  (2, 2),
    (-1, -2), (0, -2),  (1, -2),
    (-1, 2),  (0, 2),   (1, 2),
)


def _add_to_dict(slice_dict, color, group):
    """Add an outline group to the slice dictionary under its color."""
    if color in slice_dict:
        slice_dict[color].append(group)
    else:
        slice_dict[color] = [group]


def _sorted_group(group, reference_point, rotation_point, color):
    """Sort outline points into polygon order, apply corrections, and close the loop.

    Steps:
      1. Sort raw boundary points into a non-crossing polygon.
      2. Translate and rotate to correct for specimen drift/rotation.
      3. Optionally downsample (sparse mode).
      4. Append the first 3 points at the end to close the loop for splining.
    """
    ts0 = time.time()
    sorted_pts = sort_robust_outline.sort_group(group)
    ts1 = time.time()

    adjusted = adjust_algorithm.adjust_group(
        group=sorted_pts,
        reference_point=reference_point,
        rotation_point=rotation_point,
        should_rotate=should_rotate,
    )

    if ts1 - ts0 > 0.5:
        print(f"    [SLOW SORT] {len(group)} pts, sort={ts1-ts0:.3f}s")

    if sparse:
        fin_coords = adjusted[::1]  # step=1 (change to downsample)
        fin_coords.append(fin_coords[0])
        fin_coords.append(fin_coords[1])
        fin_coords.append(fin_coords[2])
        return fin_coords

    return adjusted


def format_slice(slice_path, reference_point, rotation_point):
    """Process a single PNG slice image into a slice dictionary.

    Uses numpy to find all colored pixels, groups them by color, then
    finds connected components via BFS with the loose neighborhood.

    Returns:
        Dict mapping (R, G, B) to list of sorted outlines for this slice.
    """
    slice_dict = {}
    cur_img = Image.open(slice_path)
    img_arr = np.asarray(cur_img)

    # Vectorized scan: find all non-black, non-white pixels at once
    rgb = img_arr[:, :, :3]
    is_colored = ~(np.all(rgb == 0, axis=2) | np.all(rgb == 255, axis=2))
    colored_yx = np.argwhere(is_colored)

    if len(colored_yx) == 0:
        return slice_dict

    # Group pixel coordinates by color
    color_to_pixels = {}
    for y, x in colored_yx:
        c = (int(rgb[y, x, 0]), int(rgb[y, x, 1]), int(rgb[y, x, 2]))
        if c not in color_to_pixels:
            color_to_pixels[c] = set()
        color_to_pixels[c].add((x, y))

    # For each color, find connected components via BFS
    t_sort_total = 0
    t_bfs_total = 0
    total_components = 0
    for color, pixel_set in color_to_pixels.items():
        remaining = set(pixel_set)
        while remaining:
            tbfs0 = time.time()
            start_xy = remaining.pop()
            component = [[start_xy[0], start_xy[1]]]
            queue = deque([start_xy])
            while queue:
                cx, cy = queue.popleft()
                for dx, dy in _LOOSE_OFFSETS:
                    neighbor = (cx + dx, cy + dy)
                    if neighbor in remaining:
                        remaining.discard(neighbor)
                        component.append([neighbor[0], neighbor[1]])
                        queue.append(neighbor)
            t_bfs_total += time.time() - tbfs0

            tsort0 = time.time()
            _add_to_dict(
                slice_dict=slice_dict,
                color=color,
                group=_sorted_group(component, reference_point, rotation_point, color),
            )
            t_sort_total += time.time() - tsort0
            total_components += 1

    print(f"  [TIMING] bfs={t_bfs_total:.3f}s  sort={t_sort_total:.3f}s  "
          f"components={total_components}")

    return slice_dict


def format_stack(timepoint, reference_point, rotation_point):
    """Process all slices in a single timepoint folder.

    Returns:
        List of slice dictionaries, one per slice image.
    """
    cur_path = timepoint_folders[timepoint]
    print("\nFormatting stack " + os.path.basename(cur_path))
    slice_images = [f.path for f in os.scandir(cur_path) if f.is_file()]

    stack_list = []
    for slice_num in range(len(slice_images)):
        cur_slice = format_slice(
            slice_path=slice_images[slice_num],
            reference_point=reference_point,
            rotation_point=rotation_point,
        )
        stack_list.append(cur_slice)
    return stack_list


def prepare_manual_data(path_to_timepoints, reference_point_list, rotation_point_list,
                        image_dimensions, sort_large_groups, rotate):
    """Main entry point. Process all timepoints and return the wireframe data.

    Args:
        path_to_timepoints:   Path to directory of timepoint folders.
        reference_point_list: [[x, y], ...] per timepoint for drift correction.
        rotation_point_list:  [[x, y], ...] per timepoint for rotation correction.
        image_dimensions:     [width, height] of the images.
        sort_large_groups:    Whether to sort outlines from large cells.
        rotate:               Whether to apply rotation correction.

    Returns:
        (frame_dict, time_taken) where frame_dict is
        {timepoint_index: [slice_dict, ...]} and time_taken is seconds elapsed.
    """
    global should_rotate, sort, width, height, timepoint_folders
    should_rotate = rotate
    sort = sort_large_groups
    width, height = image_dimensions[0], image_dimensions[1]

    start_time = time.time()
    print("Preparing Manual Data")

    timepoint_folders = [f.path for f in os.scandir(path_to_timepoints) if f.is_dir()]

    frame_dict = {}
    for tp_num in range(len(timepoint_folders)):
        cur_stack = format_stack(
            timepoint=tp_num,
            reference_point=reference_point_list[tp_num],
            rotation_point=rotation_point_list[tp_num],
        )
        frame_dict[tp_num] = cur_stack

    return frame_dict, time.time() - start_time
