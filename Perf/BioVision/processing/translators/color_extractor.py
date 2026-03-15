"""
Color Extractor Utility

Reads a WIREFRAME .pkl file and extracts the list of unique RGB colors
that represent real cells (outlines with more than MIN_LENGTH points).

Run this after pickled_pre_visualization_phase.py and before
pickled_quant_data.py to get the colors list needed for cell matching.
"""

import pickle

# ============================================================================
#  USER CONFIGURATION
# ============================================================================

# Path to the WIREFRAME .pkl file.
PATH_TO_WIREFRAME = r"C:/Users/tajre/OneDrive/Desktop/Amy's Animations/For Talk UPDATED ForTara.pkl"

# Minimum number of points in an outline for it to count as a real cell.
# Smaller outlines are treated as noise/artifacts and ignored.
MIN_LENGTH = 14

# Number of slices to skip from the top and bottom of each timepoint.
# Useful if edge slices have noise. Set to 0 to include all slices.
SKIP_SLICE = 0


# ============================================================================
#  FUNCTIONS
# ============================================================================

def get_data(file_path):
    """Load a pickled file, skipping the header line."""
    with open(file_path, "rb") as f:
        header = f.readline()
        parsed_data = pickle.load(f)
    return header, parsed_data


def extract(dict_data, skip_slice=0):
    """Extract all unique cell colors from wireframe data.

    Args:
        dict_data:  The wireframe dictionary {tp: [slice_dict, ...]}.
        skip_slice: Number of slices to skip from top and bottom of each
                    timepoint (to ignore noisy edge slices).

    Returns:
        List of (R, G, B) tuples for colors that have at least one outline
        longer than MIN_LENGTH.
    """
    result_colors = []
    for tp in dict_data.keys():
        tp_list = dict_data[tp]
        if skip_slice != 0:
            tp_list = dict_data[tp][skip_slice:-skip_slice]

        for slice_dict in tp_list:
            for color in slice_dict.keys():
                if color in result_colors:
                    continue
                for outline in slice_dict[color]:
                    if len(outline) > MIN_LENGTH and color not in result_colors:
                        result_colors.append(color)
    return result_colors


# ============================================================================
#  MAIN
# ============================================================================

if __name__ == "__main__":
    target_path = PATH_TO_WIREFRAME

    header, parsed_data = get_data(file_path=target_path)
    result_colors = extract(dict_data=parsed_data, skip_slice=SKIP_SLICE)

    print(result_colors)


# ============================================================================
#  PAST OUTPUTS
# ============================================================================

#ForTara: [(0, 255, 0), (0, 100, 0), (200, 200, 0), (255, 0, 0), (0, 0, 255), (200, 0, 100), (255, 0, 255), (0, 255, 255), (150, 50, 50), (255, 255, 0), (255, 200, 100)] 