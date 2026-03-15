"""Unified single-file BioVision pipeline.

This file consolidates the end-to-end workflow into one executable module so the
pipeline can run without importing project-local code files. It supports three
entry modes: existing wireframe pickle input, outlines-to-wireframe conversion,
and images-to-segmentation-to-wireframe conversion.

The optional quantification stage performs color extraction, cell matching,
tracer export, quantitative CSV export, and mesh export. A built-in py-spy
profiling wrapper is included to generate flamegraphs for full pipeline runs.
"""

import argparse
import ast
import copy
import json
import math
import os
import pickle
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

try:
    import tifffile
except Exception:
    tifffile = None

try:
    from skimage import measure
except Exception as exc:  # pragma: no cover
    print(f"Missing dependency: scikit-image ({exc})")
    raise


# ============================================================================
# Paths and constants
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent
PROCESSING_DIR = PROJECT_ROOT / "processing"

IMAGE_EXTS = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp"}
DEFAULT_Z_SPACING = (3.0 / 0.198) * 0.5


# ============================================================================
# Inlined from processing/translators/lexographic_renaming.py
# ============================================================================

def rename(path, file_or_folder, name_length):
    """Pads numeric portions of file or folder names with leading zeros so lexicographic sorting matches numeric order.
    This runs before outlines parsing to keep timepoints and slice files in stable, deterministic order across platforms.
    """
    if file_or_folder == "file":
        items = [f.path for f in os.scandir(path) if f.is_file()]
    elif file_or_folder == "folder":
        items = [f.path for f in os.scandir(path) if f.is_dir()]
    else:
        print("file_or_folder not inputted correctly")
        return

    if name_length == 'auto':
        name_length = max([len(os.path.basename(os.path.normpath(item))) for item in items])

    for cur_item in items:
        cur_name = str(os.path.basename(os.path.normpath(cur_item)))
        new_name = list(cur_name)
        if len(new_name) >= name_length:
            continue
        for i in range(len(new_name)):
            cur_char = new_name[i]
            if cur_char.isnumeric():
                for _ in range(name_length - len(new_name)):
                    new_name.insert(i, '0')
                break
        new_name = ''.join(new_name)
        os.rename(os.path.normpath(path) + '/' + cur_name, os.path.normpath(path) + '/' + new_name)


def no_leading_zeros_rename(path, file_or_folder, name_length):
    """Removes leading zeros from numeric name prefixes when names are longer than the target width.
    It is a normalization companion to `rename` and is used when cleaning directory/file naming conventions.
    """
    if file_or_folder == "file":
        items = [f.path for f in os.scandir(path) if f.is_file()]
    elif file_or_folder == "folder":
        items = [f.path for f in os.scandir(path) if f.is_dir()]
    else:
        print("file_or_folder not inputted correctly")
        return

    for cur_item in items:
        cur_name = str(os.path.basename(os.path.normpath(cur_item)))
        new_name = list(cur_name)

        if len(new_name) <= name_length:
            continue

        index_delete_list = []
        for i in range(len(new_name)):
            cur_char = new_name[i]
            if cur_char.isnumeric() and cur_char != '0':
                break
            if cur_char == '0':
                index_delete_list.append(i)

        for i in range(len(index_delete_list)):
            del_index = index_delete_list[i] - i
            del new_name[del_index]
        new_name = ''.join(new_name)
        os.rename(os.path.normpath(path) + '/' + cur_name, os.path.normpath(path) + '/' + new_name)


# ============================================================================
# Inlined from processing/translators/formatting_preparation.py
# ============================================================================

def find_image_dimensions(path_to_timepoints):
    """Reads the first image in the first timepoint folder and returns `[width, height]`.
    Outlines mode uses this when dimensions are not provided on the CLI so downstream pixel scans use the correct bounds.
    """
    timepoint_folders = sorted([f.path for f in os.scandir(path_to_timepoints) if f.is_dir()])
    tp1_images = sorted([f.path for f in os.scandir(timepoint_folders[0]) if f.is_file()])
    img1_path = tp1_images[0]

    sample_img = Image.open(img1_path)
    width, height = sample_img.size
    print("Image dimensions: " + str(width) + ", " + str(height))
    return [width, height]


def find_ref_points_multiple_slices(path_to_timepoints, reference_point_color, image_dimensions):
    """Scans all slices in each timepoint for a marker RGB color and averages marker pixels into one reference point per timepoint.
    The formatter uses these per-timepoint points to translate/rotate outlines into a common coordinate frame.
    """
    timepoint_folders = sorted([f.path for f in os.scandir(path_to_timepoints) if f.is_dir()])
    print("Finding reference points on timepoints: ", end='')
    width, height = image_dimensions[0], image_dimensions[1]
    reference_point_list = []

    n_timepoints = len(timepoint_folders)

    for tp_num in range(n_timepoints):
        print(str(tp_num + 1) + ' ', end='')

        slice_images = sorted([f.path for f in os.scandir(timepoint_folders[tp_num]) if f.is_file()])
        reference_cell_x, reference_cell_y = [], []

        for slice_path in slice_images:
            cur_img = Image.open(slice_path)
            pix = cur_img.load()

            for x in range(width):
                for y in range(height):
                    if pix[x, y][:3] == reference_point_color:
                        reference_cell_x.append(x)
                        reference_cell_y.append(y)

        if len(reference_cell_x) != 0:
            reference_point_list.append([
                int(sum(reference_cell_x) / len(reference_cell_x)),
                int(sum(reference_cell_y) / len(reference_cell_y))
            ])
        else:
            print("No reference point found on timepoint t" + str(tp_num + 1))
            reference_point_list.append([0, 0])
    print("\n")

    return reference_point_list


# ============================================================================
# Inlined from processing/translators/adjust_algorithm.py
# ============================================================================

def adjust_group(group, reference_point, rotation_point, should_rotate):
    """Translates outline coordinates by the reference point and optionally rotates them using the rotation point direction.
    This is the geometric normalization step before wireframe serialization in outlines mode.
    """
    ox, oy = reference_point[0], reference_point[1]

    if not should_rotate:
        return [[coord[0] - ox, coord[1] - oy] for coord in group]

    result = []
    angle = -math.atan((rotation_point[1] - oy) / (rotation_point[0] - ox))

    for coord in group:
        px, py = coord[0], coord[1]
        adj_px, adj_py = px - ox, py - oy
        qx = math.cos(angle) * adj_px - math.sin(angle) * adj_py
        qy = math.sin(angle) * adj_px + math.cos(angle) * adj_py

        if ox - rotation_point[0] < 0:
            qx, qy = -qx, -qy
        result.append([qx, qy])

    result.append(result[0])
    result.append(result[1])
    return result


# ============================================================================
# Inlined from processing/translators/sort_robust_outline.py
# ============================================================================

def _distance_sq(p1, p2):
    """Computes squared Euclidean distance between two 2D points.
    Used by robust outline ordering to avoid repeated square-root calls in nearest-neighbor selection.
    """
    return (p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2


def _ccw(A, B, C):
    """Returns whether three points are in counter-clockwise orientation.
    This orientation test is part of the segment-intersection logic in the 2-opt cleanup pass.
    """
    return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])


def _segments_intersect(A, B, C, D):
    """Checks whether two line segments intersect using CCW orientation predicates.
    The robust sorter uses this to remove self-crossings while improving outline traversal order.
    """
    return _ccw(A, C, D) != _ccw(B, C, D) and _ccw(A, B, C) != _ccw(A, B, D)


def _nearest_neighbor_order(points):
    """Builds an initial visit order by repeatedly selecting the nearest unvisited point.
    This provides a fast first-pass path that the 2-opt routine refines into a cleaner contour order.
    """
    n = len(points)
    visited = [False] * n
    order = [0]
    visited[0] = True

    for _ in range(n - 1):
        cur = order[-1]
        best_sq = float('inf')
        best = -1
        for j in range(n):
            if not visited[j]:
                d = _distance_sq(points[cur], points[j])
                if d < best_sq:
                    best_sq = d
                    best = j
        order.append(best)
        visited[best] = True

    return order


def _two_opt(points, order):
    """Iteratively reverses path segments when intersections are found, reducing contour self-crossings.
    It is the expensive refinement step inside robust outline sorting for noisy or unordered point groups.
    """
    n = len(order)
    improved = True
    while improved:
        improved = False
        for i in range(n - 1):
            for j in range(i + 2, n):
                if i == 0 and j == n - 1:
                    continue

                A = points[order[i]]
                B = points[order[i + 1]]
                C = points[order[j]]
                D = points[order[(j + 1) % n]]

                if _segments_intersect(A, B, C, D):
                    order[i + 1:j + 1] = order[i + 1:j + 1][::-1]
                    improved = True
    return order


def robust_sort_group(group):
    """Returns an ordered version of a point group using nearest-neighbor initialization and 2-opt cleanup.
    Manual outline formatting calls this before coordinate adjustment so exported outlines are topologically consistent.
    """
    if len(group) <= 3:
        return list(group)

    order = _nearest_neighbor_order(group)
    order = _two_opt(group, order)
    return [group[i] for i in order]


# ============================================================================
# Inlined from processing/translators/v10manual_segmentation_formatter.py
# ============================================================================

VF_sparse = True
sys.setrecursionlimit(1500)

VF_should_rotate = False
VF_width, VF_height = 0, 0
VF_timepoint_folders = []


def vf_get_surrounding_colored_points(pix, point_coords, color, loose):
    """Collects neighboring pixels around a point that match a target RGB color, with optional loose radius.
    This is the local adjacency primitive used to grow connected color components in a slice.
    """
    coords1 = [point_coords[0] - 1, point_coords[1] - 1]
    coords2 = [point_coords[0] - 1, point_coords[1]]
    coords3 = [point_coords[0] - 1, point_coords[1] + 1]

    coords4 = [point_coords[0], point_coords[1] - 1]
    coords5 = [point_coords[0], point_coords[1] + 1]

    coords6 = [point_coords[0] + 1, point_coords[1] - 1]
    coords7 = [point_coords[0] + 1, point_coords[1]]
    coords8 = [point_coords[0] + 1, point_coords[1] + 1]

    coords_list = [coords1, coords2, coords3, coords4, coords5, coords6, coords7, coords8]

    if loose:
        ys = [-2, -1, 0, 1, 2]
        for y in ys:
            coords_list.append([point_coords[0] - 2, point_coords[1] + y])
        for y in ys:
            coords_list.append([point_coords[0] + 2, point_coords[1] + y])

        xs = [-1, 0, 1]
        for x in xs:
            coords_list.append([point_coords[0] + x, point_coords[1] - 2])
        for x in xs:
            coords_list.append([point_coords[0] + x, point_coords[1] + 2])

    if not (1 < point_coords[0] < VF_width - 2 and 1 < point_coords[1] < VF_height - 2):
        for coord in coords_list.copy():
            if not (0 <= coord[0] <= VF_width - 1 and 0 <= coord[1] <= VF_height - 1):
                coords_list.remove(coord)

    surrounding_points = []

    for coord in coords_list:
        cur_x, cur_y = coord[0], coord[1]
        coord_color = pix[cur_x, cur_y][:3]
        if coord_color == color:
            surrounding_points.append(coord)
    return surrounding_points


def vf_create_outline_lists(pix, starting_point, color):
    """Flood-fills from a starting pixel to gather all connected pixels of the same color.
    Each connected component becomes one raw outline group before sorting and coordinate normalization.
    """
    final_point_list = [starting_point]
    queued_points = vf_get_surrounding_colored_points(
        pix=pix,
        point_coords=starting_point,
        color=color,
        loose=True,
    )
    while len(queued_points) > 0:
        temporary_list = []
        for q_point in queued_points:
            for pos_new_point in vf_get_surrounding_colored_points(
                pix=pix,
                point_coords=q_point,
                color=color,
                loose=True,
            ):
                if (pos_new_point not in temporary_list) and (pos_new_point not in final_point_list):
                    temporary_list.append(pos_new_point)
        queued_points = temporary_list

        final_point_list += queued_points
    return final_point_list


def vf_add_to_dict(data_dict, color, group):
    """Appends a grouped outline under its RGB key in a per-slice dictionary.
    This keeps the wireframe payload grouped by color for downstream matching and quantification.
    """
    if color in data_dict.keys():
        data_dict[color].append(group)
    else:
        data_dict[color] = [group]


def vf_sorted_group(group, reference_point, rotation_point, color):
    """Orders points robustly, applies reference/rotation adjustment, and optionally sparsifies/extends the contour endpoints.
    This finalizes one component into the shape format expected by the wireframe pickle schema.
    """
    sorted_points = robust_sort_group(group)

    adjusted_group = adjust_group(
        group=sorted_points,
        reference_point=reference_point,
        rotation_point=rotation_point,
        should_rotate=VF_should_rotate,
    )

    if VF_sparse:
        fin_coords = []
        step = 1
        if color in [(0, 255, 0), (255, 0, 255), (255, 0, 0), (255, 0, 0)]:
            step = 1
        for i in range(0, len(adjusted_group), step):
            fin_coords.append(adjusted_group[i])
        fin_coords.append(fin_coords[0])
        fin_coords.append(fin_coords[1])
        fin_coords.append(fin_coords[2])
        return fin_coords

    return adjusted_group


def vf_format_slice(slice_path, reference_point, rotation_point):
    """Scans every pixel in one outline image, extracts non-background connected components, and groups them by color.
    It is the core slice parser in outlines mode and feeds per-slice dictionaries into each timepoint stack.
    """
    slice_dict = {}

    cur_img = Image.open(slice_path)
    pix = cur_img.load()

    checked_points = []
    for x in range(VF_width):
        for y in range(VF_height):
            color = pix[x, y][:3]
            if (color != (0, 0, 0) and color != (255, 255, 255)) and ([x, y] not in checked_points):
                cur_group = vf_create_outline_lists(pix=pix, starting_point=[x, y], color=color)
                checked_points += cur_group

                vf_add_to_dict(
                    data_dict=slice_dict,
                    color=color,
                    group=vf_sorted_group(cur_group, reference_point, rotation_point, color),
                )

    return slice_dict


def vf_format_stack(timepoint, reference_point, rotation_point):
    """Processes every slice image in one timepoint folder by calling `vf_format_slice` in file order.
    The returned list is one timepoint stack in the wireframe frame dictionary.
    """
    cur_path = VF_timepoint_folders[timepoint]
    print("\nFormatting stack " + os.path.basename(os.path.normpath(cur_path)))
    slice_images = sorted([f.path for f in os.scandir(cur_path) if f.is_file()])

    n_slices = len(slice_images)

    stack_list = []
    for slice_num in range(n_slices):
        cur_slice = vf_format_slice(
            slice_path=slice_images[slice_num],
            reference_point=reference_point,
            rotation_point=rotation_point,
        )
        stack_list.append(cur_slice)
    return stack_list


def prepare_manual_data(path_to_timepoints, reference_point_list, rotation_point_list, image_dimensions, sort_large_groups, rotate):
    # Keep signature/flow close to original even though sort_large_groups is not used in robust sorter
    """Runs outline formatting across all timepoints and returns the assembled frame dictionary plus elapsed time.
    This is the main converter used by outlines mode before writing the `WIREFRAME` pickle.
    """
    _ = sort_large_groups

    global VF_should_rotate
    VF_should_rotate = rotate

    start_manual_time = time.time()
    print("Preparing Manual Data")

    global VF_width, VF_height
    VF_width, VF_height = image_dimensions[0], image_dimensions[1]

    global VF_timepoint_folders
    VF_timepoint_folders = sorted([f.path for f in os.scandir(path_to_timepoints) if f.is_dir()])
    n_timepoints = len(VF_timepoint_folders)

    frame_dict = {}
    for tp_num in range(n_timepoints):
        cur_refp = reference_point_list[tp_num]
        cur_rotp = rotation_point_list[tp_num]

        cur_stack = vf_format_stack(
            timepoint=tp_num,
            reference_point=cur_refp,
            rotation_point=cur_rotp,
        )
        frame_dict[tp_num] = cur_stack

    manual_time_taken = time.time() - start_manual_time
    return frame_dict, manual_time_taken


# ============================================================================
# Inlined from processing/translators/color_extractor.py
# ============================================================================

MIN_LENGTH = 14


def get_data(file_path):
    """Reads a header-prefixed pickle file and returns `(header, payload)`.
    The quantification stage uses this to load wireframe data before color extraction.
    """
    with open(file_path, "rb") as f:
        header = f.readline()
        parsed_data = pickle.load(f)

    return header, parsed_data


def extract(dict_data, skip_slice=0):
    """Collects unique RGB colors that have outlines longer than a minimum length across timepoints and slices.
    These extracted colors determine which cell tracks are matched and quantified in the downstream pipeline.
    """
    result_colors = []

    for tp in dict_data.keys():
        tp_list = dict_data[tp]
        if skip_slice != 0:
            tp_list = dict_data[tp][skip_slice:-skip_slice]

        for cur_slice in tp_list:
            for color in cur_slice.keys():
                if color in result_colors:
                    continue
                for outline in cur_slice[color]:
                    if len(outline) > MIN_LENGTH and color not in result_colors:
                        result_colors.append(color)

    return result_colors


# ============================================================================
# Inlined (adapted to function form) from arc-c++/tools/segment_images_to_animation.py
# ============================================================================


def parse_int_token(text: str) -> int:
    """Extracts the first integer from a string, returning a large sentinel when no integer exists.
    Used to sort timepoint folders and slice files numerically instead of pure lexicographic text order.
    """
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else 10**9


def deterministic_color(seed: int) -> tuple[int, int, int]:
    """Generates a deterministic pseudo-random RGB color from an integer seed.
    Segmentation mode uses this to assign stable display/group colors to instance labels in RAW JSON.
    """
    r = (seed * 53 + 29) % 256
    g = (seed * 97 + 71) % 256
    b = (seed * 193 + 11) % 256
    return int(r), int(g), int(b)


def to_numpy(x):
    """Converts tensors/array-like inputs to a NumPy array, detaching Torch tensors when needed.
    This normalizes model outputs before mask/label post-processing.
    """
    try:
        import torch

        if isinstance(x, torch.Tensor):
            return x.detach().cpu().numpy()
    except Exception:
        pass
    return np.asarray(x)


def normalize_labels(mask_like) -> np.ndarray:
    """Normalizes segmentation output into a 2D non-negative `int32` label map.
    It handles bool/float/logit-like outputs so contour extraction can run on a consistent label representation.
    """
    arr = to_numpy(mask_like)
    if arr.ndim > 2:
        arr = np.squeeze(arr)
        if arr.ndim > 2:
            arr = np.argmax(arr, axis=0)

    if arr.ndim != 2:
        raise ValueError(f"Expected 2D labels; got shape={arr.shape}")

    if arr.dtype == np.bool_:
        arr = measure.label(arr, connectivity=1)

    if np.issubdtype(arr.dtype, np.floating):
        if float(np.nanmax(arr)) <= 1.0:
            arr = measure.label(arr > 0.5, connectivity=1)
        else:
            arr = np.rint(arr)

    arr = arr.astype(np.int32, copy=False)
    arr[arr < 0] = 0
    return arr


def load_image(path: Path) -> np.ndarray:
    """Loads an image file into a NumPy array, using `tifffile` for TIFF when available.
    Segmentation mode calls this for every input slice before inference.
    """
    if path.suffix.lower() in {".tif", ".tiff"} and tifffile is not None:
        return np.asarray(tifffile.imread(path))
    return np.asarray(Image.open(path))


def infer_gpu_available() -> bool:
    """Checks whether CUDA or Apple MPS appears available through Torch.
    This is used by auto device selection in segmentation mode.
    """
    try:
        import torch

        if torch.cuda.is_available():
            return True
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return True
    except Exception:
        pass
    return False


def resolve_use_gpu(device: str) -> bool:
    """Resolves `cpu/gpu/auto` CLI policy to a boolean GPU usage decision.
    The segmentation runner builders use this to configure model initialization.
    """
    d = device.strip().lower()
    if d == "cpu":
        return False
    if d == "gpu":
        return True
    return infer_gpu_available()


def build_cellpose_runner(model_name: str, use_gpu: bool, diameter: float):
    """Constructs and configures a Cellpose/Cellpose-SAM model wrapper for slice inference.
    Returns a callable used repeatedly by the segmentation loop to produce normalized label masks.
    """
    from cellpose import models

    model = None
    if model_name == "cellpose":
        ctor_variants = [
            {"gpu": use_gpu, "model_type": "cyto3"},
            {"gpu": use_gpu, "pretrained_model": "cyto3"},
            {"gpu": use_gpu},
        ]
    else:
        ctor_variants = [
            {"gpu": use_gpu, "pretrained_model": "cpsam"},
            {"gpu": use_gpu, "model_type": "cpsam"},
            {"gpu": use_gpu},
        ]

    last_err = None
    for kwargs in ctor_variants:
        try:
            model = models.CellposeModel(**kwargs)
            break
        except Exception as exc:
            last_err = exc
            continue

    if model is None:
        raise RuntimeError(f"Failed to initialize Cellpose model: {last_err}")

    eval_kwargs = {}
    if diameter > 0:
        eval_kwargs["diameter"] = float(diameter)

    def run(image: np.ndarray) -> np.ndarray:
        """Runs Cellpose inference on one image with fallback eval signatures and optional diameter override.
        This closure is the per-slice inference function consumed by `run_segmentation_to_json`.
        """
        attempts = [dict(eval_kwargs, channels=[0, 0]), dict(eval_kwargs)]

        last_eval_err = None
        for kwargs in attempts:
            try:
                out = model.eval(image, **kwargs)
                masks = out[0] if isinstance(out, tuple) else out
                if isinstance(masks, list) and len(masks) == 1:
                    masks = masks[0]
                return normalize_labels(masks)
            except TypeError as exc:
                last_eval_err = exc
                continue
            except Exception as exc:
                raise RuntimeError(f"Cellpose inference failed: {exc}") from exc

        raise RuntimeError(f"Cellpose eval signature mismatch: {last_eval_err}")

    return run


def build_cellsam_runner():
    """Builds a CellSAM inference wrapper and normalizes variant output formats.
    Returns a callable with the same contract as the Cellpose runner for interchangeable segmentation backends.
    """
    try:
        from cellSAM import cellsam_pipeline
    except Exception:
        from cellsam import cellsam_pipeline

    def run(image: np.ndarray) -> np.ndarray:
        """Runs CellSAM on one image and normalizes dict/tensor outputs into a 2D label map.
        This closure plugs into the same segmentation loop used by other model backends.
        """
        out = cellsam_pipeline(image)
        if isinstance(out, dict):
            for key in ("masks", "labels", "mask", "segmentation", "instances"):
                if key in out:
                    out = out[key]
                    break
        return normalize_labels(out)

    return run


@dataclass
class TimepointImages:
    timepoint: int
    directory: Path
    files: list[Path]


def collect_image_files(directory: Path) -> list[Path]:
    """Lists supported image files in one directory and sorts them numerically by stem token.
    Used by timepoint discovery to produce deterministic slice order for segmentation.
    """
    files = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    files.sort(key=lambda p: (parse_int_token(p.stem), p.name))
    return files


def discover_timepoints(input_root: Path) -> list[TimepointImages]:
    """Discovers timepoint directories (`t1`, `t2`, etc.) or falls back to a single flat-image timepoint.
    Segmentation mode uses this to build the processing plan before per-slice inference.
    """
    tp_dirs: list[tuple[int, Path]] = []
    for child in input_root.iterdir():
        if child.is_dir():
            n = parse_int_token(child.name)
            if n < 10**9:
                tp_dirs.append((n, child))

    tp_dirs.sort(key=lambda x: (x[0], x[1].name))

    discovered: list[TimepointImages] = []
    if tp_dirs:
        for tp, d in tp_dirs:
            imgs = collect_image_files(d)
            if imgs:
                discovered.append(TimepointImages(timepoint=tp, directory=d, files=imgs))
        return discovered

    flat = collect_image_files(input_root)
    if flat:
        discovered.append(TimepointImages(timepoint=1, directory=input_root, files=flat))
    return discovered


def mask_to_contours(mask: np.ndarray, min_area: int) -> dict[int, list[np.ndarray]]:
    """Converts an instance label mask into per-label contour arrays and drops tiny regions.
    These contours are written to outputs and transformed into RAW JSON grouped geometry.
    """
    out: dict[int, list[np.ndarray]] = {}
    labels = np.unique(mask)
    labels = labels[labels > 0]
    for label in labels:
        binary = mask == int(label)
        if int(binary.sum()) < min_area:
            continue
        contours = measure.find_contours(binary.astype(np.uint8), level=0.5)
        curves = [c for c in contours if c.shape[0] >= 6]
        if curves:
            out[int(label)] = curves
    return out


def write_outline_txt(path: Path, contours_xy: list[np.ndarray]) -> None:
    """Writes contour coordinates to text in the expected comma-separated outline format.
    This preserves a human-inspectable outline artifact alongside mask and JSON outputs.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for curve in contours_xy:
        vals: list[str] = []
        for row, col in curve:
            vals.append(f"{col:.3f}")
            vals.append(f"{row:.3f}")
        if vals:
            lines.append(",".join(vals))
    path.write_text("\n".join(lines), encoding="utf-8")


def write_mask_outputs(mask: np.ndarray, out_dir: Path, stem: str) -> None:
    """Writes segmentation masks to `.npy` and `.tif` artifacts for each processed slice.
    These files are debugging and provenance outputs for segmentation mode.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / f"{stem}_mask.npy", mask.astype(np.int32, copy=False))

    if tifffile is not None:
        if int(mask.max()) <= 65535:
            tifffile.imwrite(out_dir / f"{stem}_mask.tif", mask.astype(np.uint16, copy=False))
        else:
            tifffile.imwrite(out_dir / f"{stem}_mask.tif", mask.astype(np.int32, copy=False))


def run_segmentation_to_json(
    input_root: Path,
    output_root: Path,
    model: str,
    device: str,
    diameter: float,
    min_area: int,
    z_spacing: float,
    animation_json: Path | None,
):
    """Runs end-to-end segmentation over discovered timepoints/slices and emits ARC-style RAW animation JSON.
    This is the core `images`-mode producer that bridges raw images to wireframe conversion.
    """
    if not input_root.exists():
        raise FileNotFoundError(f"Input folder not found: {input_root}")

    timepoints = discover_timepoints(input_root)
    if not timepoints:
        raise RuntimeError(f"No supported image files found under: {input_root}")

    use_gpu = resolve_use_gpu(device)
    if model in {"cellpose", "cellpose-sam"}:
        segment_fn = build_cellpose_runner(model, use_gpu=use_gpu, diameter=diameter)
    else:
        segment_fn = build_cellsam_runner()

    payload: dict[str, list[dict[str, list[list[list[float]]]]]] = {}
    total_slices = 0
    total_instances = 0

    masks_root = output_root / "masks"
    outlines_root = output_root / "outlines"

    for tp in timepoints:
        slice_payload: list[dict[str, list[list[list[float]]]]] = []
        for slice_idx, img_path in enumerate(tp.files):
            image = load_image(img_path)
            labels = segment_fn(image)

            write_mask_outputs(labels, masks_root / f"t{tp.timepoint}", img_path.stem)
            contours = mask_to_contours(labels, min_area=max(1, int(min_area)))
            total_instances += len(contours)

            outline_curves: list[np.ndarray] = []
            slice_dict: dict[str, list[list[list[float]]]] = {}
            z = float(slice_idx) * float(z_spacing)

            for label_id, curves in contours.items():
                seed = (tp.timepoint * 1_000_000) + (slice_idx * 10_000) + label_id
                r, g, b = deterministic_color(seed)
                key = f"[{r}, {g}, {b}]#L{label_id}"

                groups: list[list[list[float]]] = []
                for curve in curves:
                    outline_curves.append(curve)
                    group = [[float(col), float(row), z] for row, col in curve]
                    groups.append(group)
                slice_dict[key] = groups

            outline_path = outlines_root / f"t{tp.timepoint}" / f"{img_path.stem}_cp_outlines.txt"
            write_outline_txt(outline_path, outline_curves)
            slice_payload.append(slice_dict)
            total_slices += 1

        payload[str(tp.timepoint)] = slice_payload

    model_safe = model.replace("-", "_")
    default_json = output_root / f"{input_root.name}_{model_safe}_raw.json"
    animation_json = animation_json if animation_json else default_json
    animation_json.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "source_folder": str(input_root),
        "model": model,
        "device": "gpu" if use_gpu else "cpu",
        "header": "RAW",
        "payload": payload,
    }
    animation_json.write_text(json.dumps(output), encoding="utf-8")

    print("Segmentation complete")
    print(f"Model: {model}")
    print(f"Device: {'gpu' if use_gpu else 'cpu'}")
    print(f"Timepoints: {len(payload)}")
    print(f"Slices processed: {total_slices}")
    print(f"Instances: {total_instances}")
    print(f"Masks dir: {masks_root}")
    print(f"Outlines dir: {outlines_root}")
    print(f"Animation JSON: {animation_json}")

    return animation_json


# ============================================================================
# Inlined from processing/single_stack_cell_matching.py
# ============================================================================

ss_cell_count = 0
ss_cells = []
DIST_MULTIPLIER = 0.7


class Cell:
    def __init__(self, id, starting_slice, initial_outline, c_color):
        """Creates a per-stack cell track with starting slice, first outline, and first center.
        Instances are built during within-timepoint slice matching before 3D/4D linking.
        """
        self.id = id
        self.color = c_color

        self.starting_slice = starting_slice
        self.top_slice = starting_slice

        self.centers = [ss_find_center(initial_outline)]
        self.outlines = [initial_outline]

        global ss_cell_count, ss_cells
        ss_cell_count += 1
        ss_cells.append(self)

    def add_outline(self, new_outline):
        """Appends a newly matched outline to an existing stack-level cell and updates derived center/top slice.
        Called when slice-to-slice matching links a segment to an existing cell track.
        """
        self.top_slice += 1
        self.outlines.append(new_outline)
        self.centers.append(ss_find_center(new_outline))


def ss_find_center(point_list):
    """Computes the centroid of a 2D outline point list.
    Used extensively by single-stack matching heuristics and distance scoring.
    """
    length = len(point_list)
    if length == 0:
        return None

    x_sum, y_sum = 0, 0
    for [x, y] in point_list:
        x_sum += x
        y_sum += y
    return (x_sum / length, y_sum / length)


def ss_approx_width(point_list, x_or_y):
    """Approximates an outline extent along `x` or `y` by min-max spread.
    This feeds matching error thresholds so link distances scale with object size.
    """
    comp = 0
    if x_or_y == "y":
        comp = 1
    res_min = point_list[0][comp]
    res_max = point_list[1][comp]
    for p in point_list:
        val = p[comp]
        if val < res_min:
            res_min = val
        elif val > res_max:
            res_max = val
    return res_max - res_min


def ss_find_segs(slice_dict, color):
    """Returns all segments for a given color from one slice dictionary.
    This isolates matching to one color class at a time in stack matching.
    """
    if color not in slice_dict.keys():
        return []
    return slice_dict[color].copy()


def ss_matched_sort_fn(e):
    """Sort key for candidate pairs based on center distance.
    Used to prioritize nearest matches before conflict filtering.
    """
    return e[1]


def ss_match_cells(cur_cells, prev_cells):
    """Builds all current-vs-previous segment pair candidates with center distances and sorts them.
    This creates the candidate list that is pruned by `ss_filter_pairs`.
    """
    matched_list = []
    for cur_c in cur_cells:
        cur_center = ss_find_center(cur_c)
        for prev_c in prev_cells:
            prev_center = ss_find_center(prev_c)
            matched_list.append([{cur_center: cur_c, prev_center: prev_c}, math.dist(cur_center, prev_center)])
    matched_list.sort(key=ss_matched_sort_fn)
    return matched_list


def ss_remove_pairs(matched_list, center):
    """Removes all candidate pairs containing a tagged center to enforce one-to-one matches.
    Used by the greedy conflict-resolution loop in single-stack matching.
    """
    new_matched_list = []
    for pair in matched_list:
        if center not in pair[0].keys():
            new_matched_list.append(pair)
    return new_matched_list


def ss_find_max_error(point_list1, point_list2):
    """Computes an adaptive distance threshold for a candidate pair from outline extents.
    Pairs beyond this threshold are rejected as implausible slice-to-slice links.
    """
    approx_r1 = max([ss_approx_width(point_list1, "x"), ss_approx_width(point_list1, "y")])
    approx_r2 = max([ss_approx_width(point_list2, "x"), ss_approx_width(point_list2, "y")])
    return max(approx_r1, approx_r2) * DIST_MULTIPLIER


def ss_appears_before(matched_list, center, loc):
    """Checks whether a center already appeared in earlier candidate pairs.
    This supports conflict tagging so each center is linked at most once.
    """
    found = False
    for e in matched_list[:loc]:
        if center in e[0].keys():
            found = True
            break
    return found


def ss_tag_centers(matched_list, center, starting_idx):
    """Tags competing centers that conflict with a chosen pair from the current index onward.
    It is part of the greedy pair-pruning strategy in stack matching.
    """
    tagged = []
    for cur_idx in range(starting_idx, len(matched_list)):
        pair = matched_list[cur_idx]
        c_centers = list(pair[0].keys()).copy()
        if center in c_centers:
            c_centers.remove(center)
            center_pos_tag = c_centers[0]
            if not ss_appears_before(matched_list=matched_list, center=center_pos_tag, loc=cur_idx):
                tagged.append(center_pos_tag)
    return tagged


def ss_filter_pairs(matched_list):
    """Greedily filters sorted candidate pairs to one-to-one links and applies adaptive error thresholds.
    The output drives actual outline-to-cell assignments for each slice transition.
    """
    filtered = []
    idx = 0
    while idx < len(matched_list):
        filtered.append(matched_list[idx])

        paired_centers = list(matched_list[idx][0].keys())
        tagged = [paired_centers[0], paired_centers[1]]
        tagged += ss_tag_centers(matched_list=matched_list, center=paired_centers[0], starting_idx=idx + 1)
        tagged += ss_tag_centers(matched_list=matched_list, center=paired_centers[1], starting_idx=idx + 1)

        for center in tagged:
            matched_list = ss_remove_pairs(matched_list=matched_list, center=center)
    new_filtered = []
    for pair in filtered:
        outlines = list(pair[0].values())
        max_error = ss_find_max_error(outlines[0], outlines[1])
        if pair[1] < max_error:
            new_filtered.append(pair)
    return new_filtered


def ss_identify_cell(center, color):
    """Finds the active `Cell` object by prior center and color.
    Used when a matched pair says the current segment should extend an existing track.
    """
    for c_obj in ss_cells:
        if (c_obj.color == color) and (center in c_obj.centers):
            return c_obj

    print("No Cell Found with center: ", center)
    return None


def ss_compute_slice(stack_list, slice_num, color):
    """Matches one slice against the previous slice for a single color and updates/creates `Cell` tracks.
    This is the per-transition worker used by `compute_stack`.
    """
    cur_segs = ss_find_segs(slice_dict=stack_list[slice_num], color=color)
    prev_segs = ss_find_segs(slice_dict=stack_list[slice_num - 1], color=color)

    if len(cur_segs) == 0:
        return
    if len(prev_segs) == 0:
        for seg in cur_segs:
            Cell(id="Cell" + str(color) + " " + str(ss_cell_count), starting_slice=slice_num, initial_outline=seg, c_color=color)
        return

    matched_list = ss_match_cells(cur_cells=cur_segs, prev_cells=prev_segs)
    filtered_list = ss_filter_pairs(matched_list=matched_list)

    for pair in filtered_list:
        cur_outline = list(pair[0].values())[0]
        prev_center = list(pair[0].keys())[1]

        cell_obj = ss_identify_cell(prev_center, color)
        cell_obj.add_outline(new_outline=cur_outline)

        cur_segs.remove(cur_outline)

    for seg in cur_segs:
        Cell(id="Cell" + str(color) + " " + str(ss_cell_count), starting_slice=slice_num, initial_outline=seg, c_color=color)


def ss_first_slice_cells(slice_dict, color):
    """Initializes `Cell` objects from first-slice segments for a given color.
    Provides the base state before iterative slice-to-slice matching starts.
    """
    cur_segs = ss_find_segs(slice_dict=slice_dict, color=color)
    for seg in cur_segs:
        Cell(id="Cell" + str(color) + " " + str(ss_cell_count), starting_slice=0, initial_outline=seg, c_color=color)


def compute_stack(stack_list, color):
    """Runs single-timepoint stack matching for one color across all slices.
    Returns stack-level `Cell` tracks that later feed timepoint-to-timepoint matching.
    """
    global ss_cells
    ss_cells = []
    ss_first_slice_cells(slice_dict=stack_list[0], color=color)
    for slice_num in range(1, len(stack_list)):
        ss_compute_slice(stack_list=stack_list, slice_num=slice_num, color=color)

    return ss_cells


# ============================================================================
# Inlined from processing/pickled_animation_cell_matching.py
# ============================================================================

cell3D_count = 0
cells3D = []
dist_travel_multiplier = 4


class Cell3D:
    def __init__(self, id, starting_tp, initial_cell_obj, c_color):
        """Creates a cross-timepoint cell track from one stack-level cell object and initial 3D center.
        This is the base unit for 4D animation-level matching and quantification.
        """
        self.id = id
        self.color = c_color

        self.starting_tp = starting_tp
        self.final_tp = starting_tp

        self.centers3D = [find_3D_center(initial_cell_obj)]
        self.cells_list = [initial_cell_obj]

        global cell3D_count, cells3D
        cell3D_count += 1
        cells3D.append(self)

    def add_cell(self, new_cell_obj):
        """Appends a newly matched stack-level cell to an existing 4D track and updates its center history.
        Called when adjacent timepoints are linked during animation matching.
        """
        self.final_tp += 1
        self.cells_list.append(new_cell_obj)
        self.centers3D.append(find_3D_center(new_cell_obj))


def find_3D_center(cell_obj):
    """Computes a 3D center for a stack-level cell from all outline points and slice depth.
    This center is the matching key for cross-timepoint linking.
    """
    length = 0
    x_sum, y_sum = 0, 0

    for point_list in cell_obj.outlines:
        length += len(point_list)

        for [x, y] in point_list:
            x_sum += x
            y_sum += y

    z = (cell_obj.top_slice + cell_obj.starting_slice) * 0.5 * (3 / 0.198)
    return (x_sum / length, y_sum / length, z)


def approx_width(cell_obj, axis):
    """Approximates 3D cell extent along `x`, `y`, or `z` from outline geometry.
    Used by cross-timepoint thresholding so movement limits scale with cell size.
    """
    if axis == "x":
        comp = 0
    elif axis == "y":
        comp = 1
    else:
        return len(cell_obj.outlines) * (3 / 0.198)

    res_min = cell_obj.outlines[0][0][comp]
    res_max = cell_obj.outlines[0][1][comp]

    for point_list in cell_obj.outlines:
        for p in point_list:
            val = p[comp]
            if val < res_min:
                res_min = val
            elif val > res_max:
                res_max = val
        return res_max - res_min


def pa_matched_sort_fn(e):
    """Sort key for timepoint-level candidate matches by 3D center distance.
    Used before greedy filtering in animation matching.
    """
    return e[1]


def pa_match_cells(cur_cells, prev_cells):
    """Builds all current-vs-previous timepoint candidate links for one color and sorts by distance.
    This is the candidate generator for 4D track continuation.
    """
    matched_list = []
    for cur_c in cur_cells:
        cur_center = find_3D_center(cur_c)
        for prev_c in prev_cells:
            prev_center = find_3D_center(prev_c)
            matched_list.append([{cur_center: cur_c, prev_center: prev_c}, math.dist(cur_center, prev_center)])
    matched_list.sort(key=pa_matched_sort_fn)
    return matched_list


def pa_remove_pairs(matched_list, center):
    """Removes candidate links containing a tagged 3D center to preserve one-to-one assignments.
    Used by greedy conflict resolution in timepoint matching.
    """
    new_matched_list = []
    for pair in matched_list:
        if center not in pair[0].keys():
            new_matched_list.append(pair)
    return new_matched_list


def pa_find_max_error(cell_obj1, cell_obj2):
    """Computes an adaptive cross-timepoint link threshold from average 3D size estimates.
    Candidate links farther than this threshold are discarded.
    """
    approx_r1 = (approx_width(cell_obj1, "x") + approx_width(cell_obj1, "y") + approx_width(cell_obj1, "z")) / 3
    approx_r2 = (approx_width(cell_obj2, "x") + approx_width(cell_obj2, "y") + approx_width(cell_obj2, "z")) / 3
    return (approx_r1 + approx_r2) * 0.5 * dist_travel_multiplier


def pa_appears_before(matched_list, center, loc):
    """Checks whether a center already appears in earlier selected/considered pairs.
    Supports conflict tagging during greedy pair filtering.
    """
    found = False
    for e in matched_list[:loc]:
        if center in e[0].keys():
            found = True
            break
    return found


def pa_tag_centers(matched_list, center, starting_idx):
    """Tags conflicting centers for removal after choosing a pair at a given index.
    This helps enforce one-to-one mapping across adjacent timepoints.
    """
    tagged = []
    for cur_idx in range(starting_idx, len(matched_list)):
        pair = matched_list[cur_idx]
        c_centers = list(pair[0].keys()).copy()
        if center in c_centers:
            c_centers.remove(center)
            center_pos_tag = c_centers[0]
            if not pa_appears_before(matched_list=matched_list, center=center_pos_tag, loc=cur_idx):
                tagged.append(center_pos_tag)
    return tagged


def pa_filter_pairs(matched_list):
    """Greedily filters timepoint candidate pairs and keeps only links under adaptive motion thresholds.
    The retained links are used to extend `Cell3D` tracks.
    """
    filtered = []
    idx = 0
    while idx < len(matched_list):
        filtered.append(matched_list[idx])

        paired_centers = list(matched_list[idx][0].keys())
        tagged = [paired_centers[0], paired_centers[1]]
        tagged += pa_tag_centers(matched_list=matched_list, center=paired_centers[0], starting_idx=idx + 1)
        tagged += pa_tag_centers(matched_list=matched_list, center=paired_centers[1], starting_idx=idx + 1)

        for center in tagged:
            matched_list = pa_remove_pairs(matched_list=matched_list, center=center)
    new_filtered = []
    for pair in filtered:
        cell_objs = list(pair[0].values())
        max_error = pa_find_max_error(cell_objs[0], cell_objs[1])
        if pair[1] < max_error:
            new_filtered.append(pair)
    return new_filtered


def pa_identify_cell(center, color):
    """Locates the target `Cell3D` object for a prior center/color combination.
    Used when a selected pair indicates a track continuation.
    """
    for c_obj in cells3D:
        if (c_obj.color == color) and (center in c_obj.centers3D):
            return c_obj

    print("No Cell Found with center: ", center)
    return None


def compute_tp(all_raw_cells, tp_num, color):
    """Matches one timepoint against the previous timepoint for a single color and updates/creates `Cell3D` tracks.
    This is the per-timepoint worker in animation-level matching.
    """
    cur_cells = [cell for cell in copy.deepcopy(all_raw_cells[tp_num]) if cell.color == color]
    prev_cells = [cell for cell in copy.deepcopy(all_raw_cells[tp_num - 1]) if cell.color == color]

    if len(cur_cells) == 0:
        print("No cells on current tp (???? should rarely happen lol)")
        return
    if len(prev_cells) == 0:
        for cell_obj in cur_cells:
            Cell3D(
                id=str(cell3D_count) + "_" + str(color) + "_Cell3D",
                starting_tp=tp_num,
                initial_cell_obj=cell_obj,
                c_color=color,
            )
        return

    matched_list = pa_match_cells(cur_cells=cur_cells, prev_cells=prev_cells)
    filtered_list = pa_filter_pairs(matched_list=matched_list)

    for pair in filtered_list:
        cur_cell_obj = list(pair[0].values())[0]
        prev_center = list(pair[0].keys())[1]

        cell_3D_obj = pa_identify_cell(prev_center, color)
        cell_3D_obj.add_cell(new_cell_obj=cur_cell_obj)

        cur_cells.remove(cur_cell_obj)

    for cell_obj in cur_cells:
        print("Cell divided or new cell found, timepoint: ", tp_num)
        Cell3D(
            id=str(cell3D_count) + "_" + str(color) + "_Cell3D",
            starting_tp=tp_num,
            initial_cell_obj=cell_obj,
            c_color=color,
        )


def first_timepoint_cells(first_tp_cells, color):
    """Initializes `Cell3D` tracks from the first timepoint for the selected color.
    Provides starting tracks before iterative timepoint matching.
    """
    for cell in first_tp_cells:
        if cell.color == color:
            Cell3D(
                id=str(cell3D_count) + "_" + str(color) + "_Cell3D",
                starting_tp=0,
                initial_cell_obj=cell,
                c_color=color,
            )


def compute_animation(all_raw_cells, color):
    """Runs full cross-timepoint matching for one color over the entire animation.
    Returns the completed list of 4D cell tracks for that color.
    """
    global cells3D
    cells3D = []
    first_timepoint_cells(first_tp_cells=all_raw_cells[0], color=color)
    for tp in range(1, len(all_raw_cells)):
        compute_tp(all_raw_cells=all_raw_cells, tp_num=tp, color=color)

    print("Number of cells:", cell3D_count)
    return cells3D


def get_raw_cell_data(path, color):
    """Loads wireframe data and computes stack-level cells for one color in each timepoint.
    This prepares per-timepoint inputs for animation-level matching.
    """
    with open(path, "rb") as f:
        _header = f.readline()
        data = pickle.load(f)

    all_raw_cells = []

    for tp in range(0, len(data.keys())):
        cur_cell_objs = compute_stack(stack_list=copy.deepcopy(data[tp]), color=color)
        all_raw_cells.append(cur_cell_objs)

    return all_raw_cells


# ============================================================================
# Inlined from processing/get_matched_cells.py
# ============================================================================

def matched_cell_filter(cell3D):
    """Filters out weak tracks whose per-timepoint outlines are too small/sparse.
    Called before quantification exports to reduce noisy or low-information tracks.
    """
    max_outlines = []
    for single_tp_cell in cell3D.cells_list:
        max_outlines.append(max([len(outline) for outline in single_tp_cell.outlines]))
    return max(max_outlines) > 10


def get_cells3D(path, colors, output_path, tp_path):
    """Builds 4D cell tracks for all selected colors and writes matched-cell intermediates to pickle files.
    This is the expensive matching stage executed before quant metrics and mesh exports.
    """
    print("Matching stacks")
    all_raw_cells = []
    for col in colors:
        print(col, end=" ")
        cur_cells = get_raw_cell_data(path=path, color=col)
        if len(all_raw_cells) == 0:
            all_raw_cells += cur_cells
        else:
            for idx in range(len(all_raw_cells)):
                all_raw_cells[idx] += cur_cells[idx]

    num_tps = len(all_raw_cells)
    print("Number of Timepoints: ", num_tps)

    print("Matching animation")
    cells_3d = []
    for col in colors:
        print(col, end=" ")
        cells_3d += compute_animation(copy.deepcopy(all_raw_cells), col)

    print("\nNumber of cells before filter: ", len(cells_3d))
    scrap_cells = [cell for cell in cells_3d if not matched_cell_filter(cell)]
    cells_3d = [cell for cell in cells_3d if matched_cell_filter(cell)]
    print("After filter: ", len(cells_3d))
    for scrap in scrap_cells:
        print("Scrap cell, ", scrap.color, end=" ")

    with open(output_path, 'wb') as f:
        pickle.dump(cells_3d, f)
    with open(tp_path, 'wb') as f:
        pickle.dump(num_tps, f)


# ============================================================================
# Inlined from processing/pickled_quant_data.py
# ============================================================================

round_decimal_place = 1
num_interp = 20
num_tps = None

tens = -0.75
cont = 0
bias = 0
points_per_segment = 8
include_base_outlines_step = 3
max_outline_points_per_slice = 40

DEFAULT_INPUT_PKL = "For Talk Anim1.pkl"
DEFAULT_COLORS = [
    (0, 255, 255), (0, 0, 255), (0, 120, 10),
    (255, 0, 255), (255, 0, 0), (255, 255, 0),
    (255, 100, 0), (230, 180, 0)
]
DEFAULT_MATCHED_CELLS_PATH = "working_matched_cells.pkl"
DEFAULT_TP_PATH = "working_matched_cells_tp_num.pkl"
DEFAULT_TRACERS_OUTPUT = "For Talk Anim1 TRACERS.pkl"
DEFAULT_QUANT_OUTPUT = "For Talk Anim1 QUANT DATA.csv"
DEFAULT_MESHES_OUTPUT = "For Talk Anim1 SOLIDS.pkl"


# ============================================================================
# Inlined mesh helpers from processing/mesh_creation/*
# ============================================================================

# ---- new_triple_wireframe.py
wf_height = 3 / 0.198


def ntw_find_min_and_width(outline_list):
    """Finds min coordinate and span along the active axis across all outlines.
    Used to define sampling planes for triple-wireframe construction.
    """
    min_val = outline_list[0][0][ntw_comp]
    max_val = outline_list[0][0][ntw_comp]
    for cur_slice in outline_list:
        for coord in cur_slice:
            if coord[ntw_comp] < min_val:
                min_val = coord[ntw_comp]
            elif coord[ntw_comp] > max_val:
                max_val = coord[ntw_comp]
    return min_val, max_val - min_val


def ntw_find_num_wfs(width):
    """Computes how many wireframe planes to generate from object width and target spacing.
    Controls mesh-support wireframe density for each cell snapshot.
    """
    return round(width / ntw_wf_dist) - 1


def ntw_find_planes(min_val, width, num_wfs):
    """Generates evenly spaced plane coordinates centered within the measured width.
    These planes are used to sample candidate min/max points per slice.
    """
    plane_vals = [(width / 2) - (((num_wfs - 1) / 2) * ntw_wf_dist) + min_val]
    for _ in range(num_wfs - 1):
        plane_vals.append(plane_vals[-1] + ntw_wf_dist)
    return plane_vals


def ntw_find_dividing_line(outline):
    """Computes a dividing line in the orthogonal axis for splitting upper/lower path halves.
    Used by sorting helpers when constructing directionally consistent wireframe loops.
    """
    switched_comp = (ntw_comp + 1) % 2
    total = 0
    for coord in outline:
        total += coord[switched_comp]
    return total / len(outline)


def ntw_sort_fn(e):
    """Sort key along the active component axis.
    Used by wireframe point ordering routines.
    """
    return e[ntw_comp]


def ntw_create_sorted_outlines(outline_list):
    """Sorts points and splits each outline around a dividing line into directional halves.
    This is one strategy for preparing outlines before wireframe extraction.
    """
    sorted_outlines = outline_list.copy()
    length = len(sorted_outlines)
    for idx in range(length):
        sorted_outlines[idx].sort(key=ntw_sort_fn)

    for idx in range(length - 1, -1, -1):
        cur_outline = sorted_outlines[idx]
        dividing_line = ntw_find_dividing_line(cur_outline)
        switched_comp = (ntw_comp + 1) % 2
        new_list = []
        i = 0
        while i < len(cur_outline):
            e = cur_outline[i]
            if e[switched_comp] > dividing_line:
                new_list.append(e)
                del cur_outline[i]
            else:
                i += 1
        sorted_outlines.append(new_list)
    return sorted_outlines


def ntw_new_sorted_outlines(outline_list):
    """Duplicates outlines in reverse index order to create mirrored traversal lists.
    The triple-wireframe builder uses this simplified ordering path in current flow.
    """
    sorted_outlines = outline_list.copy()
    length = len(sorted_outlines)
    for idx in range(length - 1, -1, -1):
        sorted_outlines.append(sorted_outlines[idx])
    return sorted_outlines


def ntw_find_point(p_list, plane_val, min_or_max):
    """Finds candidate points near a sampling plane and returns axis-extreme min/max point.
    Used to pick top/bottom wireframe path points for each slice.
    """
    valids = []
    for point in p_list:
        if abs(plane_val - point[ntw_comp]) < ntw_wf_offset:
            valids.append(point)

    if len(valids) == 0:
        return -1

    switched_comp = (ntw_comp + 1) % 2
    extreme = valids[0][switched_comp]
    result = valids[0]

    if min_or_max == "min":
        for point in valids:
            if point[switched_comp] < extreme:
                extreme = point[switched_comp]
                result = point
    else:
        for point in valids:
            if point[switched_comp] > extreme:
                extreme = point[switched_comp]
                result = point
    return result


def ntw_create_wf_list(sorted_outlines, plane_val, z_start):
    """Builds one closed wireframe loop by sampling matching upper/lower points across slices.
    This converts stacked outlines into a mesh-friendly loop with z coordinates.
    """
    wf_list = []
    num_slices = int(len(sorted_outlines) / 2)

    up_dict = {}
    for idx in range(0, num_slices):
        cur_z = z_start + idx * wf_height
        point = ntw_find_point(
            p_list=sorted_outlines[idx],
            plane_val=plane_val,
            min_or_max="min",
        )
        if point == -1:
            continue
        point.append(cur_z)
        up_dict[idx] = point

    down_dict = {}
    for idx in range(num_slices, 2 * num_slices):
        cur_z = z_start + (2 * num_slices - idx - 1) * wf_height
        point = ntw_find_point(
            p_list=sorted_outlines[idx],
            plane_val=plane_val,
            min_or_max="max",
        )
        if point == -1:
            continue
        if len(point) < 3:
            point.append(cur_z)
        down_dict[(2 * num_slices - idx - 1)] = point

    up_list = []
    down_list = []
    for idx in up_dict.keys():
        if idx in down_dict.keys():
            up_list.append(up_dict[idx])
            down_list.append(down_dict[idx])
    wf_list = up_list + down_list[::-1]

    return wf_list


def ntw_triple_wireframe_creation(outline_list, x_or_y, starting_slice, wf_dist_arg, wf_offset_arg):
    """Generates multiple wireframe loops along either x- or y-oriented sampling planes.
    This is the first geometric bridge from contours to volumetric mesh reconstruction.
    """
    global ntw_wf_dist, ntw_wf_offset, ntw_comp
    ntw_wf_dist = wf_dist_arg
    ntw_wf_offset = wf_offset_arg
    ntw_comp = 0
    if x_or_y == "y":
        ntw_comp = 1

    min_val, width = ntw_find_min_and_width(outline_list)
    num_wfs = ntw_find_num_wfs(width)
    plane_vals = ntw_find_planes(min_val, width, num_wfs)
    sorted_outlines = ntw_new_sorted_outlines(outline_list)

    wfs = []
    for val in plane_vals:
        wf_list = ntw_create_wf_list(
            sorted_outlines=sorted_outlines,
            plane_val=val,
            z_start=starting_slice * wf_height,
        )

        if len(wf_list) < 4:
            continue

        wfs.append(wf_list)
    return wfs


# ---- kochanek_bartels_spline_safe.py
def kbs_chord_lengths(P0, P1, P2, P3):
    """Computes cumulative chord-length parameterization for four control points.
    Used by non-uniform Kochanek-Bartels interpolation to stabilize parameter spacing.
    """
    P = [np.array(P0), np.array(P1), np.array(P2), np.array(P3)]
    ts = [0]
    for i in range(1, 4):
        ts.append(ts[-1] + np.linalg.norm(P[i] - P[i - 1]))
    return ts


def kbs_kochanek_bartels_spline_nonuniform(P0, P1, P2, P3, tension=0.0, continuity=0.0, bias=0.0, num_points=1000):
    """Evaluates a non-uniform Kochanek-Bartels spline segment between `P1` and `P2`.
    Cap fitting uses this to infer smooth z values from xz/yz control lines.
    """
    from scipy.interpolate import CubicHermiteSpline

    P0, P1, P2, P3 = map(np.array, [P0, P1, P2, P3])
    ts = kbs_chord_lengths(P0, P1, P2, P3)
    t0, t1, t2, t3 = ts

    if np.isclose(t2, t1):
        u_vals = np.full(num_points, P1[0])
        v_vals = np.full(num_points, P1[1])
        return u_vals, v_vals

    def compute_tangent(P_prev, P_curr, P_next, t_prev, t_curr, t_next, T, C, B, outgoing=True):
        """Computes incoming/outgoing Hermite tangent vectors with tension/continuity/bias controls.
        It is the local derivative helper used by the Kochanek-Bartels segment evaluation.
        """
        dt1 = t_curr - t_prev
        dt2 = t_next - t_curr

        d1 = (P_curr - P_prev) / dt1 if dt1 != 0 else np.zeros(2)
        d2 = (P_next - P_curr) / dt2 if dt2 != 0 else np.zeros(2)

        if outgoing:
            return (1 - T) * (1 + C) * (1 + B) / 2 * d1 + \
                   (1 - T) * (1 - C) * (1 - B) / 2 * d2
        return (1 - T) * (1 - C) * (1 + B) / 2 * d1 + \
               (1 - T) * (1 + C) * (1 - B) / 2 * d2

    T1 = compute_tangent(P0, P1, P2, t0, t1, t2, tension, continuity, bias, outgoing=True)
    T2 = compute_tangent(P1, P2, P3, t1, t2, t3, tension, continuity, bias, outgoing=False)

    t = np.linspace(t1, t2, num_points)
    u_spline = CubicHermiteSpline([t1, t2], [P1[0], P2[0]], [T1[0], T2[0]])
    v_spline = CubicHermiteSpline([t1, t2], [P1[1], P2[1]], [T1[1], T2[1]])

    u_vals = u_spline(t)
    v_vals = v_spline(t)
    return u_vals, v_vals


def kbs_v_for_u_nonuniform(target_u, P0, P1, P2, P3, tension=0.0, continuity=0.0, bias=0.0, tol=1e-0):
    """Samples the non-uniform spline and returns `v` values where sampled `u` is near target.
    Cap-point z estimation uses this inverse lookup against xz/yz splines.
    """
    u_vals, v_vals = kbs_kochanek_bartels_spline_nonuniform(P0, P1, P2, P3, tension, continuity, bias)
    matches = np.abs(u_vals - target_u) < tol
    return v_vals[matches].tolist()


# ---- cap_finder_own_approach.py
cfoa_arches = []


def cfoa_create_arches(XZ_outlines, YZ_outlines, top_or_bottom):
    """Creates `CapArch` containers for every candidate XZ and YZ cap outline.
    This initializes cap-construction bookkeeping before intersection linking.
    """
    for outline in XZ_outlines:
        CapArch(arch=[], XZ_outline=outline, YZ_outline=None, top_or_bottom=top_or_bottom)
    for outline in YZ_outlines:
        CapArch(arch=[], XZ_outline=None, YZ_outline=outline, top_or_bottom=top_or_bottom)


def cfoa_identify_arch(outline, top_or_bottom):
    """Finds the `CapArch` object associated with a specific XZ or YZ outline.
    Used while assigning computed cap points back onto their parent arches.
    """
    for arch in cfoa_arches:
        if arch.top_or_bottom == top_or_bottom and (arch.XZ_outline is outline or arch.YZ_outline is outline):
            return arch
    return None


class CapArch:
    def __init__(self, arch, XZ_outline, YZ_outline, top_or_bottom):
        """Stores arch metadata and registers each arch object in the global cap-arch list.
        Each instance tracks how one outline receives generated cap points.
        """
        self.arch = arch
        self.XZ_outline = XZ_outline
        self.YZ_outline = YZ_outline
        self.top_or_bottom = top_or_bottom

        if XZ_outline is None:
            self.XZ_or_YZ = "YZ"
        elif YZ_outline is None:
            self.XZ_or_YZ = "XZ"

        cfoa_arches.append(self)

    def order_arch(self):
        """Sorts arch points along x or y and flips order for bottom caps.
        This ensures inserted cap segments follow consistent traversal direction.
        """
        if self.XZ_or_YZ == "XZ":
            self.arch = sorted(self.arch, key=lambda e: e[0])
        elif self.XZ_or_YZ == "YZ":
            self.arch = sorted(self.arch, key=lambda e: e[1])
        if self.top_or_bottom == "bottom":
            self.arch.reverse()

    def add_to_outline(self):
        """Inserts ordered arch points into the parent outline to produce a capped contour.
        Called after cap-point generation to create geometry-ready capped outlines.
        """
        if self.XZ_or_YZ == "XZ":
            working_outline = self.XZ_outline
        elif self.XZ_or_YZ == "YZ":
            working_outline = self.YZ_outline
        else:
            return []

        self.order_arch()
        res = []
        if self.top_or_bottom == "top":
            middle = len(working_outline) // 2
            res.extend(working_outline[:middle])
            res.extend(self.arch)
            res.extend(working_outline[middle:])

        if self.top_or_bottom == "bottom":
            res.extend(working_outline)
            res.extend(self.arch)
        return res


def cfoa_find_z(XZ_pts, YZ_pts, intersection, top_or_bottom):
    """Estimates cap-point z by intersecting xz and yz spline predictions at the same xy location.
    This combines both directional constraints to place cap points in 3D.
    """
    XZ_pts = [[pt[0], pt[2]] for pt in XZ_pts]
    z1 = kbs_v_for_u_nonuniform(
        target_u=intersection[0],
        P0=XZ_pts[0], P1=XZ_pts[1], P2=XZ_pts[2], P3=XZ_pts[3],
        tension=cfoa_tens, continuity=cfoa_cont, bias=cfoa_bias
    )
    YZ_pts = [[pt[1], pt[2]] for pt in YZ_pts]
    z2 = kbs_v_for_u_nonuniform(
        target_u=intersection[1],
        P0=YZ_pts[0], P1=YZ_pts[1], P2=YZ_pts[2], P3=YZ_pts[3],
        tension=cfoa_tens, continuity=cfoa_cont, bias=cfoa_bias
    )
    if top_or_bottom == "top":
        z1 = max(z1)
        z2 = max(z2)
    elif top_or_bottom == "bottom":
        z1 = min(z1)
        z2 = min(z2)

    return min(z1, z2)


def cfoa_four_imp_points(outline, top_or_bottom):
    """Selects four local control points near the top or bottom region of an outline.
    These points define local spline context for z interpolation and intersection checks.
    """
    if top_or_bottom == "top":
        middle = len(outline) // 2
        return [outline[middle - 2], outline[middle - 1], outline[middle], outline[middle + 1]]

    if top_or_bottom == "bottom":
        return [outline[-2], outline[-1], outline[0], outline[1]]
    return []


class CapPoint:
    def __init__(self, XZ_line, YZ_line, top_or_bottom, intersection):
        """Builds one cap point from XZ/YZ local control lines, computed intersection, and inferred z value.
        Cap points are later scaled/inserted to close top and bottom mesh boundaries.
        """
        self.XZ_pts = cfoa_four_imp_points(XZ_line, top_or_bottom)
        self.YZ_pts = cfoa_four_imp_points(YZ_line, top_or_bottom)
        self.top_or_bottom = top_or_bottom
        self.intersection = intersection
        self.z = cfoa_find_z(self.XZ_pts, self.YZ_pts, intersection, top_or_bottom)
        self.pos = (intersection[0], intersection[1], self.z)


def cfoa_find_min_max_z(outlines, top_or_bottom):
    """Finds the global top or bottom z level across a set of outlines.
    This identifies which outlines participate in each cap pass.
    """
    all_z = []
    for outline in outlines:
        all_z.extend([pt[2] for pt in outline])

    res = max(all_z)
    if top_or_bottom == "bottom":
        res = min(all_z)

    return res


def cfoa_find_cap_outlines(outlines, cap_lvl):
    """Selects outlines that touch a specified cap z level.
    Only these outlines are considered for cap intersection and arch insertion.
    """
    cap_outlines = []
    for outline in outlines:
        for pt in outline:
            if pt[2] == cap_lvl:
                cap_outlines.append(outline)
                break
    return cap_outlines


def cfoa_find_intersection(XZ_line, YZ_line, top_or_bottom):
    """Computes an xy intersection candidate between local XZ and YZ line segments near cap region.
    Valid intersections seed `CapPoint` generation.
    """
    XZ_two = cfoa_four_imp_points(XZ_line, top_or_bottom)
    YZ_two = cfoa_four_imp_points(YZ_line, top_or_bottom)
    XZ_two = [XZ_two[1], XZ_two[2]]
    YZ_two = [YZ_two[1], YZ_two[2]]

    y = XZ_two[0][1]
    x1, x2 = XZ_two[0][0], XZ_two[1][0]
    x = YZ_two[0][0]
    y1, y2 = YZ_two[0][1], YZ_two[1][1]

    if min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2):
        return [x, y]
    return False


def cfoa_find_limit(outlines, top_or_bottom, cap_lvl):
    """Computes a z limit for cap scaling based on spacing to the adjacent interior slice level.
    Used to clamp cap geometry so extrapolated points stay within reasonable bounds.
    """
    z_wo_top = []
    for outline in outlines:
        z_wo_top.extend([pt[2] for pt in outline if pt[2] != cap_lvl])

    second_top = max(z_wo_top)
    if top_or_bottom == "bottom":
        second_top = min(z_wo_top)

    dist_btwn_slices = abs(second_top - cap_lvl)

    if top_or_bottom == "top":
        return cap_lvl + dist_btwn_slices
    return cap_lvl - dist_btwn_slices


def cfoa_scale(cap_points, cap_lvl, scale_factor):
    """Scales cap-point z offsets relative to cap level by a global factor.
    Applies uniform correction when cap points exceed allowed top/bottom limits.
    """
    for point in cap_points:
        point.z = (point.z - cap_lvl) * scale_factor + cap_lvl


def cfoa_scale_cap_points(cap_points, cap_lvl, limit, top_or_bottom):
    """Determines whether cap-point z values exceed limits and rescales when necessary.
    This keeps generated caps geometrically plausible before insertion.
    """
    max_z = cap_points[0].z
    min_z = cap_points[0].z
    for point in cap_points:
        if point.z > max_z:
            max_z = point.z
        if point.z < min_z:
            min_z = point.z

    if top_or_bottom == "top" and max_z > limit and max_z != cap_lvl:
        scale_factor = abs((limit - cap_lvl) / (max_z - cap_lvl))
        cfoa_scale(cap_points, cap_lvl, scale_factor)

    elif top_or_bottom == "bottom" and min_z < limit and min_z != cap_lvl:
        scale_factor = abs((limit - cap_lvl) / (min_z - cap_lvl))
        cfoa_scale(cap_points, cap_lvl, scale_factor)


def cfoa_execute(all_XZ_outlines, all_YZ_outlines, top_or_bottom="top", tension_arg=0, continuity_arg=0, bias_arg=0):
    """Runs full cap construction for top or bottom: detect cap outlines, find intersections, estimate z, scale, and insert arches.
    The result is capped XZ/YZ wireframe geometry used by spline/mesh stages.
    """
    if len(all_XZ_outlines) == 0 or len(all_YZ_outlines) == 0:
        return [], [], []

    cfoa_arches.clear()

    global cfoa_tens, cfoa_cont, cfoa_bias
    cfoa_tens = tension_arg
    cfoa_cont = continuity_arg
    cfoa_bias = bias_arg

    cap_lvl = cfoa_find_min_max_z(outlines=all_XZ_outlines + all_YZ_outlines, top_or_bottom=top_or_bottom)
    XZ_outlines = cfoa_find_cap_outlines(all_XZ_outlines, cap_lvl)
    YZ_outlines = cfoa_find_cap_outlines(all_YZ_outlines, cap_lvl)

    cfoa_create_arches(XZ_outlines, YZ_outlines, top_or_bottom)

    cap_points = []
    for XZ_line in XZ_outlines:
        XZ_arch = cfoa_identify_arch(XZ_line, top_or_bottom)
        for YZ_line in YZ_outlines:
            intersection = cfoa_find_intersection(XZ_line, YZ_line, top_or_bottom)
            if intersection:
                new_cap_point = CapPoint(copy.deepcopy(XZ_line), copy.deepcopy(YZ_line), top_or_bottom, intersection)

                cap_points.append(new_cap_point)
                YZ_arch = cfoa_identify_arch(YZ_line, top_or_bottom)
                XZ_arch.arch.append(new_cap_point.pos)
                YZ_arch.arch.append(new_cap_point.pos)

    if len(cap_points) == 0:
        XZ_res = []
        YZ_res = []

        for XZ_outline in all_XZ_outlines:
            XZ_res.append(XZ_outline)
        for YZ_outline in all_YZ_outlines:
            YZ_res.append(YZ_outline)

        return cap_points, XZ_res, YZ_res

    limit = cfoa_find_limit(
        outlines=all_XZ_outlines + all_YZ_outlines,
        top_or_bottom=top_or_bottom,
        cap_lvl=cap_lvl,
    )

    cfoa_scale_cap_points(
        cap_points=cap_points,
        cap_lvl=cap_lvl,
        limit=limit,
        top_or_bottom=top_or_bottom,
    )

    XZ_res = []
    YZ_res = []

    for XZ_outline in all_XZ_outlines:
        arch = cfoa_identify_arch(XZ_outline, top_or_bottom)
        if arch is None:
            XZ_res.append(XZ_outline)
        else:
            capped = arch.add_to_outline()
            XZ_res.append(capped)

    for YZ_outline in all_YZ_outlines:
        arch = cfoa_identify_arch(YZ_outline, top_or_bottom)
        if arch is None:
            YZ_res.append(YZ_outline)
        else:
            capped = arch.add_to_outline()
            YZ_res.append(capped)

    return cap_points, XZ_res, YZ_res


# ---- catmull_rom_spline_injecter.py
def csi_catmull_rom_spline(P0, P1, P2, P3, n_points):
    """Computes interpolated points on a Catmull-Rom segment in 3D.
    Used to densify wireframe loops for smoother mesh stitching.
    """
    t = np.linspace(0, 1, n_points + 2)[1:-1]
    points = []
    for tt in t:
        tt2 = tt * tt
        tt3 = tt2 * tt
        x = 0.5 * ((2 * P1[0]) +
                   (-P0[0] + P2[0]) * tt +
                   (2 * P0[0] - 5 * P1[0] + 4 * P2[0] - P3[0]) * tt2 +
                   (-P0[0] + 3 * P1[0] - 3 * P2[0] + P3[0]) * tt3)
        y = 0.5 * ((2 * P1[1]) +
                   (-P0[1] + P2[1]) * tt +
                   (2 * P0[1] - 5 * P1[1] + 4 * P2[1] - P3[1]) * tt2 +
                   (-P0[1] + 3 * P1[1] - 3 * P2[1] + P3[1]) * tt3)
        z = 0.5 * ((2 * P1[2]) +
                   (-P0[2] + P2[2]) * tt +
                   (2 * P0[2] - 5 * P1[2] + 4 * P2[2] - P3[2]) * tt2 +
                   (-P0[2] + 3 * P1[2] - 3 * P2[2] + P3[2]) * tt3)
        points.append([x, y, z])
    return points


def csi_inject_catmull_rom_points(point_list, points_per_segment, top_spline=True):
    """Injects Catmull-Rom samples between consecutive points around a closed loop.
    This increases contour resolution before triangulation while optionally preserving flat cap edges.
    """
    max_z = max([p[2] for p in point_list])
    min_z = min([p[2] for p in point_list])

    n = len(point_list)
    new_points = []
    for i in range(n):
        P0 = point_list[(i - 1) % n]
        P1 = point_list[i]
        P2 = point_list[(i + 1) % n]
        P3 = point_list[(i + 2) % n]
        new_points.append(P1)

        if (top_spline is False) and ((P1[2] == max_z and P2[2] == max_z) or (P1[2] == min_z and P2[2] == min_z)):
            continue

        extra = csi_catmull_rom_spline(P0, P1, P2, P3, points_per_segment)
        new_points.extend(extra)
    return new_points


# ---- cell_point_filler.py
def cpf_point_filler(cell, tens, cont, bias, points_per_segment, top_spline=True, spline=True):
    """Generates xz/yz wireframes, optionally caps and splines them, and returns mesh-ready loops for one cell snapshot.
    This is the main geometry-preparation entry point before surface reconstruction.
    """
    wfsx = ntw_triple_wireframe_creation(
        outline_list=copy.deepcopy(cell.outlines),
        x_or_y="x",
        starting_slice=cell.starting_slice,
        wf_dist_arg=(3 / 0.198) / 5,
        wf_offset_arg=1.5
    )
    wfsy = ntw_triple_wireframe_creation(
        outline_list=copy.deepcopy(cell.outlines),
        x_or_y="y",
        starting_slice=cell.starting_slice,
        wf_dist_arg=(3 / 0.198) / 5,
        wf_offset_arg=1.5
    )

    if not spline:
        wfsx = cpf_spline_and_circuit(wfs=wfsx, points_per_segment=points_per_segment, top_spline=top_spline, spline=False)
        wfsy = cpf_spline_and_circuit(wfs=wfsy, points_per_segment=points_per_segment, top_spline=top_spline, spline=False)
        return wfsx, wfsy

    _, XZ_top_capped, YZ_top_capped = cfoa_execute(
        all_XZ_outlines=wfsy,
        all_YZ_outlines=wfsx,
        top_or_bottom="top",
        tension_arg=tens,
        continuity_arg=cont,
        bias_arg=bias
    )

    _, XZ_capped, YZ_capped = cfoa_execute(
        all_XZ_outlines=XZ_top_capped,
        all_YZ_outlines=YZ_top_capped,
        top_or_bottom="bottom",
        tension_arg=tens,
        continuity_arg=cont,
        bias_arg=bias
    )

    splined_xz = cpf_spline_and_circuit(XZ_capped, points_per_segment=points_per_segment, top_spline=top_spline)
    splined_yz = cpf_spline_and_circuit(YZ_capped, points_per_segment=points_per_segment, top_spline=top_spline)

    return splined_xz, splined_yz


def cpf_spline_and_circuit(wfs, points_per_segment, top_spline, spline=True):
    """Optionally splines each wireframe loop and appends wrap-around points to preserve closed-circuit assumptions.
    Downstream slicing/stitching code expects these loop endings to exist.
    """
    res = []
    for idx in range(len(wfs)):
        if spline:
            splined = csi_inject_catmull_rom_points(copy.deepcopy(wfs[idx]), points_per_segment=points_per_segment, top_spline=top_spline)
        else:
            splined = copy.deepcopy(wfs[idx])
        splined.append(splined[0])
        splined.append(splined[1])
        splined.append(splined[2])
        res.append(splined)

    return res


# ---- contour_stitching_mesh.py
def _resample_outline(outline, num_points):
    """Resamples a closed 2D contour to a fixed point count using arc-length interpolation.
    Mesh builders use this to keep vertex correspondence consistent across contour levels.
    """
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
    """Ensures contour winding is counter-clockwise by checking signed polygon area.
    Consistent winding prevents face-orientation issues during triangulation.
    """
    pts = np.array(outline, dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    area = np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
    if area < 0:
        return pts[::-1].copy()
    return pts


def _align_start(ref, target):
    """Rotates a target contour so its start point aligns with a reference contour start.
    This stabilizes cross-level vertex correspondence for side-wall face stitching.
    """
    dists = np.sqrt(((target - ref[0]) ** 2).sum(axis=1))
    best = np.argmin(dists)
    return np.roll(target, -best, axis=0)


def _smooth_contour(contour, iterations=3, factor=0.5):
    """Applies iterative neighbor averaging to smooth contour noise while preserving closure.
    Mesh reconstruction uses this to reduce jagged surfaces from noisy outlines.
    """
    pts = contour.copy()
    for _ in range(iterations):
        prev = np.roll(pts, 1, axis=0)
        nxt = np.roll(pts, -1, axis=0)
        pts = pts + factor * (0.5 * (prev + nxt) - pts)
    return pts


def _slice_wireframes_at_z(all_wireframes, z_target):
    """Intersects wireframe segments with a target z plane and returns crossing xy points.
    These crossings are used to synthesize contour levels in cap/body interpolation zones.
    """
    crossings = []
    for loop in all_wireframes:
        if len(loop) < 4:
            continue
        n_seg = len(loop) - 3
        for i in range(n_seg):
            z0 = loop[i][2]
            z1 = loop[i + 1][2]
            dz = z1 - z0
            if abs(dz) < 1e-9:
                continue
            if (z0 - z_target) * (z1 - z_target) < 0:
                t = (z_target - z0) / dz
                x = loop[i][0] + t * (loop[i + 1][0] - loop[i][0])
                y = loop[i][1] + t * (loop[i + 1][1] - loop[i][1])
                crossings.append([x, y])
    return crossings


def _crossings_to_contour(crossings, num_points):
    """Orders plane-crossing points by angle around centroid and resamples to a closed contour.
    Converts unordered wireframe intersections into contour levels usable for meshing.
    """
    pts = np.array(crossings, dtype=float)
    centroid = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - centroid[1], pts[:, 0] - centroid[0])
    order = np.argsort(angles)
    sorted_pts = pts[order]
    return _resample_outline(sorted_pts, num_points)


def mesh_from_wireframes(splined_xz, splined_yz, outlines, starting_slice,
                         z_scale=3 / 0.198, num_points=96, interp_per_gap=7,
                         num_cap_levels=5, smooth_iters=3):
    """Builds a closed triangulated mesh by blending original contours, interpolated body contours, and wireframe-derived cap contours.
    This is the preferred high-quality mesh constructor when wireframe generation succeeds.
    """
    import trimesh

    all_wireframes = splined_xz + splined_yz

    if len(all_wireframes) == 0 or len(outlines) < 2:
        return None

    wf_zs = [pt[2] for loop in all_wireframes for pt in loop]
    wf_z_min = min(wf_zs)
    wf_z_max = max(wf_zs)

    num_slices = len(outlines)
    original_zs = [(starting_slice + i) * z_scale for i in range(num_slices)]

    centroids = []
    original_contours = []
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

    z_plan = []

    bot_range = original_zs[0] - wf_z_min
    if bot_range > 0:
        for i in range(1, num_cap_levels + 1):
            frac = i / (num_cap_levels + 1)
            z_plan.append((wf_z_min + frac * bot_range, 'wireframe', None))

    for i in range(num_slices):
        z_plan.append((original_zs[i], 'original', i))
        if i < num_slices - 1:
            gap = original_zs[i + 1] - original_zs[i]
            for j in range(1, interp_per_gap + 1):
                frac = j / (interp_per_gap + 1)
                z_plan.append((original_zs[i] + frac * gap, 'body', (i, i + 1, frac)))

    top_range = wf_z_max - original_zs[-1]
    if top_range > 0:
        for i in range(1, num_cap_levels + 1):
            frac = i / (num_cap_levels + 1)
            z_plan.append((original_zs[-1] + frac * top_range, 'wireframe', None))

    z_plan.sort(key=lambda x: x[0])

    contours = []
    for z, source, data in z_plan:
        if source == 'original':
            contours.append((z, original_contours[data] + centroids[data]))
        elif source == 'body':
            idx_a, idx_b, frac = data
            P1 = original_contours[idx_a]
            P2 = original_contours[idx_b]
            P0 = original_contours[idx_a - 1] if idx_a > 0 else P1
            P3 = original_contours[idx_b + 1] if idx_b < num_slices - 1 else P2
            t = frac
            t2 = t * t
            t3 = t2 * t
            shape = 0.5 * ((2 * P1) +
                           (-P0 + P2) * t +
                           (2 * P0 - 5 * P1 + 4 * P2 - P3) * t2 +
                           (-P0 + 3 * P1 - 3 * P2 + P3) * t3)
            center = (1 - t) * centroids[idx_a] + t * centroids[idx_b]
            contours.append((z, shape + center))
        else:
            crossings = _slice_wireframes_at_z(all_wireframes, z)
            if len(crossings) < 4:
                continue
            contour = _crossings_to_contour(crossings, num_points)
            if smooth_iters > 0:
                contour = _smooth_contour(contour, iterations=smooth_iters)
            contours.append((z, contour))

    if len(contours) < 2:
        return None

    for i in range(1, len(contours)):
        contours[i] = (contours[i][0], _align_start(contours[i - 1][1], contours[i][1]))

    all_verts = []
    all_faces = []
    n = num_points

    for z, contour in contours:
        for pt in contour:
            all_verts.append([pt[0], pt[1], z])

    for i in range(len(contours) - 1):
        a = i * n
        b = (i + 1) * n
        for j in range(n):
            nj = (j + 1) % n
            all_faces.append([a + j, b + j, a + nj])
            all_faces.append([a + nj, b + j, b + nj])

    bot_contour = contours[0][1]
    bot_center = bot_contour.mean(axis=0)
    bot_center_idx = len(all_verts)
    all_verts.append([bot_center[0], bot_center[1], wf_z_min])
    for j in range(n):
        nj = (j + 1) % n
        all_faces.append([j, nj, bot_center_idx])

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


def mesh_from_contours(outlines, starting_slice, num_points=64, z_scale=3 / 0.198, smooth_iters=5):
    """Builds a fallback mesh directly from stacked contours with simple dome-like caps.
    Used when wireframe/spline geometry is insufficient for the primary mesh path.
    """
    import trimesh

    if len(outlines) < 2:
        return None

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

    for i, contour in enumerate(resampled):
        z = (starting_slice + i) * z_scale
        for pt in contour:
            all_verts.append([pt[0], pt[1], z])

    for i in range(len(resampled) - 1):
        a = i * n
        b = (i + 1) * n
        for j in range(n):
            nj = (j + 1) % n
            all_faces.append([a + j, b + j, a + nj])
            all_faces.append([a + nj, b + j, b + nj])

    dome_height = z_scale

    bot_contour = resampled[0]
    bot_center = bot_contour.mean(axis=0)
    bot_z = starting_slice * z_scale

    bot_ring_off = len(all_verts)
    for j in range(n):
        xy = bot_center + 0.5 * (bot_contour[j] - bot_center)
        all_verts.append([xy[0], xy[1], bot_z - 0.5 * dome_height])

    for j in range(n):
        nj = (j + 1) % n
        all_faces.append([j, nj, bot_ring_off + j])
        all_faces.append([nj, bot_ring_off + nj, bot_ring_off + j])

    bot_center_idx = len(all_verts)
    all_verts.append([bot_center[0], bot_center[1], bot_z - dome_height])

    for j in range(n):
        nj = (j + 1) % n
        all_faces.append([bot_ring_off + j, bot_ring_off + nj, bot_center_idx])

    top_contour = resampled[-1]
    top_center = top_contour.mean(axis=0)
    top_z = (starting_slice + len(resampled) - 1) * z_scale
    top_off = (len(resampled) - 1) * n

    top_ring_off = len(all_verts)
    for j in range(n):
        xy = top_center + 0.5 * (top_contour[j] - top_center)
        all_verts.append([xy[0], xy[1], top_z + 0.5 * dome_height])

    for j in range(n):
        nj = (j + 1) % n
        all_faces.append([top_off + nj, top_off + j, top_ring_off + j])
        all_faces.append([top_off + nj, top_ring_off + j, top_ring_off + nj])

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


def get_positions(cell3D):
    """Expands a `Cell3D` center history into a full-length per-timepoint list with `None` gaps.
    Quant export uses this aligned timeline representation for all downstream metrics.
    """
    res = []
    for _ in range(0, cell3D.starting_tp):
        res.append(None)

    res += cell3D.centers3D

    while len(res) < num_tps:
        res.append(None)
    return res


def get_displacement_vecs(positions):
    """Computes per-timepoint displacement vectors from consecutive valid positions.
    Used to derive movement distances and CSV displacement columns.
    """
    res = [None]

    for i in range(1, len(positions)):
        if positions[i - 1] is None or positions[i] is None:
            res.append(None)
        else:
            x = positions[i][0] - positions[i - 1][0]
            y = positions[i][1] - positions[i - 1][1]
            z = positions[i][2] - positions[i - 1][2]
            res.append((x, y, z))
    return res


def get_distance_travelled(displacements):
    """Computes displacement magnitudes from displacement vectors.
    These magnitudes become per-timepoint movement metrics in the quant CSV.
    """
    res = []
    for displ in displacements:
        if displ is None:
            res.append(None)
        else:
            res.append(sum([coord ** 2 for coord in displ]) ** 0.5)
    return res


def round_tuple(tup, place):
    """Rounds numeric tuples to a fixed decimal precision while preserving `None`.
    Used when formatting position/displacement fields for CSV export.
    """
    if tup is None:
        return None
    return tuple(round(elem, place) for elem in tup)


def round_num(num, place):
    """Rounds scalar numeric values while leaving strings/`None` untouched.
    CSV export uses this helper for distance, volume, and area fields.
    """
    if isinstance(num, str):
        return num
    if num is None:
        return None
    return round(num, place)


def quant_cell_filter(cell3D):
    """Applies a minimum-outline-density filter for quantification eligibility.
    Tracks failing this filter are excluded from metric and mesh exports.
    """
    max_outlines = []
    for single_tp_cell in cell3D.cells_list:
        max_outlines.append(max([len(outline) for outline in single_tp_cell.outlines]))
    return max(max_outlines) > 10


def get_solid_mesh_objs(cell3D):
    """Creates one mesh per valid timepoint cell instance using wireframe-first and contour-fallback reconstruction.
    This provides geometry inputs for volume/area metrics and mesh serialization.
    """
    mesh_objs = []

    for _ in range(0, cell3D.starting_tp):
        mesh_objs.append(None)

    for single_tp_cell in cell3D.cells_list:
        if len(single_tp_cell.outlines) <= 1:
            mesh_objs.append(None)
            continue

        try:
            splined_xz, splined_yz = cpf_point_filler(
                cell=copy.deepcopy(single_tp_cell),
                tens=tens,
                cont=cont,
                bias=bias,
                points_per_segment=points_per_segment,
            )
        except Exception:
            splined_xz, splined_yz = [], []

        if len(splined_xz) + len(splined_yz) >= 4:
            mesh = mesh_from_wireframes(
                splined_xz=splined_xz,
                splined_yz=splined_yz,
                outlines=single_tp_cell.outlines,
                starting_slice=single_tp_cell.starting_slice,
            )
        else:
            print("Can't spline Correctly", end="  ")
            mesh = mesh_from_contours(
                outlines=single_tp_cell.outlines,
                starting_slice=single_tp_cell.starting_slice,
            )

        print("Created mesh,", len(mesh.vertices), "vertices") if mesh else None
        mesh_objs.append(mesh)

    while len(mesh_objs) < num_tps:
        mesh_objs.append(None)
    return mesh_objs


def get_volumes(meshes):
    """Computes absolute mesh volumes per timepoint, preserving `None` slots.
    Used by quant CSV export for volumetric metrics.
    """
    res = []

    for mesh in meshes:
        if mesh is None:
            res.append(None)
        else:
            res.append(abs(mesh.volume))
    return res


def get_SAs(meshes):
    """Computes mesh surface area per timepoint, preserving `None` slots.
    Used by quant CSV export for surface-area metrics.
    """
    res = []

    for mesh in meshes:
        if mesh is None:
            res.append(None)
        else:
            res.append(mesh.area)
    return res


def export_csv_data(cells3D_list, output_path, all_meshes=None):
    """Builds and writes the quantitative CSV containing positions, displacements, distances, volume, and surface area.
    This is the primary tabular output consumed by downstream analysis tools.
    """
    data = []
    for cell_idx, cell3D_obj in enumerate(cells3D_list):
        print("\n\nCell ID: ", cell3D_obj.id)
        data.append({"Cell ID": cell3D_obj.id})

        positions = get_positions(cell3D=cell3D_obj)
        displacement_vecs = get_displacement_vecs(positions=positions)
        distances = get_distance_travelled(displacement_vecs)

        meshes = all_meshes[cell_idx] if all_meshes else get_solid_mesh_objs(cell3D=cell3D_obj)
        volumes = get_volumes(meshes=meshes)
        SAs = get_SAs(meshes=meshes)

        for timepoint in range(num_tps):
            pos = round_tuple(tup=positions[timepoint], place=round_decimal_place)
            displ_vec = round_tuple(tup=displacement_vecs[timepoint], place=round_decimal_place)
            dist = round_num(num=distances[timepoint], place=round_decimal_place)

            vol = round_num(num=volumes[timepoint], place=round_decimal_place)
            area = round_num(num=SAs[timepoint], place=round_decimal_place)

            data.append({
                "Timepoint": timepoint,
                "Position": pos,
                "X Pos": pos[0] if pos else None,
                "Y Pos": pos[1] if pos else None,
                "Z Pos": pos[2] if pos else None,
                "Displacement Vector": displ_vec,
                "X Disp": displ_vec[0] if displ_vec else None,
                "Y Disp": displ_vec[1] if displ_vec else None,
                "Z Disp": displ_vec[2] if displ_vec else None,
                "Distance Traveled": dist,
                "Volume": vol,
                "Surface Area": area,
            })

    df = pd.DataFrame(data)
    df.to_csv(output_path, index=False)


def export_solid_meshs(cells3D_list, output_path, min_size=None, all_meshes=None):
    """Serializes per-timepoint mesh vertices/faces/colors into a header-prefixed mesh pickle.
    This is the geometry output for visualization or downstream mesh processing.
    """
    mesh_frames_dict = {}

    for cell_idx, cell3D_obj in enumerate(cells3D_list):
        meshes = all_meshes[cell_idx] if all_meshes else get_solid_mesh_objs(cell3D=copy.deepcopy(cell3D_obj))

        for t, mesh in enumerate(meshes):
            if mesh is None:
                continue

            if min_size is not None and abs(mesh.volume) < min_size:
                continue

            mesh_obj = {
                'vertices': mesh.vertices.tolist(),
                'faces': mesh.faces.tolist(),
                'color': cell3D_obj.color,
                'name': f'cell_{cell_idx}_t{t}',
            }

            if t not in mesh_frames_dict:
                for i in range(t):
                    if i not in mesh_frames_dict:
                        mesh_frames_dict[i] = []
                mesh_frames_dict[t] = []

            mesh_frames_dict[t].append(mesh_obj)

    with open(output_path, 'wb') as f:
        f.write(b"MESH\n")
        pickle.dump(mesh_frames_dict, f)

    print(f"Exported solid mesh data to {output_path}")
    return mesh_frames_dict


def export_tracers(cells3D_list, output_path):
    """Serializes per-color cell trajectories as tracer paths with a `TRACER` header.
    This output is used for trajectory visualization and animation overlays.
    """
    tracers = {}

    for cell_obj in cells3D_list:
        col = cell_obj.color

        positions = [i for i in get_positions(cell_obj) if i is not None]

        if col in tracers:
            tracers[col].append(positions)
        else:
            tracers[col] = [positions]

    with open(output_path, 'wb') as f:
        f.write(b"TRACER\n")
        pickle.dump(tracers, f)

    return tracers


def parse_colors(colors_text):
    """Parses and validates a text literal of RGB tuples.
    Used when colors are supplied explicitly instead of auto-extracted from wireframe data.
    """
    parsed = ast.literal_eval(colors_text)
    if not isinstance(parsed, (list, tuple)):
        raise ValueError("Colors must be a list or tuple of RGB tuples.")

    normalized = []
    for color in parsed:
        if not isinstance(color, (list, tuple)) or len(color) != 3:
            raise ValueError("Each color must contain exactly 3 values: (R, G, B).")
        normalized.append(tuple(color))
    return normalized


def run_quant_pipeline(input_path,
                       colors,
                       matched_cells_path,
                       tp_path,
                       tracers_output,
                       quant_output,
                       meshes_output,
                       match_cells=True):
    """Runs matching intermediates (optional), loads matched tracks, computes meshes/metrics, and writes tracers, CSV, and mesh outputs.
    This is the orchestrator for the full quantification/export stage.
    """
    global num_tps

    if match_cells:
        get_cells3D(path=input_path, colors=colors, output_path=matched_cells_path, tp_path=tp_path)

    with open(matched_cells_path, "rb") as f:
        cells3d_list = pickle.load(f)

    with open(tp_path, "rb") as f:
        num_tps = pickle.load(f)

    print("Tracers")
    export_tracers(cells3D_list=cells3d_list, output_path=tracers_output)

    print("Computing meshes")
    all_meshes = [get_solid_mesh_objs(cell3D=cell3d) for cell3d in cells3d_list]

    print("CSV data")
    export_csv_data(cells3D_list=cells3d_list, output_path=quant_output, all_meshes=all_meshes)

    print("Meshes")
    export_solid_meshs(cells3D_list=cells3d_list, output_path=meshes_output, all_meshes=all_meshes)


# ============================================================================
# Pipeline (adapted from pipeline.py)
# ============================================================================

def resolve_path(path_text):
    """Resolves CLI path text into an absolute path rooted at project directory when relative.
    All pipeline modes use this to keep path handling deterministic.
    """
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


def ensure_parent(path_obj):
    """Creates parent directories for an output path if they do not already exist.
    Called before writing any pipeline artifact.
    """
    path_obj.parent.mkdir(parents=True, exist_ok=True)


def parse_rgb(text_value):
    """Parses an `R,G,B` string into an integer RGB tuple.
    Used for reference/rotation marker color options in outlines mode.
    """
    parts = [p.strip() for p in text_value.split(",")]
    if len(parts) != 3:
        raise ValueError(f"Expected R,G,B format but got: {text_value}")
    return tuple(int(p) for p in parts)


def parse_optional_image_dims(text_value):
    """Parses optional `WIDTH,HEIGHT` CLI text into integer dimensions.
    Outlines mode uses this to override automatic image-size detection.
    """
    if text_value is None:
        return None
    parts = [p.strip() for p in text_value.split(",")]
    if len(parts) != 2:
        raise ValueError(f"Expected WIDTH,HEIGHT format but got: {text_value}")
    return [int(parts[0]), int(parts[1])]


def sorted_dirs(path):
    """Returns subdirectories sorted by name.
    Used wherever deterministic timepoint directory traversal is needed.
    """
    dirs = [p for p in path.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.name)
    return dirs


def strip_profile_args(argv):
    """Removes profiler-only flags from argv before launching the profiled child run.
    Prevents recursive profiling flags and preserves the actual pipeline invocation arguments.
    """
    filtered = []
    idx = 0
    while idx < len(argv):
        arg = argv[idx]

        if arg == "--_profiled-run":
            idx += 1
            continue

        if arg == "--profile-flamegraph":
            idx += 1
            if idx < len(argv) and not argv[idx].startswith("--"):
                idx += 1
            continue
        if arg.startswith("--profile-flamegraph="):
            idx += 1
            continue

        if arg == "--profile-rate":
            idx += 2
            continue
        if arg.startswith("--profile-rate="):
            idx += 1
            continue

        if arg in ("--profile-subprocesses", "--no-profile-subprocesses"):
            idx += 1
            continue

        filtered.append(arg)
        idx += 1

    return filtered


def run_with_pyspy_flamegraph(args):
    """Re-executes the pipeline under `py-spy record` and writes a flamegraph SVG.
    This wraps a normal run so performance can be analyzed without modifying core algorithm logic.
    """
    pyspy_exe = shutil.which("py-spy")
    if pyspy_exe is None:
        raise RuntimeError(
            "py-spy is required for --profile-flamegraph but was not found on PATH. "
            "Install it and rerun."
        )

    flamegraph_output = resolve_path(args.profile_flamegraph)
    ensure_parent(flamegraph_output)

    child_args = strip_profile_args(sys.argv[1:])
    child_args.append("--_profiled-run")

    cmd = [
        pyspy_exe,
        "record",
        "--format",
        "flamegraph",
        "--output",
        str(flamegraph_output),
        "--rate",
        str(args.profile_rate),
    ]
    if args.profile_subprocesses:
        cmd.append("--subprocesses")

    cmd.extend([
        "--",
        args.python,
        str(Path(__file__).resolve()),
    ])
    cmd.extend(child_args)

    print("Running pipeline under py-spy")
    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT)
    print(f"Flamegraph written: {flamegraph_output}")


def run_lexographic_renaming(target_dir):
    """Applies folder and file zero-padding renaming to timepoints and slices.
    This is the outlines-mode preprocessing step for deterministic ordering.
    """
    rename(path=str(target_dir), file_or_folder="folder", name_length="auto")
    for cur_tp in sorted_dirs(target_dir):
        rename(path=str(cur_tp), file_or_folder="file", name_length="auto")


def build_zero_ref_lists(path_to_timepoints):
    """Creates default reference and rotation point lists for all timepoints.
    Used when marker-based point detection is disabled.
    """
    n_timepoints = len(sorted_dirs(path_to_timepoints))
    ref_list = [[0, 0] for _ in range(n_timepoints)]
    rot_list = [[1, 0] for _ in range(n_timepoints)]
    return ref_list, rot_list


def build_ref_lists(path_to_timepoints, image_dims, args):
    """Builds per-timepoint reference/rotation point lists from defaults and optional marker detection flags.
    Outlines conversion calls this before geometry normalization.
    """
    ref_list, rot_list = build_zero_ref_lists(path_to_timepoints)

    if args.find_reference_points:
        ref_color = parse_rgb(args.reference_point_color)
        ref_list = find_ref_points_multiple_slices(
            path_to_timepoints=str(path_to_timepoints),
            reference_point_color=ref_color,
            image_dimensions=image_dims,
        )

    if args.find_rotation_points:
        rot_color = parse_rgb(args.rotation_point_color)
        rot_list = find_ref_points_multiple_slices(
            path_to_timepoints=str(path_to_timepoints),
            reference_point_color=rot_color,
            image_dimensions=image_dims,
        )

    return ref_list, rot_list


def outlines_to_wireframe_pickle(args, wireframe_pkl):
    """Runs outlines-mode preprocessing/formatting and writes the resulting `WIREFRAME` pickle.
    This is the mode entrypoint that converts manually outlined images into pipeline wireframe data.
    """
    outlines_dir = resolve_path(args.outlines_dir)
    if not outlines_dir.exists():
        raise FileNotFoundError(f"Outlines directory not found: {outlines_dir}")

    if not args.skip_lexographic_renaming:
        print("Running lexographic renaming on outlines directory")
        run_lexographic_renaming(outlines_dir)

    image_dims = parse_optional_image_dims(args.image_dims)
    if image_dims is None:
        image_dims = find_image_dimensions(path_to_timepoints=str(outlines_dir))

    ref_list, rot_list = build_ref_lists(outlines_dir, image_dims, args)

    frame_dict, manual_time_taken = prepare_manual_data(
        path_to_timepoints=str(outlines_dir),
        reference_point_list=ref_list,
        rotation_point_list=rot_list,
        image_dimensions=image_dims,
        sort_large_groups=not args.no_sort_large_groups,
        rotate=args.rotate,
    )
    print(f"Manual data formatting time taken: {manual_time_taken}")

    ensure_parent(wireframe_pkl)
    with open(wireframe_pkl, "wb") as f:
        f.write(b"WIREFRAME\n")
        pickle.dump(frame_dict, f)
    print(f"Wireframe pickle written: {wireframe_pkl}")


def default_segmentation_json_path(images_dir, segmentation_output_dir, model_name):
    """Constructs the default RAW animation JSON path from images directory name and model name.
    Used when no explicit segmentation JSON output path is passed.
    """
    model_safe = model_name.replace("-", "_")
    return segmentation_output_dir / f"{images_dir.name}_{model_safe}_raw.json"


def run_image_segmentation(args):
    """Validates image inputs, runs segmentation, and returns the produced RAW animation JSON path.
    This is the segmentation substage used by `images` mode before wireframe conversion.
    """
    images_dir = resolve_path(args.images_dir)
    if not images_dir.exists():
        raise FileNotFoundError(f"Images directory not found: {images_dir}")

    segmentation_output_dir = resolve_path(args.segmentation_output_dir)
    segmentation_output_dir.mkdir(parents=True, exist_ok=True)

    animation_json = resolve_path(args.segmentation_animation_json) if args.segmentation_animation_json else None

    print("Running segmentation")
    run_segmentation_to_json(
        input_root=images_dir,
        output_root=segmentation_output_dir,
        model=args.segmentation_model,
        device=args.segmentation_device,
        diameter=args.segmentation_diameter,
        min_area=args.segmentation_min_area,
        z_spacing=args.segmentation_z_spacing,
        animation_json=animation_json,
    )

    if args.segmentation_animation_json:
        return resolve_path(args.segmentation_animation_json)
    return default_segmentation_json_path(
        images_dir=images_dir,
        segmentation_output_dir=segmentation_output_dir,
        model_name=args.segmentation_model,
    )


def parse_color_from_arc_key(raw_key):
    """Extracts RGB tuple values from ARC-style JSON keys such as `[r, g, b]#Llabel`.
    Images-mode wireframe conversion uses this to rebuild color-grouped slice dictionaries.
    """
    match = re.search(r"\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]", raw_key)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def images_to_wireframe_pickle(args, wireframe_pkl):
    """Runs segmentation-to-RAW (or loads provided RAW), converts payload points to XY outlines, and writes `WIREFRAME` pickle.
    This is the `images` mode bridge from model output to standard wireframe format.
    """
    animation_json = run_image_segmentation(args)
    if not animation_json.exists():
        raise FileNotFoundError(f"Segmentation animation JSON not found: {animation_json}")

    with open(animation_json, "r", encoding="utf-8") as f:
        parsed = json.load(f)
    payload = parsed.get("payload", {})
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError(f"Animation JSON payload is missing/empty: {animation_json}")

    frame_dict = {}
    tp_keys = sorted(payload.keys(), key=parse_int_token)
    for output_tp_idx, tp_key in enumerate(tp_keys):
        stack_list = []
        for slice_dict in payload[tp_key]:
            new_slice_dict = {}
            for raw_color, groups in slice_dict.items():
                color = parse_color_from_arc_key(raw_color)
                if color is None:
                    continue
                converted_groups = []
                for group in groups:
                    converted = [[float(point[0]), float(point[1])] for point in group if len(point) >= 2]
                    if len(converted) >= 3:
                        converted_groups.append(converted)
                if converted_groups:
                    if color in new_slice_dict:
                        new_slice_dict[color] += converted_groups
                    else:
                        new_slice_dict[color] = converted_groups
            stack_list.append(new_slice_dict)
        frame_dict[output_tp_idx] = stack_list

    if len(frame_dict) == 0:
        raise RuntimeError("No wireframe frames were generated from the segmentation payload.")

    ensure_parent(wireframe_pkl)
    with open(wireframe_pkl, "wb") as f:
        f.write(b"WIREFRAME\n")
        pickle.dump(frame_dict, f)
    print(f"Wireframe pickle written: {wireframe_pkl}")


def run_quantification(args, wireframe_pkl):
    """Resolves quant output paths, extracts colors from wireframe data, and executes the quant pipeline.
    Main mode orchestration calls this when `--run-quant` is enabled.
    """
    tracers_output = resolve_path(args.tracers_output) if args.tracers_output else wireframe_pkl.with_name(
        f"{wireframe_pkl.stem} TRACERS.pkl"
    )
    quant_output = resolve_path(args.quant_output) if args.quant_output else wireframe_pkl.with_name(
        f"{wireframe_pkl.stem} QUANT DATA.csv"
    )
    meshes_output = resolve_path(args.meshes_output) if args.meshes_output else wireframe_pkl.with_name(
        f"{wireframe_pkl.stem} SOLIDS.pkl"
    )
    matched_cells_path = resolve_path(args.matched_cells_path) if args.matched_cells_path else wireframe_pkl.with_name(
        "working_matched_cells.pkl"
    )
    tp_path = resolve_path(args.tp_path) if args.tp_path else wireframe_pkl.with_name(
        "working_matched_cells_tp_num.pkl"
    )

    for output_path in [tracers_output, quant_output, meshes_output, matched_cells_path, tp_path]:
        ensure_parent(output_path)

    print("Extracting colors from wireframe pickle")
    _, parsed_data = get_data(file_path=str(wireframe_pkl))
    extracted_colors = extract(dict_data=parsed_data, skip_slice=args.skip_slice)
    print(f"Extracted {len(extracted_colors)} colors")
    if not extracted_colors:
        raise RuntimeError("No colors were extracted from the wireframe pickle. Aborting quantification step.")

    print("Running quantification")
    run_quant_pipeline(
        input_path=str(wireframe_pkl),
        colors=extracted_colors,
        matched_cells_path=str(matched_cells_path),
        tp_path=str(tp_path),
        tracers_output=str(tracers_output),
        quant_output=str(quant_output),
        meshes_output=str(meshes_output),
        match_cells=not args.skip_match_cells,
    )
    print("Quantification complete")
    print(f"Tracers: {tracers_output}")
    print(f"Quant CSV: {quant_output}")
    print(f"Meshes: {meshes_output}")


def build_arg_parser():
    """Defines CLI arguments for mode selection, segmentation, quant outputs, and profiling controls.
    This is the single command-line interface contract for the unified pipeline script.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Single-file full pipeline for generating wireframe pickle data and optional quant outputs.\n"
            "Modes:\n"
            "- existing: use an existing wireframe .pkl\n"
            "- outlines: generate wireframe .pkl from outline images\n"
            "- images: segment images then generate wireframe .pkl from ARC RAW json"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["existing", "outlines", "images"],
        default="existing",
        help="Pipeline input mode.",
    )
    parser.add_argument(
        "--wireframe-pkl",
        default="./output/wireframe.pkl",
        help="Output wireframe .pkl path (or existing input path in existing mode).",
    )
    parser.add_argument(
        "--run-quant",
        action="store_true",
        help="After wireframe generation/load, run quant export.",
    )
    parser.add_argument(
        "--profile-flamegraph",
        nargs="?",
        const="./output/full_pipeline_flamegraph.svg",
        default=None,
        help="Run the pipeline under py-spy and write a flamegraph SVG (default path if omitted).",
    )
    parser.add_argument(
        "--profile-rate",
        type=int,
        default=100,
        help="Sampling rate for py-spy flamegraph profiling.",
    )
    parser.add_argument(
        "--profile-subprocesses",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include Python subprocesses in py-spy profiling when supported.",
    )
    parser.add_argument(
        "--_profiled-run",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    parser.add_argument("--tracers-output", default=None, help="Output path for tracers .pkl.")
    parser.add_argument("--quant-output", default=None, help="Output path for quant CSV.")
    parser.add_argument("--meshes-output", default=None, help="Output path for meshes .pkl.")
    parser.add_argument("--matched-cells-path", default=None, help="Intermediate matched cells .pkl path.")
    parser.add_argument("--tp-path", default=None, help="Intermediate timepoint-count .pkl path.")
    parser.add_argument("--skip-slice", type=int, default=0, help="Color extractor skip_slice argument.")
    parser.add_argument("--skip-match-cells", action="store_true", help="Reuse existing matched cell files.")

    parser.add_argument("--outlines-dir", default=None, help="Root directory containing t1/t2/... outline image folders.")
    parser.add_argument("--skip-lexographic-renaming", action="store_true", help="Skip renaming pass in outlines mode.")
    parser.add_argument("--image-dims", default=None, help="Image dimensions as WIDTH,HEIGHT.")
    parser.add_argument("--find-reference-points", action="store_true", help="Detect reference points from colored markers.")
    parser.add_argument("--find-rotation-points", action="store_true", help="Detect rotation points from colored markers.")
    parser.add_argument("--reference-point-color", default="255,255,0", help="Reference point marker color as R,G,B.")
    parser.add_argument("--rotation-point-color", default="0,255,0", help="Rotation point marker color as R,G,B.")
    parser.add_argument("--rotate", action="store_true", help="Enable rotation in outline->pickle conversion.")
    parser.add_argument("--no-sort-large-groups", action="store_true", help="Disable large-group sorting in formatter.")

    parser.add_argument("--images-dir", default=None, help="Root directory of source images for segmentation.")
    parser.add_argument("--segmentation-output-dir", default="./output/segmentation", help="Output root for segmentation artifacts.")
    parser.add_argument("--segmentation-model", choices=["cellpose", "cellpose-sam", "cellsam"], default="cellpose")
    parser.add_argument("--segmentation-device", choices=["auto", "cpu", "gpu"], default="auto")
    parser.add_argument("--segmentation-diameter", type=float, default=0.0)
    parser.add_argument("--segmentation-min-area", type=int, default=25)
    parser.add_argument("--segmentation-z-spacing", type=float, default=DEFAULT_Z_SPACING)
    parser.add_argument("--segmentation-animation-json", default=None, help="Optional explicit path for segmentation RAW JSON.")

    parser.add_argument("--python", default=sys.executable, help="Python executable used for py-spy child rerun.")
    return parser


def main():
    """Parses CLI arguments, handles optional profiling rerun, dispatches by mode to create/validate wireframe data, and optionally runs quantification.
    This is the top-level entrypoint for every pipeline execution path.
    """
    args = build_arg_parser().parse_args()

    if args.profile_flamegraph and not args._profiled_run:
        run_with_pyspy_flamegraph(args)
        return

    wireframe_pkl = resolve_path(args.wireframe_pkl)

    if args.mode == "existing":
        if not wireframe_pkl.exists():
            raise FileNotFoundError(f"Wireframe .pkl not found: {wireframe_pkl}")
    elif args.mode == "outlines":
        if not args.outlines_dir:
            raise ValueError("--outlines-dir is required in --mode outlines")
        outlines_to_wireframe_pickle(args, wireframe_pkl)
    elif args.mode == "images":
        if not args.images_dir:
            raise ValueError("--images-dir is required in --mode images")
        images_to_wireframe_pickle(args, wireframe_pkl)

    print(f"Wireframe ready: {wireframe_pkl}")
    if args.run_quant:
        run_quantification(args, wireframe_pkl)
    else:
        print("Skipping quantification. Use --run-quant to enable it.")


if __name__ == "__main__":
    main()
