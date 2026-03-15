#!/usr/bin/env python3
"""Standalone outlines-to-4D cell matching pipeline.

This script isolates the portion of the unified pipeline that converts manual
outline images into 4D matched cell objects (`Cell3D`).

Flow:
1. Optional lexographic renaming for deterministic folder/file order.
2. Outline image parsing into wireframe-like frame dictionaries.
3. Color extraction (or explicit color list).
4. Single-stack matching (slice-to-slice) -> `Cell` objects.
5. Animation matching (timepoint-to-timepoint) -> `Cell3D` objects.
6. Write matched 4D cells and timepoint count pickle outputs.
"""

import argparse
import ast
import copy
import math
import os
import pickle
import time
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Inlined from processing/translators/lexographic_renaming.py
# ---------------------------------------------------------------------------

def rename(path, file_or_folder, name_length):
    """Pad numeric portions of names with leading zeros for stable lexical order."""
    if file_or_folder == "file":
        items = [f.path for f in os.scandir(path) if f.is_file()]
    elif file_or_folder == "folder":
        items = [f.path for f in os.scandir(path) if f.is_dir()]
    else:
        print("file_or_folder not inputted correctly")
        return

    if name_length == "auto":
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
                    new_name.insert(i, "0")
                break
        new_name = "".join(new_name)
        os.rename(os.path.normpath(path) + "/" + cur_name, os.path.normpath(path) + "/" + new_name)


# ---------------------------------------------------------------------------
# Inlined from processing/translators/formatting_preparation.py
# ---------------------------------------------------------------------------

def find_image_dimensions(path_to_timepoints):
    """Read width/height from the first image in the first timepoint directory."""
    timepoint_folders = sorted([f.path for f in os.scandir(path_to_timepoints) if f.is_dir()])
    tp1_images = sorted([f.path for f in os.scandir(timepoint_folders[0]) if f.is_file()])
    img1_path = tp1_images[0]

    sample_img = Image.open(img1_path)
    width, height = sample_img.size
    print("Image dimensions: " + str(width) + ", " + str(height))
    return [width, height]


def find_ref_points_multiple_slices(path_to_timepoints, reference_point_color, image_dimensions):
    """Average marker-color pixels into one reference point per timepoint."""
    timepoint_folders = sorted([f.path for f in os.scandir(path_to_timepoints) if f.is_dir()])
    print("Finding reference points on timepoints: ", end="")
    width, height = image_dimensions[0], image_dimensions[1]
    reference_point_list = []

    n_timepoints = len(timepoint_folders)

    for tp_num in range(n_timepoints):
        print(str(tp_num + 1) + " ", end="")

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
            reference_point_list.append(
                [
                    int(sum(reference_cell_x) / len(reference_cell_x)),
                    int(sum(reference_cell_y) / len(reference_cell_y)),
                ]
            )
        else:
            print("No reference point found on timepoint t" + str(tp_num + 1))
            reference_point_list.append([0, 0])
    print("\n")

    return reference_point_list


# ---------------------------------------------------------------------------
# Inlined from processing/translators/adjust_algorithm.py
# ---------------------------------------------------------------------------

def adjust_group(group, reference_point, rotation_point, should_rotate):
    """Translate a point group by reference and optionally rotate by rotation marker."""
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


# ---------------------------------------------------------------------------
# Inlined from processing/translators/sort_robust_outline.py
# ---------------------------------------------------------------------------

def _distance_sq(p1, p2):
    """Squared Euclidean distance helper."""
    return (p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2


def _ccw(A, B, C):
    """Return whether A->B->C is counter-clockwise."""
    return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])


def _segments_intersect(A, B, C, D):
    """Segment intersection test used by 2-opt."""
    return _ccw(A, C, D) != _ccw(B, C, D) and _ccw(A, B, C) != _ccw(A, B, D)


def _nearest_neighbor_order(points):
    """Create initial point visit order using nearest-neighbor traversal."""
    n = len(points)
    visited = [False] * n
    order = [0]
    visited[0] = True

    for _ in range(n - 1):
        cur = order[-1]
        best_sq = float("inf")
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
    """Remove path self-intersections by iterative 2-opt edge reversals."""
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
                    order[i + 1 : j + 1] = order[i + 1 : j + 1][::-1]
                    improved = True
    return order


def robust_sort_group(group):
    """Sort a contour group into a stable traversal order."""
    if len(group) <= 3:
        return list(group)

    order = _nearest_neighbor_order(group)
    order = _two_opt(group, order)
    return [group[i] for i in order]


# ---------------------------------------------------------------------------
# Inlined from processing/translators/v10manual_segmentation_formatter.py
# ---------------------------------------------------------------------------

VF_sparse = True
VF_should_rotate = False
VF_width, VF_height = 0, 0
VF_timepoint_folders = []


def vf_get_surrounding_colored_points(pix, point_coords, color, loose):
    """Return neighboring same-color pixels around one coordinate."""
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
    """Grow a full connected same-color component from one seed pixel."""
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
    """Append a contour group under its color key in the per-slice map."""
    if color in data_dict.keys():
        data_dict[color].append(group)
    else:
        data_dict[color] = [group]


def vf_sorted_group(group, reference_point, rotation_point, color):
    """Order and normalize one component into export-ready contour coordinates."""
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
    """Parse one outline image into `{color: [outlines...]}` format."""
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
    """Parse all slices in one timepoint directory."""
    cur_path = VF_timepoint_folders[timepoint]
    print("\nFormatting stack " + os.path.basename(os.path.normpath(cur_path)))
    slice_images = sorted([f.path for f in os.scandir(cur_path) if f.is_file()])

    stack_list = []
    for slice_num in range(len(slice_images)):
        cur_slice = vf_format_slice(
            slice_path=slice_images[slice_num],
            reference_point=reference_point,
            rotation_point=rotation_point,
        )
        stack_list.append(cur_slice)
    return stack_list


def prepare_manual_data(path_to_timepoints, reference_point_list, rotation_point_list, image_dimensions, sort_large_groups, rotate):
    """Convert all timepoint outline images into the frame dictionary used by matching."""
    _ = sort_large_groups  # Preserved for compatibility with upstream flags.

    global VF_should_rotate
    VF_should_rotate = rotate

    start_manual_time = time.time()
    print("Preparing Manual Data")

    global VF_width, VF_height
    VF_width, VF_height = image_dimensions[0], image_dimensions[1]

    global VF_timepoint_folders
    VF_timepoint_folders = sorted([f.path for f in os.scandir(path_to_timepoints) if f.is_dir()])

    frame_dict = {}
    for tp_num in range(len(VF_timepoint_folders)):
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


# ---------------------------------------------------------------------------
# Inlined from processing/translators/color_extractor.py
# ---------------------------------------------------------------------------

MIN_LENGTH = 14


def extract(dict_data, skip_slice=0):
    """Extract colors with sufficiently long outlines from frame data."""
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


# ---------------------------------------------------------------------------
# Inlined from processing/single_stack_cell_matching.py
# ---------------------------------------------------------------------------

ss_cell_count = 0
ss_cells = []
DIST_MULTIPLIER = 0.7


class Cell:
    """Cell track within a single timepoint stack (slice-linked)."""

    def __init__(self, id, starting_slice, initial_outline, c_color):
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
        self.top_slice += 1
        self.outlines.append(new_outline)
        self.centers.append(ss_find_center(new_outline))


def ss_find_center(point_list):
    """Compute centroid for one 2D outline."""
    length = len(point_list)
    if length == 0:
        return None

    x_sum, y_sum = 0, 0
    for [x, y] in point_list:
        x_sum += x
        y_sum += y
    return (x_sum / length, y_sum / length)


def ss_approx_width(point_list, x_or_y):
    """Approximate x/y extent of one outline."""
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
    """Return all segments for one color from a slice dictionary."""
    if color not in slice_dict.keys():
        return []
    return slice_dict[color].copy()


def ss_matched_sort_fn(e):
    """Sort key for candidate links by distance."""
    return e[1]


def ss_match_cells(cur_cells, prev_cells):
    """Build and sort all pair candidates between current and previous slice segments."""
    matched_list = []
    for cur_c in cur_cells:
        cur_center = ss_find_center(cur_c)
        for prev_c in prev_cells:
            prev_center = ss_find_center(prev_c)
            matched_list.append([{cur_center: cur_c, prev_center: prev_c}, math.dist(cur_center, prev_center)])
    matched_list.sort(key=ss_matched_sort_fn)
    return matched_list


def ss_remove_pairs(matched_list, center):
    """Drop candidate pairs that involve a tagged center."""
    new_matched_list = []
    for pair in matched_list:
        if center not in pair[0].keys():
            new_matched_list.append(pair)
    return new_matched_list


def ss_find_max_error(point_list1, point_list2):
    """Adaptive maximum distance threshold for accepting a slice link."""
    approx_r1 = max([ss_approx_width(point_list1, "x"), ss_approx_width(point_list1, "y")])
    approx_r2 = max([ss_approx_width(point_list2, "x"), ss_approx_width(point_list2, "y")])
    return max(approx_r1, approx_r2) * DIST_MULTIPLIER


def ss_appears_before(matched_list, center, loc):
    """Check whether center already appears in earlier candidate pairs."""
    found = False
    for e in matched_list[:loc]:
        if center in e[0].keys():
            found = True
            break
    return found


def ss_tag_centers(matched_list, center, starting_idx):
    """Tag conflicting centers after selecting one candidate pair."""
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
    """Greedy one-to-one pairing with adaptive threshold rejection."""
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
    """Find existing stack-level Cell object by center and color."""
    for c_obj in ss_cells:
        if (c_obj.color == color) and (center in c_obj.centers):
            return c_obj

    print("No Cell Found with center: ", center)
    return None


def ss_compute_slice(stack_list, slice_num, color):
    """Match one slice to its previous slice and update/create Cell tracks."""
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
    """Initialize stack-level Cell objects from first slice segments."""
    cur_segs = ss_find_segs(slice_dict=slice_dict, color=color)
    for seg in cur_segs:
        Cell(id="Cell" + str(color) + " " + str(ss_cell_count), starting_slice=0, initial_outline=seg, c_color=color)


def compute_stack(stack_list, color):
    """Run slice-to-slice matching for one color in one timepoint stack."""
    global ss_cells
    ss_cells = []
    ss_first_slice_cells(slice_dict=stack_list[0], color=color)
    for slice_num in range(1, len(stack_list)):
        ss_compute_slice(stack_list=stack_list, slice_num=slice_num, color=color)

    return ss_cells


# ---------------------------------------------------------------------------
# Inlined from processing/pickled_animation_cell_matching.py
# ---------------------------------------------------------------------------

cell3D_count = 0
cells3D = []
dist_travel_multiplier = 4


class Cell3D:
    """Cell track across timepoints (4D object used by downstream quant/mesh)."""

    def __init__(self, id, starting_tp, initial_cell_obj, c_color):
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
        self.final_tp += 1
        self.cells_list.append(new_cell_obj)
        self.centers3D.append(find_3D_center(new_cell_obj))


def find_3D_center(cell_obj):
    """Compute 3D center from all outline points and z from slice range."""
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
    """Approximate cell span along x/y/z for thresholding."""
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
    """Sort key for timepoint pair candidates by distance."""
    return e[1]


def pa_match_cells(cur_cells, prev_cells):
    """Build and sort all pair candidates between adjacent timepoints."""
    matched_list = []
    for cur_c in cur_cells:
        cur_center = find_3D_center(cur_c)
        for prev_c in prev_cells:
            prev_center = find_3D_center(prev_c)
            matched_list.append([{cur_center: cur_c, prev_center: prev_c}, math.dist(cur_center, prev_center)])
    matched_list.sort(key=pa_matched_sort_fn)
    return matched_list


def pa_remove_pairs(matched_list, center):
    """Drop candidate links containing a tagged center."""
    new_matched_list = []
    for pair in matched_list:
        if center not in pair[0].keys():
            new_matched_list.append(pair)
    return new_matched_list


def pa_find_max_error(cell_obj1, cell_obj2):
    """Adaptive movement threshold for cross-timepoint linking."""
    approx_r1 = (approx_width(cell_obj1, "x") + approx_width(cell_obj1, "y") + approx_width(cell_obj1, "z")) / 3
    approx_r2 = (approx_width(cell_obj2, "x") + approx_width(cell_obj2, "y") + approx_width(cell_obj2, "z")) / 3
    return (approx_r1 + approx_r2) * 0.5 * dist_travel_multiplier


def pa_appears_before(matched_list, center, loc):
    """Check whether center appears earlier in candidate list."""
    found = False
    for e in matched_list[:loc]:
        if center in e[0].keys():
            found = True
            break
    return found


def pa_tag_centers(matched_list, center, starting_idx):
    """Tag conflicting centers after selecting one timepoint pair."""
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
    """Greedy one-to-one filtering plus adaptive threshold for timepoint links."""
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
    """Find existing Cell3D by center and color."""
    for c_obj in cells3D:
        if (c_obj.color == color) and (center in c_obj.centers3D):
            return c_obj

    print("No Cell Found with center: ", center)
    return None


def compute_tp(all_raw_cells, tp_num, color):
    """Match one timepoint against previous for one color and update Cell3D tracks."""
    cur_cells = [cell for cell in copy.deepcopy(all_raw_cells[tp_num]) if cell.color == color]
    prev_cells = [cell for cell in copy.deepcopy(all_raw_cells[tp_num - 1]) if cell.color == color]

    if len(cur_cells) == 0:
        print("No cells on current tp")
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
        Cell3D(
            id=str(cell3D_count) + "_" + str(color) + "_Cell3D",
            starting_tp=tp_num,
            initial_cell_obj=cell_obj,
            c_color=color,
        )


def first_timepoint_cells(first_tp_cells, color):
    """Initialize Cell3D tracks from first timepoint cells."""
    for cell in first_tp_cells:
        if cell.color == color:
            Cell3D(
                id=str(cell3D_count) + "_" + str(color) + "_Cell3D",
                starting_tp=0,
                initial_cell_obj=cell,
                c_color=color,
            )


def compute_animation(all_raw_cells, color):
    """Run full cross-timepoint matching for one color."""
    global cells3D
    cells3D = []
    first_timepoint_cells(first_tp_cells=all_raw_cells[0], color=color)
    for tp in range(1, len(all_raw_cells)):
        compute_tp(all_raw_cells=all_raw_cells, tp_num=tp, color=color)

    return cells3D


# ---------------------------------------------------------------------------
# Inlined from processing/get_matched_cells.py (adapted for in-memory data)
# ---------------------------------------------------------------------------

def matched_cell_filter(cell3D):
    """Filter tracks that are too small/sparse for robust downstream use."""
    max_outlines = []
    for single_tp_cell in cell3D.cells_list:
        max_outlines.append(max([len(outline) for outline in single_tp_cell.outlines]))
    return max(max_outlines) > 10


def get_raw_cell_data_from_frame_dict(frame_dict, color):
    """Compute per-timepoint stack-level cells for one color from frame dictionary."""
    all_raw_cells = []
    for tp in sorted(frame_dict.keys()):
        cur_cell_objs = compute_stack(stack_list=copy.deepcopy(frame_dict[tp]), color=color)
        all_raw_cells.append(cur_cell_objs)
    return all_raw_cells


def get_cells3D_from_frame_dict(frame_dict, colors, apply_filter=True):
    """Build 4D Cell3D objects from frame_dict for all target colors."""
    print("Matching stacks")
    all_raw_cells = []
    for col in colors:
        print(col, end=" ")
        cur_cells = get_raw_cell_data_from_frame_dict(frame_dict=frame_dict, color=col)
        if len(all_raw_cells) == 0:
            all_raw_cells += cur_cells
        else:
            for idx in range(len(all_raw_cells)):
                all_raw_cells[idx] += cur_cells[idx]

    num_tps = len(all_raw_cells)
    print("\nNumber of Timepoints: ", num_tps)

    print("Matching animation")
    cells_3d = []
    for col in colors:
        print(col, end=" ")
        cells_3d += compute_animation(copy.deepcopy(all_raw_cells), col)

    print("\nNumber of cells before filter: ", len(cells_3d))
    if apply_filter:
        scrap_cells = [cell for cell in cells_3d if not matched_cell_filter(cell)]
        cells_3d = [cell for cell in cells_3d if matched_cell_filter(cell)]
        print("After filter: ", len(cells_3d))
        for scrap in scrap_cells:
            print("Scrap cell, ", scrap.color, end=" ")
        print("")

    return cells_3d, num_tps


# ---------------------------------------------------------------------------
# Orchestration helpers
# ---------------------------------------------------------------------------

def resolve_path(path_text):
    """Resolve relative paths against this script's directory."""
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


def ensure_parent(path_obj):
    """Ensure parent directory exists before writing output."""
    path_obj.parent.mkdir(parents=True, exist_ok=True)


def parse_rgb(text_value):
    """Parse R,G,B string into integer tuple."""
    parts = [p.strip() for p in text_value.split(",")]
    if len(parts) != 3:
        raise ValueError(f"Expected R,G,B format but got: {text_value}")
    return tuple(int(p) for p in parts)


def parse_optional_image_dims(text_value):
    """Parse optional WIDTH,HEIGHT into integer list."""
    if text_value is None:
        return None
    parts = [p.strip() for p in text_value.split(",")]
    if len(parts) != 2:
        raise ValueError(f"Expected WIDTH,HEIGHT format but got: {text_value}")
    return [int(parts[0]), int(parts[1])]


def parse_optional_colors(text_value):
    """Parse optional literal list of RGB tuples."""
    if text_value is None:
        return None

    parsed = ast.literal_eval(text_value)
    if not isinstance(parsed, (list, tuple)):
        raise ValueError("Colors must be a list or tuple of RGB tuples")

    colors = []
    for color in parsed:
        if not isinstance(color, (list, tuple)) or len(color) != 3:
            raise ValueError("Each color must be length-3 RGB")
        colors.append(tuple(int(v) for v in color))
    return colors


def sorted_dirs(path):
    """Return child directories sorted by name."""
    dirs = [p for p in path.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.name)
    return dirs


def run_lexographic_renaming(target_dir):
    """Apply folder+file zero-padding rename for deterministic traversal order."""
    rename(path=str(target_dir), file_or_folder="folder", name_length="auto")
    for cur_tp in sorted_dirs(target_dir):
        rename(path=str(cur_tp), file_or_folder="file", name_length="auto")


def build_zero_ref_lists(path_to_timepoints):
    """Build default reference and rotation lists for each timepoint."""
    n_timepoints = len(sorted_dirs(path_to_timepoints))
    ref_list = [[0, 0] for _ in range(n_timepoints)]
    rot_list = [[1, 0] for _ in range(n_timepoints)]
    return ref_list, rot_list


def build_ref_lists(path_to_timepoints, image_dims, args):
    """Build reference and rotation point lists from defaults or marker detection."""
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


def save_wireframe_pickle(path, frame_dict):
    """Write intermediate wireframe pickle with WIREFRAME header."""
    ensure_parent(path)
    with open(path, "wb") as f:
        f.write(b"WIREFRAME\n")
        pickle.dump(frame_dict, f)


def outlines_to_frame_dict(args):
    """Convert outlines directory into the frame dictionary used by matching."""
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
    return frame_dict


def run_cell_matching_from_outlines(args):
    """Run the full outlines -> 4D Cell3D matching pipeline in isolation."""
    global ss_cell_count, cell3D_count
    ss_cell_count = 0
    cell3D_count = 0

    frame_dict = outlines_to_frame_dict(args)

    if args.wireframe_pkl:
        wireframe_path = resolve_path(args.wireframe_pkl)
        save_wireframe_pickle(wireframe_path, frame_dict)
        print(f"Intermediate wireframe pickle written: {wireframe_path}")

    colors = parse_optional_colors(args.colors)
    if colors is None:
        colors = extract(dict_data=frame_dict, skip_slice=args.skip_slice)
        print(f"Extracted {len(colors)} colors from frame data")
    else:
        print(f"Using {len(colors)} user-provided colors")

    if not colors:
        raise RuntimeError("No colors available for matching. Check outlines or pass --colors.")

    cells_3d, num_tps = get_cells3D_from_frame_dict(
        frame_dict=frame_dict,
        colors=colors,
        apply_filter=not args.no_filter,
    )

    output_cells = resolve_path(args.output_cells_pkl)
    output_tp = resolve_path(args.output_tp_pkl)
    ensure_parent(output_cells)
    ensure_parent(output_tp)

    with open(output_cells, "wb") as f:
        pickle.dump(cells_3d, f)
    with open(output_tp, "wb") as f:
        pickle.dump(num_tps, f)

    print("\nCell matching complete")
    print(f"4D cells: {len(cells_3d)}")
    print(f"Timepoints: {num_tps}")
    print(f"Cells output: {output_cells}")
    print(f"TP count output: {output_tp}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser():
    """CLI for isolated outlines-to-4D matching run."""
    parser = argparse.ArgumentParser(
        description=(
            "Isolated cell-matching pipeline from outlines to 4D Cell3D objects.\n"
            "Input: outline folders (t1, t2, ... with slice images).\n"
            "Outputs: matched 4D cells pickle + timepoint-count pickle."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument("--outlines-dir", required=True, help="Root directory containing t1/t2/... outline image folders.")
    parser.add_argument("--skip-lexographic-renaming", action="store_true", help="Skip renaming pass in outlines mode.")

    parser.add_argument("--image-dims", default=None, help="Image dimensions as WIDTH,HEIGHT.")
    parser.add_argument("--find-reference-points", action="store_true", help="Detect reference points from colored markers.")
    parser.add_argument("--find-rotation-points", action="store_true", help="Detect rotation points from colored markers.")
    parser.add_argument("--reference-point-color", default="255,255,0", help="Reference marker color as R,G,B.")
    parser.add_argument("--rotation-point-color", default="0,255,0", help="Rotation marker color as R,G,B.")
    parser.add_argument("--rotate", action="store_true", help="Enable rotation in outline normalization.")
    parser.add_argument("--no-sort-large-groups", action="store_true", help="Keep compatibility with formatter options.")

    parser.add_argument("--colors", default=None, help="Optional explicit color list literal, e.g. '[(255,0,0),(0,255,0)]'.")
    parser.add_argument("--skip-slice", type=int, default=0, help="Skip this many slices from each stack edge during color extraction.")
    parser.add_argument("--no-filter", action="store_true", help="Disable matched-cell filtering step.")

    parser.add_argument("--wireframe-pkl", default=None, help="Optional path to save intermediate WIREFRAME pickle.")
    parser.add_argument("--output-cells-pkl", default="./output/matched_cells_4d.pkl", help="Output path for matched Cell3D list pickle.")
    parser.add_argument("--output-tp-pkl", default="./output/matched_cells_tp_num.pkl", help="Output path for timepoint count pickle.")
    return parser


def main():
    """Entry point for isolated cell matching."""
    args = build_arg_parser().parse_args()
    run_cell_matching_from_outlines(args)


if __name__ == "__main__":
    main()
