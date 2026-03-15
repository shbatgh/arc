"""
Formatting Preparation (PNG)

Detects image dimensions and locates reference/rotation point markers
in PNG slice images. Called by pickled_pre_visualization_phase.py.
"""

from PIL import Image
import numpy as np
import os


def find_image_dimensions(path_to_timepoints):
    """Auto-detect image dimensions from the first image in the first timepoint.

    Returns [width, height].
    """
    timepoint_folders = [f.path for f in os.scandir(path_to_timepoints) if f.is_dir()]
    tp1_images = [f.path for f in os.scandir(timepoint_folders[0]) if f.is_file()]
    sample_img = Image.open(tp1_images[0])
    width, height = sample_img.size
    print("Image dimensions: " + str(width) + ", " + str(height))
    return [width, height]


def find_ref_points_multiple_slices(path_to_timepoints, reference_point_color, image_dimensions):
    """Find the average position of a colored marker across all slices in each timepoint.

    Uses numpy to find matching pixels in each slice image.

    Args:
        path_to_timepoints:   Path to directory of timepoint folders.
        reference_point_color: (R, G, B) tuple of the marker color to find.
        image_dimensions:      [width, height] of the images.

    Returns:
        List of [x, y] reference points, one per timepoint.
        Timepoints with no marker get [0, 0].
    """
    timepoint_folders = [f.path for f in os.scandir(path_to_timepoints) if f.is_dir()]
    print("Finding reference points on timepoints: ", end="")
    ref_color = np.array(reference_point_color, dtype=np.uint8)
    reference_point_list = []

    for tp_num in range(len(timepoint_folders)):
        print(str(tp_num + 1) + " ", end="")
        slice_images = [f.path for f in os.scandir(timepoint_folders[tp_num]) if f.is_file()]
        all_x, all_y = [], []

        for slice_path in slice_images:
            img_arr = np.asarray(Image.open(slice_path))[:, :, :3]
            matches = np.all(img_arr == ref_color, axis=2)
            yx = np.argwhere(matches)
            if len(yx) > 0:
                all_y.extend(yx[:, 0].tolist())
                all_x.extend(yx[:, 1].tolist())

        if len(all_x) != 0:
            avg_x = int(sum(all_x) / len(all_x))
            avg_y = int(sum(all_y) / len(all_y))
            reference_point_list.append([avg_x, avg_y])
        else:
            print("No reference point found on timepoint t" + str(tp_num + 1))
            reference_point_list.append([0, 0])
    print()

    return reference_point_list
