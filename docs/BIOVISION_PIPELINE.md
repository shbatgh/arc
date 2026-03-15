# BioVision Pipeline Deep Dive

This document explains the `BioVision/` codebase as it exists in this repository: what parts ARC uses directly, what remains legacy tooling, and how the major algorithms work.

## Why BioVision Exists

BioVision is the historical processing engine that predates the current Qt app. ARC still depends on core pieces of it for reconstruction and clustering.

ARC-critical modules:
- `BioVision/processing/single_stack_cell_matching.py`
- `BioVision/processing/mesh_creation/cell_point_filler.py`
- `BioVision/processing/solid_mesh_from_3D_outlines.py`
- `BioVision/clustering/cell_clustering.py`

Most other BioVision scripts are workflow tools for manual data formatting, segmentation preprocessing, export, and Blender visualization.

## Core Data Contracts

### Slice and stack format

Many modules operate on:

```python
stack_list[slice_idx] = {
    (R, G, B): [outline1, outline2, ...]
}
```

Where each `outline` is:

```python
[[x1, y1], [x2, y2], ...]
```

### Cell object from single-stack matching

`single_stack_cell_matching.Cell` stores:
- `id`
- `color`
- `starting_slice`
- `top_slice`
- `outlines` (list of 2D outlines across Z)
- `centers` (centroid per outline)

### Wireframe payload (pickle/text)

Used by Blender renderers and sometimes ARC cache logic:

```text
WIREFRAME\n
{ timepoint: [ slice_dict, ... ] }
slice_dict = { color_tuple: [outline3d, outline3d, ...] }
```

### Solid mesh payload

```text
MESH\n
{ timepoint: [
  {
    'vertices': [[x,y,z], ...],
    'faces': [[i,j,k], ...],
    'color': (R,G,B),
    'name': 'cell_...'
  },
  ...
]}
```

### Tracer payload

```text
TRACER\n
{ color_tuple: [ path3d, path3d, ... ] }
```

## Pipeline Families in BioVision

There are 5 major pipeline families:

1. Segmentation and outline extraction
2. Translator/formatter stage (manual PNG, SVG, AI outline text)
3. 3D grouping and geometry generation
4. Cross-timepoint tracking and quantification
5. Clustering and visualization/export

---

## 1) Segmentation and Outline Extraction

### `processing/segmentation/run_cellpose_sam.py`

This is the cleanest segmentation script in the tree.

Flow:
1. iterate timepoint folders `tN`
2. load each `.tif`
3. force RGB if grayscale
4. Gaussian blur (`blur_kernel`)
5. run Cellpose model (`CellposeModel.eval`)
6. save:
   - `_seg.npy` (mask + flows + styles)
   - `_cp_outlines.txt` (largest contour per mask label)
   - `_cp_masks.png` visualization

Contour extraction:
- for each label > 0, use binary mask + `cv2.findContours`
- choose largest external contour
- write as `x,y,x,y,...`

### `processing/segmentation/cell_iso_gui.py`

Legacy Tk GUI wrapper with additional HSV-based cell isolation.

Notable behavior:
- can copy raw input tree to a working directory
- runs segmentation over copied tree
- optional HSV filter retains only cells with enough colored pixels
- writes isolated PNGs and `_outlines.txt`

This script includes substantial UI state and hardcoded workflow assumptions.

---

## 2) Translator/Formatter Stage

Purpose: normalize manually segmented or SVG traced data into BioVision stack format.

### PNG manual formatter

`processing/translators/v10manual_segmentation_formatter.py`

Key algorithm pieces:
- flood/region growth around non-black/non-white pixels (`create_outline_lists`)
- per-outline point ordering via:
  - angle sort (`sort_angle_algorithm.py`) or
  - greedy nearest-neighbor TSP-like sort (`sort_loose_travelling_salesman_algorithm.py`)
- coordinate adjustment relative to reference point and optional rotation (`adjust_algorithm.py`)
- circuit closure by appending first 3 points again

Output:
- `frame_dict[timepoint] = stack_list`

### SVG formatter

- `processing/translators/svg_translator.py`
- `processing/translators/v10manual_segmentation_formatter_SVG.py`

`svg_translator` parses `<path>` elements, samples each path by length, converts stroke hex colors to `(R,G,B)`, and emits the same slice dictionary structure as PNG formatter.

### Preparation helpers

- `formatting_preparation.py`
- `formatting_preparation_SVG.py`

These generate per-timepoint reference/rotation points by locating specific colored marks.

### Orchestration scripts

- `pre_visualization_phase.py` (text output)
- `pickled_pre_visualization_phase.py` (pickle output + `WIREFRAME` header)

Both are interactive command-style scripts combining segmentation and formatting steps.

---

## 3) 3D Grouping and Geometry Generation

### 3.1 Single timepoint: Z-slice cell matching

`processing/single_stack_cell_matching.py`

This algorithm groups 2D outlines from adjacent Z slices into 3D cell objects.

#### Steps

1. Initialize cells from slice 0.
2. For each slice `s > 0`:
   - get current outlines and previous outlines for chosen color
   - compute all pairwise center distances
   - sort candidate pairs by distance
   - greedily keep non-conflicting matches
   - enforce distance threshold based on size heuristic
   - add matched outlines to existing cell objects
   - unmatched current outlines start new cells

#### Distance gate

`find_max_error(point_list1, point_list2)`:
- approximate radius from max axis span per outline
- allowed motion = `0.5 * max(approx_r1, approx_r2)`
- pair kept only if center distance < allowed motion

#### Important implementation characteristics

- global mutable lists (`cells`, `cell_count`)
- greedy matching, not Hungarian/global optimum
- no explicit split/merge handling beyond unmatched creation

### 3.2 Wireframe fill and spline generation

`processing/mesh_creation/cell_point_filler.py`

Goal: from slice outlines, generate additional XZ and YZ wireframes to densify 3D surface support.

Sub-pipeline:

1. `new_triple_wireframe.triple_wireframe_creation(..., x_or_y='x')`
2. same for `x_or_y='y'`
3. top cap construction via `cap_finder_own_approach.execute(..., top)`
4. bottom cap construction via `...execute(..., bottom)`
5. Catmull-Rom interpolation injection (`catmull_rom_spline_injecter`)
6. force closed circuits (append first 3 points)

#### Triple wireframe (`new_triple_wireframe.py`)

Algorithm highlights:
- finds min/max extent along chosen axis
- defines a set of parallel cutting planes spaced by `wf_dist`
- for each plane, extracts representative points per slice (min side going up, max side coming down)
- produces a closed loop across slices

It duplicates slice ordering (`new_sorted_outlines`) to create up/down traversal symmetry.

#### Cap synthesis (`cap_finder_own_approach.py`)

High-level idea:
- find outlines touching top/bottom Z level
- build XZ and YZ arch objects at those caps
- estimate intersection points between XZ and YZ segments
- recover Z coordinate using nonuniform Kochanek-Bartels spline inversion (`v_for_u_nonuniform`)
- scale cap points if they exceed adjacent-slice limits
- splice cap arches into original outlines

#### Spline kernels

- `kochanek_bartels_spline_safe.py`: nonuniform Hermite spline with tension/continuity/bias
- `catmull_rom_spline_injecter.py`: inserts intermediate points per segment for smooth curves

### 3.3 Solid mesh generation

Two major strategies exist.

#### Convex hull from outlines (used by ARC solid mode)

`processing/solid_mesh_from_3D_outlines.py`

Steps:
1. downsample each outline to common point count
2. concatenate all points
3. compute convex hull (`trimesh.convex.convex_hull`)

Pros:
- simple, fast, stable

Cons:
- smooths away concavities and internal detail

#### Point-cloud Poisson blanket

`processing/mesh_creation/solid_mesh_from_point_cloud.py`

Steps:
1. deduplicate points and remove isolated outliers (kNN quantile threshold)
2. estimate and orient normals (Open3D)
3. Poisson reconstruction
4. convert to trimesh
5. run repair/sealing pipeline (`seal_mesh.py`)

`seal_mesh.py` chains:
- degenerate/duplicate cleanup
- hole fill
- non-manifold edge removal
- fallback robust repair + largest component selection

Pros:
- can represent non-convex geometry

Cons:
- heavier dependencies (`open3d`), slower, more failure modes

---

## 4) Cross-Timepoint Tracking and Quantification

### 4.1 4D matching across timepoints

`processing/animation_cell_matching.py` (and pickled variant)

This mirrors single-stack matching but at cell-object level:
- each item is a per-timepoint 3D cell object
- matches adjacent timepoints by 3D centroid distance
- threshold uses average approximate width times `dist_travel_multiplier`

Output object: `Cell3D`
- `starting_tp`, `final_tp`
- `centers3D`
- `cells_list` (observations over time)

The pickled variant reads input with header + pickle payload (`WIREFRAME`-style).

### 4.2 Quant exports

Primary scripts:
- `processing/get_quant_data.py`
- `processing/get_quant_data_mesh_updated.py`
- `processing/pickled_quant_data.py`

Computed series per tracked cell:
- position over time
- displacement vectors
- distance traveled
- volume and surface area (from generated solid meshes)

Outputs:
- CSV (`quant_data.csv` variants)
- tracer payloads (`TRACER` header)
- mesh payloads (`MESH` header)

Note:
- scripts are workflow-heavy and include hardcoded paths in `__main__` blocks.

---

## 5) Clustering Engine

### `clustering/cell_clustering.py`

`CellClusteringAnalyzer` supports two main input styles:

1. precomputed feature CSV (`outlines` + `mean_volume`, etc.)
2. legacy outline CSV (`Outline Points` / `Outline Points 3D`)

#### Feature handling

- can load existing numeric columns directly
- can compute additional geometric features from outlines on demand
- optional correlation-based feature pruning by variance-preserving pair filtering

#### Clustering methods

- `KMeans`
- `SpectralClustering` (nearest-neighbor affinity)
- `HDBSCAN` (if installed)

All features are standardized (`StandardScaler`) before clustering.

Outputs include:
- cluster labels in dataframe
- silhouette score
- visualizations (UMAP, KDE, boxplots, correlation heatmap)
- summary CSVs and Blender mapping files

### `clustering/safe_gui.py`

A separate Tk GUI frontend for clustering. It is independent from ARC’s Qt clustering panel and mainly serves legacy/manual analysis workflows.

---

## Blender Renderer Add-ons

Located in `BioVision/visualizing/`:
- `pickled_renderer.py` (current primary)
- `renderer_with_solid_meshes.py` (text/eval parser variant)
- `faster_renderer.py` (older variant)

Behavior:
- loads payload by header (`WIREFRAME`, `MESH`, `TRACER`)
- creates Blender collections per timepoint
- generates curves/meshes/materials
- drives visibility by frame-change handler (`frames_per_time_point`)
- includes color hide/show panel

Security note:
- some older renderers parse text data with `eval`; do not feed untrusted files.

---

## How ARC Calls BioVision Today

ARC import path (`Arc/core/io/mesh_loader.py`) does:

1. parse outline text files -> `stack_list`
2. call `single_stack_cell_matching.compute_stack()`
3. call `cell_point_filler.point_filler()` for mesh/solid modes
4. call `solid_mesh_from_3D_outlines.build_mesh()` for solid mode
5. convert outputs to vedo scene objects

ARC does **not** call translator orchestration scripts or Blender add-ons.

## Known Technical Debt in BioVision

1. Widespread module globals (`cells`, `cell_count`, arch registries)
2. Hardcoded filesystem paths in many script entry blocks
3. Mixed text and pickle formats with ad-hoc headers
4. Inconsistent style and minimal unit-test isolation
5. Some legacy scripts rely on `eval` for deserialization

ARC mitigates part of this by:
- process-level isolation during timepoint processing
- using only a narrow subset of modules in production flow

## Practical Contributor Guidance

### If you modify matching logic

- update both stack and animation matchers only if behavior should stay analogous
- keep threshold semantics explicit and documented
- test against sparse and dense slices

### If you modify mesh filling

- validate `raw`, `mesh`, and `solid` ARC modes separately
- watch for degenerate outlines (`len <= 16` filtering)
- ensure resulting curves remain closed loops

### If you modify clustering

- maintain stable column naming in analyzer output
- ensure ARC feature mapping logic still resolves selected features
- test all three methods (`kmeans`, `spectral`, `hdbscan`) for small and large CSVs

### If you modernize scripts

Prioritize this order:
1. remove path hardcoding from runnable sections
2. replace `eval` with safe parsers
3. convert globals to explicit state objects
4. centralize payload schema definitions

## File Index (High-Value)

- `BioVision/processing/single_stack_cell_matching.py`
- `BioVision/processing/animation_cell_matching.py`
- `BioVision/processing/mesh_creation/cell_point_filler.py`
- `BioVision/processing/mesh_creation/new_triple_wireframe.py`
- `BioVision/processing/mesh_creation/cap_finder_own_approach.py`
- `BioVision/processing/mesh_creation/kochanek_bartels_spline_safe.py`
- `BioVision/processing/solid_mesh_from_3D_outlines.py`
- `BioVision/processing/mesh_creation/solid_mesh_from_point_cloud.py`
- `BioVision/processing/mesh_creation/seal_mesh.py`
- `BioVision/clustering/cell_clustering.py`
- `BioVision/visualizing/pickled_renderer.py`

