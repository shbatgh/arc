"""
Cell Matching Coordinator

Orchestrates the full cell matching workflow:
  1. For each color, extract raw Cell2D objects from the WIREFRAME pickle
     (via single_stack_cell_matching within each timepoint).
  2. Match cells across timepoints to produce Cell3D objects that track
     each cell's identity over time (via pickled_animation_cell_matching).
  3. Filter out noise (cells with very small outlines).
  4. Save the matched Cell3D list and timepoint count to pickle files.

Called by pickled_quant_data.py.
"""

import pickle

from . import pickled_animation_cell_matching


def cell_filter(cell3D):
    """Return True if the cell's largest outline is big enough to be real.

    Cells whose largest outline (across all timepoints) has 10 or fewer
    points are treated as noise artifacts and discarded.
    """
    max_outlines = []
    for single_tp_cell in cell3D.cells_list:
        max_outlines.append(max(len(outline) for outline in single_tp_cell.outlines))
    return max(max_outlines) > 10


def get_cells3D(path, colors, output_path, tp_path):
    """Run the full cell matching pipeline and save results.

    Args:
        path:        Path to the WIREFRAME .pkl file.
        colors:      List of (R, G, B) tuples to process.
        output_path: Where to save the matched Cell3D list (.pkl).
        tp_path:     Where to save the timepoint count (.pkl).
    """
    # Phase 1: Z-slice matching — parallel per timepoint, sequential per color
    print("Matching stacks")
    all_raw_cells = []
    for col in colors:
        print(col, end=" ")
        cur_cells = pickled_animation_cell_matching.get_raw_cell_data_parallel(
            path=path, color=col
        )
        if not all_raw_cells:
            all_raw_cells = cur_cells
        else:
            for idx in range(len(all_raw_cells)):
                all_raw_cells[idx] += cur_cells[idx]

    num_tps = len(all_raw_cells)
    print("\nNumber of Timepoints:", num_tps)

    # Phase 2: Temporal matching — parallel matching computation per color
    print("Matching animation")
    cells3D = []
    for col in colors:
        print(col, end=" ")
        cells3D += pickled_animation_cell_matching.compute_animation_parallel(
            all_raw_cells, col
        )

    # Phase 3: Filter out noise
    print("\nNumber of cells before filter:", len(cells3D))
    scrap_cells = [cell for cell in cells3D if not cell_filter(cell)]
    cells3D = [cell for cell in cells3D if cell_filter(cell)]
    print("After filter:", len(cells3D))
    for scrap in scrap_cells:
        print("Scrap cell,", scrap.color, end=" ")

    # Save results
    with open(output_path, "wb") as f:
        pickle.dump(cells3D, f)
    with open(tp_path, "wb") as f:
        pickle.dump(num_tps, f)
