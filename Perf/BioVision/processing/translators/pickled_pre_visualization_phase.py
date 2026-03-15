"""
Pre-Visualization Phase (Entry Point)

Converts manually segmented slice images (PNG or SVG) into a pickled
WIREFRAME file that can be rendered in Blender or passed to the
quantitative analysis pipeline.

Walks the user through two phases interactively:
  1. Formatting Preparation  - detects image dimensions, reference points,
     and rotation points from the raw timepoint images.
  2. Manual Segmentation Formatter - traces colored outlines in each slice,
     sorts them, applies alignment/rotation corrections, and writes the
     result to a .pkl file with a WIREFRAME header.

See README.md for the full pipeline overview.
"""

import pickle
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    # Allow direct execution without requiring `python -m`.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# ============================================================================
#  USER CONFIGURATION - Change these before running
# ============================================================================

# Path to the folder containing the timepoint directories.
PATH_TO_TIMEPOINTS = r"C:/Users/tajre/OneDrive/Desktop/Amy Unprocessed/For Talk ForTara"

# Path for the output .pkl file (used in Phase 2).
OUTPUT_FILE = r"C:/Users/tajre/OneDrive/Desktop/Amy's Animations/For Talk UPDATED ForTara.pkl"

# Set to True if your input images are SVG files, False for PNG
SVG = False

# RGB color of the reference-point marker drawn in the images.
# Used to correct for specimen drift between timepoints.
REFERENCE_POINT_COLOR = (255, 255, 0)

# RGB color of the rotation-point marker drawn in the images.
# Used to correct for specimen rotation between timepoints.
ROTATION_POINT_COLOR = (0, 255, 0)

# Manually override image dimensions as [width, height].
# Set to False to auto-detect from the first image in the first timepoint.
MANUALLY_SET_IMAGE_DIMS = [512, 512]

# Whether to sort outlines from large cells (slower but produces cleaner
# wireframes). Highly recommended.
SORT_LARGE_GROUPS = True

# Whether to apply rotation correction using the rotation point.
ROTATE = True

# Whether to automatically go through steps without waiting for user input
AUTO_YES = True

# Path to save the reference/rotation point lists (for debugging).
# Set to False to skip saving.
SAVE_REF_ROT_PATH = False


# ============================================================================
#  PHASE 1 - FORMATTING PREPARATION
# ============================================================================

if AUTO_YES or input("\n\nRun formatting preparation? This needs to be run before "
         "the manual segmentation formatter. (y/n) ").lower() == "y":

    if SVG:
        from BioVision.processing.translators import formatting_preparation_SVG
    else:
        from BioVision.processing.translators import formatting_preparation
    print("Running formatting preparation")

    path_to_timepoints = PATH_TO_TIMEPOINTS

    # Detect or set image dimensions (PNG only; SVG doesn't need this)
    if not SVG:
        img_dims = formatting_preparation.find_image_dimensions(
            path_to_timepoints=path_to_timepoints
        )
        if MANUALLY_SET_IMAGE_DIMS:
            img_dims = MANUALLY_SET_IMAGE_DIMS

    # --- Reference points ---
    if AUTO_YES or input("Find reference points? Needed if the specimen drifts between "
             "timepoints. (y/n) ").lower() == "y":
        print("Finding Reference Points")
        if SVG:
            ref_list = formatting_preparation_SVG.find_ref_points_multiple_slices(
                path_to_timepoints=path_to_timepoints,
                reference_point_color=REFERENCE_POINT_COLOR,
            )
        else:
            ref_list = formatting_preparation.find_ref_points_multiple_slices(
                path_to_timepoints=path_to_timepoints,
                reference_point_color=REFERENCE_POINT_COLOR,
                image_dimensions=img_dims,
            )
        print(ref_list)
    else:
        n_timepoints = len([f for f in os.scandir(path_to_timepoints) if f.is_dir()])
        ref_list = [[0, 0] for _ in range(n_timepoints)]

    # --- Rotation points ---
    if AUTO_YES or input("Find rotation points? Needed if the specimen rotates between "
             "timepoints. (y/n) ").lower() == "y":
        print("Finding Rotation Points")
        if SVG:
            rot_list = formatting_preparation_SVG.find_ref_points_multiple_slices(
                path_to_timepoints=path_to_timepoints,
                reference_point_color=ROTATION_POINT_COLOR,
            )
        else:
            rot_list = formatting_preparation.find_ref_points_multiple_slices(
                path_to_timepoints=path_to_timepoints,
                reference_point_color=ROTATION_POINT_COLOR,
                image_dimensions=img_dims,
            )
        print(rot_list)
    else:
        rot_list = None

    # Optionally save the reference/rotation point lists to a text file
    if SAVE_REF_ROT_PATH:
        with open(SAVE_REF_ROT_PATH, "w") as f:
            f.write(str(ref_list) + "\n\n\n\n" + str(rot_list))


# ============================================================================
#  PHASE 2 - MANUAL SEGMENTATION FORMATTER
# ============================================================================

if AUTO_YES or input("\n\nRun manual segmentation formatter? (y/n) ").lower() == "y":
    from BioVision.processing.translators import v10manual_segmentation_formatter
    if SVG:
        from BioVision.processing.translators import v10manual_segmentation_formatter_SVG
    print("Running manual segmentation formatter")

    output_file = OUTPUT_FILE
    path_to_timepoints = PATH_TO_TIMEPOINTS

    # Run the formatter
    if SVG:
        frame_dict, manual_time_taken = (
            v10manual_segmentation_formatter_SVG.prepare_manual_data(
                path_to_timepoints=path_to_timepoints,
                reference_point_list=ref_list,
                rotation_point_list=rot_list,
                rotate=ROTATE,
            )
        )
    else:
        frame_dict, manual_time_taken = (
            v10manual_segmentation_formatter.prepare_manual_data(
                path_to_timepoints=path_to_timepoints,
                reference_point_list=ref_list,
                rotation_point_list=rot_list,
                image_dimensions=img_dims,
                sort_large_groups=SORT_LARGE_GROUPS,
                rotate=ROTATE,
            )
        )

    print("Manual data formatting time taken: " + str(manual_time_taken))

    # Write the WIREFRAME pickle
    with open(output_file, "wb") as f:
        f.write(b"WIREFRAME\n")
        pickle.dump(frame_dict, f)
