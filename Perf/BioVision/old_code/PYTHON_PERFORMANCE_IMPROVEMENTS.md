# Python Performance Improvements for the BioVision Pipeline

## Scope

This document covers Python-side performance improvements for the pipeline described in `README.md`:

1. Step 1: formatting preparation and wireframe generation
2. Step 2: cell matching, mesh generation, and quantitative export
3. Step 3: Blender loading/export-adjacent serialization

The recommendations below are based on:

- the current README pipeline description
- the current Python implementation under `processing/`
- the sampled flamegraph at `output/pipeline_flamegraph.svg`

## Executive Summary

If you only do a few things, do these first:

1. Remove the large `deepcopy` calls in the matching and mesh paths.
2. Stop re-reading and re-processing the wireframe pickle once per color.
3. Cache per-outline and per-cell geometry once instead of recomputing centers and widths inside nested loops.
4. Replace all-pairs greedy matching with candidate-gated matching using a spatial index.
5. Move slice connected-component extraction from Python sets/BFS into a C-backed routine such as `scipy.ndimage.label` or `skimage.measure.label`.
6. Parallelize coarse independent work units: timepoints in Step 1, and cells/meshes in Step 2.

Those changes should materially reduce runtime without changing the overall pipeline design.

## What the Existing Profile Already Says

The current sampled flamegraph in `output/pipeline_flamegraph.svg` was generated from the unified `full_pipeline.py` run on the `A1` dataset. The most important result is that quantification dominates runtime:

- `run_quant_pipeline`: about 98.3% of sampled runtime
- `get_cells3D`: about 69.9%
- `compute_animation`: about 44.1%
- `get_raw_cell_data`: about 4.5%
- `deepcopy` alone accounts for a very large share of samples inside matching

That means the biggest wins are not in Blender rendering, and not even in image segmentation for this profiled run. The biggest wins are in Step 2, especially cell matching and object copying.

Treat the exact percentages as approximate because this is sampled profiling, but the ranking is clear.

## Prioritized Improvement List

| Priority | Change | Why it matters | Risk |
| --- | --- | --- | --- |
| 1 | Remove `deepcopy` from matching and mesh generation | Current profile shows this is a first-order cost | Low |
| 2 | Load the wireframe pickle once and process all colors in one pass | Avoids repeated disk I/O and repeated stack traversal | Low |
| 3 | Cache geometry features on `Cell` and `Cell3D` | Removes repeated centroid and width recomputation in nested loops | Low |
| 4 | Replace all-pairs matching with gated matching | Reduces quadratic pair generation and sorting | Medium |
| 5 | Use C-backed connected components in Step 1 | Replaces Python tuple/set BFS over large pixel groups | Medium |
| 6 | Parallelize timepoint and mesh work | Independent units already exist | Medium |
| 7 | Reduce Python object churn in mesh creation | The mesh path copies and reallocates heavily | Medium |
| 8 | Introduce quality tiers for mesh density | Lets you choose speed vs fidelity explicitly | Low |
| 9 | Stream exports instead of building large Python lists first | Reduces memory spikes and serialization overhead | Low |
| 10 | Move to array-based representations and `slots` | Best long-term memory and speed improvement | Higher |

## Step 2 First: Remove the Biggest Waste

### 1. Eliminate `deepcopy` from cell matching

This is the clearest immediate win.

Relevant code:

- `processing/get_matched_cells.py:61-63`
- `processing/pickled_animation_cell_matching.py:222-223`
- `processing/pickled_animation_cell_matching.py:309-310`
- `processing/pickled_quant_data.py:156-157`
- `processing/pickled_quant_data.py:256-257`
- `processing/mesh_creation/cell_point_filler.py:49`
- `processing/mesh_creation/cell_point_filler.py:56`
- `processing/mesh_creation/cell_point_filler.py:103`
- `processing/mesh_creation/cell_point_filler.py:108`

Why this is expensive:

- your objects are nested Python lists of points inside lists of outlines inside cell objects
- `deepcopy` walks all of that recursively
- the flamegraph shows copying is not background noise, it is one of the dominant costs

What to do:

- make the matching code operate on references, not copied objects
- when you only need a filtered list, build a new top-level list with existing objects instead of deep-copying the whole structure
- only copy a structure when a function truly mutates it and mutation cannot be avoided
- for functions that mutate inputs internally, prefer making them pure and returning new outputs instead

Example direction:

- in `pickled_animation_cell_matching._compute_tp`, replace deep-copied `cur_cells` and `prev_cells`
- use list comprehensions over the original objects
- or pre-indexed lists per color

Expected impact:

- likely one of the largest single speedups in the repository
- also lowers peak memory pressure

### 2. Load the wireframe pickle once, not once per color

Relevant code:

- `processing/get_matched_cells.py:44-51`
- `processing/pickled_animation_cell_matching.py:303-313`

Current behavior:

- `get_cells3D` loops through every color
- each color calls `get_raw_cell_data`
- `get_raw_cell_data` opens the pickle and loads all wireframe data again
- each timepoint is then deep-copied again before matching

Why this is expensive:

- repeated pickle loading
- repeated traversal of the same timepoints
- repeated object creation for identical data

Better approach:

1. Load the wireframe pickle once at the start of Step 2.
2. For each timepoint, build a color-indexed structure once.
3. Run stack matching per color from that in-memory representation.
4. Reuse the same per-timepoint structures for animation matching.

Best version:

- compute raw `Cell2D` objects for all colors in a single pass over each stack
- produce `all_raw_cells_by_color[color][timepoint]`

This removes an entire multiplicative factor of `number_of_colors`.

### 3. Cache cell centers, widths, and bounds once

Relevant code:

- `processing/single_stack_cell_matching.py:77-91`
- `processing/single_stack_cell_matching.py:111-118`
- `processing/pickled_animation_cell_matching.py:83-117`
- `processing/pickled_animation_cell_matching.py:131-137`
- `processing/pickled_animation_cell_matching.py:153-157`

Current issue:

- centers are recomputed repeatedly inside matching loops
- widths are recomputed repeatedly inside threshold calculations
- these are nested inside pair generation, so the same geometry is recalculated many times

Recommended change:

- add cached geometry fields to `Cell` and `Cell3D`
- compute them once in the constructor or immediately after an outline/cell is finalized

Useful cached fields:

- `center_xy`
- `center_xyz`
- `bbox_min`
- `bbox_max`
- `width_x`
- `width_y`
- `width_z`
- `approx_radius`

Good implementation choices:

- use `@dataclass(slots=True)` for `Cell` and `Cell3D`
- store cached values as tuples or small NumPy arrays

Expected impact:

- medium to large speedup in matching
- simpler matching code because geometry lookup becomes O(1)

### 4. Replace all-pairs greedy matching with candidate-gated matching

Relevant code:

- `processing/single_stack_cell_matching.py:105-120`
- `processing/single_stack_cell_matching.py:157-178`
- `processing/pickled_animation_cell_matching.py:124-140`
- `processing/pickled_animation_cell_matching.py:182-208`

Current algorithm:

- build every pair between current and previous objects
- compute every distance
- sort the full pair list
- then remove conflicting pairs greedily

Complexity:

- pair generation is O(n*m)
- sorting is O((n*m) log(n*m))
- the repeated filtering logic adds more overhead

Better approach:

- build a spatial index on previous centers with `scipy.spatial.cKDTree`
- for each current cell, query only nearby previous cells using a biologically valid radius
- only build a reduced candidate list

Possible matching strategies:

- keep the current greedy algorithm, but run it only on gated candidates
- or switch to `scipy.optimize.linear_sum_assignment` on a sparse or pruned cost matrix

Candidate gating can use:

- center distance
- bounding-box overlap
- color equality
- max allowed travel distance

This is where you move from "Python is slow" to "the algorithm is doing too much work."

### 5. Fix the width calculation bug while refactoring matching

Relevant code:

- `processing/pickled_animation_cell_matching.py:111-117`

`_approx_width` returns from inside the loop, so it only considers the first outline list rather than all outlines.

That is primarily a correctness issue, but it also affects performance indirectly:

- bad width estimates can admit too many candidates
- or reject matches and create more downstream objects

Fix this during the matching rewrite so your gating radius is both faster and more accurate.

## Step 1 Improvements

### 6. Replace Python BFS over pixel sets with connected-component labeling

Relevant code:

- `processing/translators/v10manual_segmentation_formatter.py:109-145`

Current behavior:

- the slice image is scanned with NumPy to find colored pixels
- those pixels are converted into Python tuples
- per-color connected components are found with Python `set` membership and `deque` BFS

Why this is expensive:

- Python tuple creation is heavy
- Python hash-set membership is fast for Python, but still much slower than array operations in C
- each component accumulates many small Python objects

Recommended replacement:

- for each color mask, run `scipy.ndimage.label` or `skimage.measure.label`
- use a structuring element that matches your loose-neighborhood policy
- then extract connected component coordinates from the label image

That shifts the hot path from Python object management to compiled code.

Sketch:

```python
mask = np.all(rgb == color, axis=2)
labels, n = scipy.ndimage.label(mask, structure=structure)
for label_id in range(1, n + 1):
    ys, xs = np.nonzero(labels == label_id)
```

Further improvement:

- if you can tolerate a small morphology pass, close tiny gaps first
- that reduces fallback work in `sort_robust_outline`

### 7. Turn the current fake "sparse" mode into a real point decimator

Relevant code:

- `processing/translators/v10manual_segmentation_formatter.py:23-24`
- `processing/translators/v10manual_segmentation_formatter.py:78-83`

Right now:

- `sparse = True`
- but the code uses `adjusted[::1]`

That means sparse mode does not actually remove any points.

Why this matters:

- every extra outline point increases Step 1 sorting cost
- it also increases matching cost, pickled size, mesh generation cost, and export size

Recommended options:

- simple stride decimation like `adjusted[::2]` or `adjusted[::3]`
- Douglas-Peucker simplification on the ordered contour
- adaptive decimation based on perimeter length

Best version:

- expose two quality modes: `fast`, `balanced`, `high`

This is one of the cheapest improvements to implement.

### 8. Improve `sort_robust_outline` by using C-backed morphology or contour tracing

Relevant code:

- `processing/translators/sort_robust_outline.py:40-139`
- `processing/translators/sort_robust_outline.py:146-267`

Current behavior:

- builds a local raster grid
- performs dilation with Python loops over offsets
- flood-fills from borders
- optionally falls back to adjacency graph building and 2-opt cleanup

This is already smarter than a naive nearest-neighbor sorter, but it is still fairly allocation-heavy and partially Python-bound.

Improvement options:

1. Replace manual dilation and erosion with `scipy.ndimage.binary_dilation` and `binary_erosion`.
2. Replace manual flood-fill plus boundary trace with `skimage.measure.find_contours` or a similar compiled contour extractor on the local mask.
3. Keep the fallback path, but reduce how often it is entered by cleaning the local mask first.

Why this matters:

- Step 1 spends real time sorting large components
- those costs scale with contour complexity

Suggested strategy:

- keep the existing algorithm as the correctness baseline
- add an optional fast path behind a flag
- compare contour quality on a small validation corpus

### 9. Make formatting preparation stream sums, not coordinate lists

Relevant code:

- `processing/translators/formatting_preparation.py:47-60`

Current behavior:

- every matching marker pixel has its coordinates appended into Python lists
- average coordinates are computed later from those lists

Better approach:

- accumulate `x_sum`, `y_sum`, and `count` directly
- do not build `all_x` and `all_y`

This is not the biggest bottleneck in the repo, but it is a clean constant-factor improvement and reduces temporary memory.

### 10. Combine marker extraction with slice parsing if you want one-pass Step 1

The README currently treats marker detection and manual segmentation formatting as separate sub-steps. That is fine for clarity, but it means the same images can be read more than once.

If Step 1 becomes a bottleneck on larger datasets, consider:

- a single image-read pass
- extract reference marker hits during that pass
- extract rotation marker hits during that pass
- extract colored segmentation pixels during that pass

This is a bigger refactor, but it removes redundant image I/O.

## Mesh Generation Improvements

### 11. Remove copies and Python list churn in `point_filler`

Relevant code:

- `processing/mesh_creation/cell_point_filler.py:48-61`
- `processing/mesh_creation/cell_point_filler.py:99-113`
- `processing/pickled_quant_data.py:154-184`

Current issue:

- the mesh path repeatedly deep-copies outlines and wireframes
- loops are then copied again before splining and closing

Recommended change:

- decide exactly which functions mutate input
- make those functions return new arrays instead of mutating callers' inputs
- then remove nearly all defensive copies

This is especially valuable because Step 2 already pays large matching costs before mesh generation starts.

### 12. Preallocate mesh vertices/faces with NumPy arrays

Relevant code:

- `processing/mesh_creation/contour_stitching_mesh.py:257-299`
- `processing/mesh_creation/contour_stitching_mesh.py:331+`

Current behavior:

- vertices and faces are built with nested Python `append`
- then converted to NumPy arrays at the end

Better approach:

- compute counts up front
- allocate `verts = np.empty((n_verts, 3), dtype=np.float32)`
- allocate `faces = np.empty((n_faces, 3), dtype=np.int32)`
- fill them by index

Why this helps:

- fewer Python allocations
- less list growth overhead
- faster serialization later

### 13. Reduce repeated work when slicing wireframes at many Z levels

Relevant code:

- `processing/mesh_creation/contour_stitching_mesh.py:74-102`
- `processing/mesh_creation/contour_stitching_mesh.py:212-247`

Current behavior:

- for each Z in `z_plan`, every wireframe loop and every segment is scanned again

That creates a repeated-work pattern:

- `num_z_levels * num_wireframe_segments`

Better approach:

- precompute each loop's segment Z intervals once
- for each target Z, only evaluate segments whose `[z_min, z_max]` contain that level
- or vectorize all segment intersection tests for a loop with NumPy

This matters more as you increase:

- `POINTS_PER_SEGMENT`
- `interp_per_gap`
- `num_cap_levels`
- `num_points`

### 14. Make `trimesh` post-processing optional

Relevant code:

- `processing/mesh_creation/contour_stitching_mesh.py:294-300`

Current behavior:

- every mesh is created with `process=True`
- then `mesh.fix_normals()` is called

Those operations can be expensive.

Recommended change:

- expose a `mesh_postprocess` flag
- `process=True`
- `process=False`
- `fix_normals()` on/off

If your generated topology is already valid enough for Blender, you may be paying for cleanup you do not need on every run.

### 15. Add explicit mesh quality tiers

Relevant code:

- `processing/pickled_quant_data.py:31-36`
- `processing/mesh_creation/contour_stitching_mesh.py:119-121`

Several parameters directly control runtime:

- `POINTS_PER_SEGMENT`
- `num_points`
- `interp_per_gap`
- `num_cap_levels`
- smoothing iterations

Recommended quality presets:

| Mode | Goal | Suggested shape |
| --- | --- | --- |
| `fast` | Iteration and debugging | lower interpolation density, fewer cap levels, fewer contour points |
| `balanced` | Daily use | moderate defaults |
| `high` | Final exports | current or slightly higher fidelity |

This gives you an immediate workflow improvement even before deeper refactors land.

## Parallelism Opportunities

### 16. Parallelize by coarse independent unit, not by tiny task

Good candidates:

- Step 1: one timepoint per process
- Step 2 raw stack matching: one timepoint per process after data is loaded
- Step 2 mesh generation: one `Cell3D` per process
- export conversion: one timepoint chunk per process if needed

Why coarse tasks matter:

- Python multiprocessing has serialization overhead
- your current data is Python-object heavy
- tiny tasks will lose time to IPC and pickling

Preferred tools:

- `concurrent.futures.ProcessPoolExecutor`
- `multiprocessing` only if you need tighter control

Important caution:

- do not parallelize before reducing `deepcopy` and object churn
- otherwise the process boundary will just amplify serialization costs

### 17. Threading is probably not the first answer for CPU-heavy matching

For:

- Python loops
- geometry calculations
- object-heavy matching

use processes, not threads.

Threads can still help with:

- file I/O
- image loading
- writing outputs

But they are not the main lever here.

## Data Representation Improvements

### 18. Replace nested Python lists with arrays earlier in the pipeline

Current data shape is roughly:

- timepoint
- slice
- color
- outline
- point

and many of those points are plain Python lists like `[x, y]`.

That is easy to inspect, but expensive to:

- copy
- pickle
- iterate
- hash

Better representation:

- outlines as `np.ndarray` with shape `(n_points, 2)`
- wireframes as `np.ndarray` with shape `(n_points, 3)`
- vertices as `float32`
- faces as `int32`

Benefits:

- lower memory footprint
- faster slicing and vectorized math
- cheaper pickling than large Python object graphs

This is one of the best long-term improvements, but it touches more code than the earlier quick wins.

### 19. Use `@dataclass(slots=True)` for `Cell` and `Cell3D`

Relevant code:

- `processing/single_stack_cell_matching.py:43-70`
- `processing/pickled_animation_cell_matching.py:49-76`

Why:

- fewer per-instance dictionaries
- lower memory
- slightly faster attribute access
- easier to reason about cached fields

This is a good companion change once you start caching geometry.

## Export and Serialization Improvements

### 20. Stream CSV writing instead of building one giant list of dicts

Relevant code:

- `processing/pickled_quant_data.py:206-244`

Current behavior:

- builds `data = []`
- appends many Python dictionaries
- creates a DataFrame
- writes CSV

Better approach:

- write rows directly with `csv.writer`
- or accumulate column arrays and build the DataFrame once from arrays

This is mostly a memory optimization, but it can help on large runs.

### 21. Use the highest pickle protocol and consider array-friendly formats

Relevant code:

- all pickle writers in the repo

Easy improvement:

- use `pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)`

Longer-term option:

- use `.npz` or a compact binary format for large array payloads
- keep a thin metadata wrapper if Blender integration still expects pickle

That matters most for:

- solid mesh exports
- large wireframe files
- intermediate matched cell caches

## Recommended Implementation Order

### Phase 1: low-risk, high-return

1. Remove `deepcopy` from matching and mesh generation.
2. Load the wireframe pickle once per run.
3. Cache centers and widths on `Cell` and `Cell3D`.
4. Make sparse mode real.
5. Stream marker coordinate sums instead of storing lists.

### Phase 2: algorithmic changes

1. Refactor stack and animation matching to use candidate gating.
2. Switch connected-component extraction to `ndimage.label` or equivalent.
3. Add mesh quality presets.

### Phase 3: parallelism

1. Parallelize mesh creation by `Cell3D`.
2. Parallelize Step 1 by timepoint.
3. Parallelize raw stack matching only after the data representation is cleaned up.

### Phase 4: representation cleanup

1. Convert outlines and wireframes to NumPy arrays earlier.
2. Add `slots` dataclasses.
3. Reduce pickle-heavy intermediate structures.

## Suggested Benchmarks to Track

Do not refactor this blind. Track at least:

- total wall time for Step 1
- total wall time for Step 2
- wall time for wireframe loading
- wall time for raw stack matching
- wall time for animation matching
- wall time for mesh generation
- wall time for CSV export
- wall time for mesh export
- peak RSS memory
- output sizes for wireframe, mesh, and tracer files

Use one small dataset and one realistic dataset. The `A1` sample already looks like a good realistic benchmark candidate.

## Concrete File-by-File Targets

### `processing/get_matched_cells.py`

- load the wireframe once
- stop deep-copying `all_raw_cells` per color
- refactor to keep a `dict[color] -> per-timepoint cells`

### `processing/pickled_animation_cell_matching.py`

- cache `center3d` and width estimates
- fix `_approx_width`
- replace all-pairs matching with gated candidates
- replace linear `_identify_cell` search with an ID or center lookup map

### `processing/single_stack_cell_matching.py`

- cache per-outline center and width
- avoid recomputing centers during pair generation
- replace all-pairs matching with gated matching

### `processing/translators/v10manual_segmentation_formatter.py`

- replace Python set/BFS connected components
- implement actual contour decimation
- consider processing slices in parallel by timepoint

### `processing/translators/sort_robust_outline.py`

- move morphology and contour extraction into compiled helpers where possible
- reduce fallback frequency

### `processing/mesh_creation/cell_point_filler.py`

- stop copying every outline list defensively
- return new arrays from mutating helpers instead

### `processing/mesh_creation/contour_stitching_mesh.py`

- preallocate arrays for vertices/faces
- reduce repeated wireframe slicing work
- benchmark `trimesh` post-processing flags

### `processing/pickled_quant_data.py`

- parallelize `get_solid_mesh_objs`
- stream CSV output
- use highest pickle protocol

## Expected Outcome

If you implement only the top half of this document, the pipeline should get faster for the right reason:

- less redundant work
- less Python object copying
- less quadratic matching
- better use of compiled array code

The highest-confidence near-term wins are:

- removing `deepcopy`
- loading data once
- caching geometry
- making matching candidate-driven instead of exhaustive

Those changes align with the actual hotspot profile, not just general Python advice.
