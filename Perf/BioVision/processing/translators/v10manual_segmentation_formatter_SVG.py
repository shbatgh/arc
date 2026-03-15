"""
Manual Segmentation Formatter (SVG)

Converts manually segmented SVG slice images into structured wireframe data.
Uses svg_translator to parse each SVG file, then applies reference/rotation
corrections via adjust_algorithm.

Called by pickled_pre_visualization_phase.py when SVG mode is enabled.
"""

import time
import sys
import os

from . import adjust_algorithm, svg_translator

sys.setrecursionlimit(1500)

# Module-level state (set by prepare_manual_data)
should_rotate = True
timepoint_folders = []


def format_slice(slice_path, reference_point, rotation_point):
    """Process a single SVG slice into a slice dictionary.

    Parses the SVG to extract color-grouped outlines, then applies
    translation and rotation corrections to each outline. Appends the
    first 3 points to close the loop for downstream splining.

    Returns:
        Dict mapping (R, G, B) to list of adjusted outlines.
    """
    slice_data = svg_translator.extract_slice_from_svg(slice_path)

    for color, cells_list in slice_data.items():
        for idx, cur_cell in enumerate(cells_list):
            adjusted_cell = adjust_algorithm.adjust_group(
                group=cur_cell,
                reference_point=reference_point,
                rotation_point=rotation_point,
                should_rotate=should_rotate,
            )
            # Close the loop for splining
            adjusted_cell.append(adjusted_cell[0])
            adjusted_cell.append(adjusted_cell[1])
            adjusted_cell.append(adjusted_cell[2])
            slice_data[color][idx] = adjusted_cell

    return slice_data


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


def prepare_manual_data(path_to_timepoints, reference_point_list, rotation_point_list, rotate):
    """Main entry point. Process all SVG timepoints and return wireframe data.

    Args:
        path_to_timepoints:   Path to directory of timepoint folders.
        reference_point_list: [[x, y], ...] per timepoint for drift correction.
        rotation_point_list:  [[x, y], ...] per timepoint for rotation correction.
        rotate:               Whether to apply rotation correction.

    Returns:
        (frame_dict, time_taken) where frame_dict is
        {timepoint_index: [slice_dict, ...]} and time_taken is seconds elapsed.
    """
    global should_rotate, timepoint_folders
    should_rotate = rotate

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
