"""Greedy pairwise matching shared by slice and animation matchers.

Pure functions with no mutable globals — safe for fork-based parallelism.
"""

import math


def compute_pairwise_distances(items_a, items_b, center_fn):
    """Compute all pairwise distances between two sets of items.

    Args:
        items_a:   Items from the current slice/timepoint.
        items_b:   Items from the previous slice/timepoint.
        center_fn: Callable that returns a center tuple from an item.

    Returns a sorted list of [((center_a, item_a), (center_b, item_b)), distance].
    """
    matched_list = []
    for a in items_a:
        ca = center_fn(a)
        for b in items_b:
            cb = center_fn(b)
            matched_list.append([
                ((ca, a), (cb, b)),
                math.dist(ca, cb),
            ])
    matched_list.sort(key=lambda e: e[1])
    return matched_list


def remove_pairs(matched_list, center):
    """Remove all pairs involving a given center."""
    return [
        pair
        for pair in matched_list
        if center not in (pair[0][0][0], pair[0][1][0])
    ]


def appears_before(matched_list, center, loc):
    """Check if a center appears in any pair before index loc."""
    for e in matched_list[:loc]:
        if center in (e[0][0][0], e[0][1][0]):
            return True
    return False


def tag_centers(matched_list, center, starting_idx):
    """Find all partner centers that haven't been matched yet."""
    tagged = []
    for cur_idx in range(starting_idx, len(matched_list)):
        pair = matched_list[cur_idx]
        c_centers = [pair[0][0][0], pair[0][1][0]]
        if center in c_centers:
            c_centers.remove(center)
            center_pos_tag = c_centers[0]
            if not appears_before(matched_list, center_pos_tag, cur_idx):
                tagged.append(center_pos_tag)
    return tagged


def greedy_filter(matched_list, max_error_fn):
    """Greedily select the best non-conflicting matches within distance threshold.

    Args:
        matched_list: Sorted pairwise distance list from compute_pairwise_distances.
        max_error_fn: Callable(item_a, item_b) -> max allowed distance.
    """
    filtered = []
    idx = 0
    while idx < len(matched_list):
        filtered.append(matched_list[idx])

        paired_centers = [matched_list[idx][0][0][0], matched_list[idx][0][1][0]]
        tagged = [paired_centers[0], paired_centers[1]]
        tagged += tag_centers(matched_list, paired_centers[0], idx + 1)
        tagged += tag_centers(matched_list, paired_centers[1], idx + 1)

        for center in tagged:
            matched_list = remove_pairs(matched_list, center)

    result = []
    for pair in filtered:
        item_a = pair[0][0][1]
        item_b = pair[0][1][1]
        max_error = max_error_fn(item_a, item_b)
        if pair[1] < max_error:
            result.append(pair)
    return result
