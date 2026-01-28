# BioVision
This folder contains the legacy processing pipeline for converting 2D slice images into 3D cell meshes. ARC uses a minimal subset of these modules to turn outline files into meshes for visualization.

## Dataset layout (as used by ARC)
```
A1/
  t1/
    1.tif
    1_cp_outlines.txt
    2.tif
    2_cp_outlines.txt
    ...
  t2/
    ...
```
- Each timepoint folder (`t1` ... `t46`) contains 15 Z-slice images (`.tif`) and the corresponding Cellpose outline files (`*_cp_outlines.txt`).
- The `_cp_outlines.txt` files are produced by the segmentation step below and are what ARC consumes for mesh creation.

## Pipeline summary
1. **Segmentation + outline extraction**
   - Module: `processing/segmentation/cell_iso_gui.py`
   - Runs Cellpose on each `.tif`, saves `*_seg.npy`, then filters and writes outlines into `*_outlines.txt` (one outline per line; each line is `x,y,x,y,...`).
   - This step is expensive and optional if outlines already exist (the `A1` example already includes them).

2. **Formatting / outline to stack list**
   - ARC's loader recreates a `stack_list` (list of per-slice dicts) directly from `*_cp_outlines.txt`.
   - Format used by the matching code:
     ```python
     stack_list[slice_idx] = {
         (255, 0, 0): [outline1, outline2, ...]
     }
     ```

3. **Cell matching across Z-slices (single timepoint)**
   - Module: `processing/single_stack_cell_matching.py`
   - Function: `compute_stack(stack_list, color)`
   - Groups slice-wise outlines into 3D cell objects (each cell stores its slice outlines and start slice).

4. **Mesh generation (wireframes + convex hull)**
   - Module: `processing/mesh_creation/cell_point_filler.py`
     - Generates spline-filled XZ/YZ wireframes via triple-wireframe + caps.
   - Module: `processing/solid_mesh_from_3D_outlines.py`
     - Builds a trimesh convex hull from 3D outlines.
   - ARC wraps these functions to produce a watertight mesh per cell.

5. **ARC visualization**
   - Integration: `Arc/core/io/mesh_loader.py`
   - The loader:
     - Reads timepoint folders under a selected root.
     - Parses `*_cp_outlines.txt` -> `stack_list`.
     - Calls `single_stack_cell_matching.compute_stack`.
     - Calls `cell_point_filler.point_filler` and `solid_mesh_from_3D_outlines.build_mesh`.
     - Converts trimesh -> vedo mesh for rendering.
     - Attaches placeholder metadata: `{ "id": <cell_index>, "timepoint": <tp> }`.

## Notes
- Additional scripts (e.g., `processing/animation_cell_matching.py`, `processing/get_quant_data*.py`) handle multi-timepoint tracking and quantitative analysis, but ARC's Week-1 MVP only uses single-timepoint processing.
- Some mesh creation utilities depend on heavier libraries (e.g., Open3D). ARC currently avoids those paths to keep dependencies minimal.
