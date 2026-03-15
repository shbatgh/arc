"""
Formatting Preparation (SVG)

Locates reference/rotation point markers in SVG slice images.
Called by pickled_pre_visualization_phase.py when SVG mode is enabled.
"""

import os

from . import svg_translator


def find_ref_points_multiple_slices(path_to_timepoints, reference_point_color):
    """Find the average position of a colored marker across all slices in each timepoint.

    Parses each SVG file and looks for paths drawn in the given color. Averages
    all points from matching paths to produce a single [x, y] reference per
    timepoint.

    Args:
        path_to_timepoints:   Path to directory of timepoint folders.
        reference_point_color: (R, G, B) tuple of the marker color to find.

    Returns:
        List of [x, y] reference points, one per timepoint.
        Timepoints with no marker get [0, 0].
    """
    timepoint_folders = [f.path for f in os.scandir(path_to_timepoints) if f.is_dir()]
    print("Finding reference points on timepoints: ", end="")
    reference_point_list = []

    for tp_num in range(len(timepoint_folders)):
        print(str(tp_num + 1) + " ", end="")
        slice_images = [f.path for f in os.scandir(timepoint_folders[tp_num]) if f.is_file()]
        reference_cell_x, reference_cell_y = [], []

        for slice_path in slice_images:
            slice_data = svg_translator.extract_slice_from_svg(slice_path)
            if reference_point_color not in slice_data:
                continue

            # If multiple cells share the reference color, use the largest one
            target_cell_list = slice_data[reference_point_color][0]
            if len(slice_data[reference_point_color]) > 1:
                print(
                    f"WARNING: {len(slice_data[reference_point_color])} "
                    "reference-colored cells found. Using the largest.",
                    end="",
                )
                max_idx = max(
                    range(len(slice_data[reference_point_color])),
                    key=lambda i: len(slice_data[reference_point_color][i]),
                )
                target_cell_list = slice_data[reference_point_color][max_idx]

            reference_cell_x += [point[0] for point in target_cell_list]
            reference_cell_y += [point[1] for point in target_cell_list]

        if len(reference_cell_x) != 0:
            avg_x = int(sum(reference_cell_x) / len(reference_cell_x))
            avg_y = int(sum(reference_cell_y) / len(reference_cell_y))
            reference_point_list.append([avg_x, avg_y])
        else:
            print("No reference point found on timepoint t" + str(tp_num + 1))
            reference_point_list.append([0, 0])
    print()

    return reference_point_list
