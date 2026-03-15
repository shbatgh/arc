"""
Cell Isolation by Color Filtering

Filters Cellpose-segmented cells by HSV or RGB color thresholds, keeping only
cells whose pixels predominantly match a target color range. Outputs
``_cp_outlines.txt`` files in the standard ``x,y,x,y,...`` format consumed by
the rest of the BioVision / ARC pipeline.

Typical usage — run **after** Cellpose segmentation (which produces
``*_seg.npy`` files alongside the source ``.tif`` images) and **before**
``pickled_pre_visualization_phase.py`` or direct ARC import.

Can be used as a library::

    from BioVision.processing.cell_isolation import isolate_cells
    isolate_cells(input_folder="raw_data", output_folder="filtered_outlines",
                  lower_hsv=(40, 45, 45), upper_hsv=(80, 255, 255))

Or run directly::

    python -m BioVision.processing.cell_isolation
"""

import glob
import os
import sys
from pathlib import Path

import cv2
import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ============================================================================
#  USER CONFIGURATION — edit these when running as a script
# ============================================================================

# Folder containing timepoint subfolders (t1/, t2/, …) with .tif + _seg.npy
INPUT_FOLDER = "raw_data"

# Where to write the filtered outline files (mirrors the t*/ structure)
OUTPUT_FOLDER = "filtered_outlines"

# HSV thresholds for the target color.  Set to None to use RGB mode instead.
LOWER_HSV = np.array([40, 45, 45])
UPPER_HSV = np.array([80, 255, 255])

# RGB thresholds (only used when LOWER_HSV / UPPER_HSV are None).
LOWER_RGB = np.array([0, 100, 0])
UPPER_RGB = np.array([100, 255, 100])

# Fraction of a cell's pixels that must fall inside the color range for the
# cell to be kept (0.0–1.0).
PIXEL_RATIO_THRESHOLD = 0.50


# ============================================================================
#  CORE FUNCTIONS
# ============================================================================

def _load_image_rgb(img_path):
    """Load an image and ensure it is 3-channel RGB."""
    img = cv2.imread(img_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {img_path}")
    if img.ndim == 2:
        img = np.stack([img] * 3, axis=-1)
    elif img.ndim == 3 and img.shape[2] == 1:
        img = np.concatenate([img] * 3, axis=2)
    elif img.ndim == 3 and img.shape[2] >= 3:
        img = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2RGB)
    return img


def _build_color_mask(img_rgb, lower_hsv=None, upper_hsv=None,
                      lower_rgb=None, upper_rgb=None):
    """Return a binary mask (0/255) for pixels inside the color range.

    If ``lower_hsv``/``upper_hsv`` are provided, filters in HSV space.
    Otherwise falls back to ``lower_rgb``/``upper_rgb`` in RGB space.
    """
    if lower_hsv is not None and upper_hsv is not None:
        hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)
        return cv2.inRange(hsv, np.asarray(lower_hsv), np.asarray(upper_hsv))
    elif lower_rgb is not None and upper_rgb is not None:
        return cv2.inRange(img_rgb, np.asarray(lower_rgb), np.asarray(upper_rgb))
    else:
        raise ValueError("Provide either HSV or RGB thresholds")


def _filter_masks_by_color(masks, color_mask, pixel_ratio_threshold):
    """Return the set of mask labels whose pixels pass the color ratio test."""
    labels = np.unique(masks)
    kept_labels = set()
    for label in labels:
        if label == 0:
            continue
        cell_pixels = (masks == label)
        n_total = int(cell_pixels.sum())
        if n_total == 0:
            continue
        n_match = int((color_mask[cell_pixels] == 255).sum())
        if n_match / n_total >= pixel_ratio_threshold:
            kept_labels.add(int(label))
    return kept_labels


def _extract_outlines(masks, kept_labels):
    """Extract the outer contour of each kept cell as a list of (x, y) arrays.

    Returns a list of Nx2 int arrays, one per cell, in OpenCV (x, y) order.
    """
    outlines = []
    for label in sorted(kept_labels):
        cell_img = np.uint8(masks == label) * 255
        contours, _ = cv2.findContours(cell_img, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        largest = max(contours, key=cv2.contourArea).squeeze()
        if largest.ndim == 1:
            largest = largest.reshape(1, 2)
        outlines.append(largest)
    return outlines


def _write_outlines(outlines, path):
    """Write outlines to a text file in ``x,y,x,y,...`` format (one cell per line)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        for contour in outlines:
            pairs = [f"{pt[0]},{pt[1]}" for pt in contour]
            f.write(",".join(pairs) + "\n")


# ============================================================================
#  PUBLIC API
# ============================================================================

def isolate_cells(input_folder, output_folder, *,
                  lower_hsv=None, upper_hsv=None,
                  lower_rgb=None, upper_rgb=None,
                  pixel_ratio_threshold=0.50):
    """Filter Cellpose-segmented cells by color and write outline files.

    Walks ``input_folder`` for ``*_seg.npy`` files (with matching ``.tif``
    images), applies the color filter, and writes one
    ``<stem>_cp_outlines.txt`` per slice into ``output_folder``, preserving
    the timepoint sub-directory structure.

    Args:
        input_folder:  Root folder containing timepoint sub-directories.
        output_folder: Where to write the filtered ``_cp_outlines.txt`` files.
        lower_hsv:     Lower HSV bound as (H, S, V). Takes priority over RGB.
        upper_hsv:     Upper HSV bound as (H, S, V).
        lower_rgb:     Lower RGB bound as (R, G, B). Used if HSV is None.
        upper_rgb:     Upper RGB bound as (R, G, B).
        pixel_ratio_threshold: Minimum fraction of a cell's pixels that must
            match the color range for the cell to be kept.

    Returns:
        Number of outline files written.
    """
    seg_files = sorted(
        glob.glob(os.path.join(input_folder, "**", "*_seg.npy"), recursive=True)
    )
    if not seg_files:
        print(f"No *_seg.npy files found under {input_folder}")
        return 0

    files_written = 0
    for seg_file in seg_files:
        stem = os.path.basename(seg_file).replace("_seg.npy", "")
        img_file = os.path.join(os.path.dirname(seg_file), stem + ".tif")
        if not os.path.exists(img_file):
            print(f"  Skipping {seg_file}: no matching .tif")
            continue

        subfolder = os.path.relpath(os.path.dirname(seg_file), input_folder)
        out_dir = os.path.join(output_folder, subfolder)

        img_rgb = _load_image_rgb(img_file)
        dat = np.load(seg_file, allow_pickle=True).item()
        masks = dat["masks"]

        color_mask = _build_color_mask(
            img_rgb,
            lower_hsv=lower_hsv, upper_hsv=upper_hsv,
            lower_rgb=lower_rgb, upper_rgb=upper_rgb,
        )
        kept = _filter_masks_by_color(masks, color_mask, pixel_ratio_threshold)

        if not kept:
            print(f"  {subfolder}/{stem}: 0 cells passed filter")
            continue

        outlines = _extract_outlines(masks, kept)
        out_path = os.path.join(out_dir, stem + "_cp_outlines.txt")
        _write_outlines(outlines, out_path)
        print(f"  {subfolder}/{stem}: {len(outlines)} cells -> {out_path}")
        files_written += 1

    print(f"Done. {files_written} outline files written to {output_folder}")
    return files_written


# ============================================================================
#  MAIN — run as a script
# ============================================================================

if __name__ == "__main__":
    use_hsv = LOWER_HSV is not None and UPPER_HSV is not None

    isolate_cells(
        input_folder=INPUT_FOLDER,
        output_folder=OUTPUT_FOLDER,
        lower_hsv=LOWER_HSV if use_hsv else None,
        upper_hsv=UPPER_HSV if use_hsv else None,
        lower_rgb=LOWER_RGB if not use_hsv else None,
        upper_rgb=UPPER_RGB if not use_hsv else None,
        pixel_ratio_threshold=PIXEL_RATIO_THRESHOLD,
    )
