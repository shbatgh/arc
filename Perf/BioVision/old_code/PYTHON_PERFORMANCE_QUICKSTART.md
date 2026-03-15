# Python Performance Quickstart for BioVision

## Audience

This is for someone who:

- already writes Python for personal projects
- understands classes, loops, functions, and modules
- has formal experience in C, C++, or Java
- wants to move quickly into implementing the performance improvements in `PYTHON_PERFORMANCE_IMPROVEMENTS.md`

This is not a Python basics tutorial. It is a fast-paced guide to the specific Python concepts and tools that matter for this codebase.

## Core Idea

For performance work in Python, the main rule is:

> Python is slow when you make it manage millions of tiny objects and operations. Python is fast enough when you reduce object churn, reduce algorithmic work, or move work into C-backed libraries like NumPy and SciPy.

In this repo, that means:

- fewer nested Python lists and tuples
- fewer `deepcopy` calls
- fewer all-pairs matching loops
- more cached geometry
- more NumPy arrays
- more SciPy utilities for connected components and nearest-neighbor queries

## Mental Model Shifts From C/C++/Java

### 1. Names are bindings, not boxes

Python variables hold references to objects.

```python
a = some_list
b = a
b.append(1)
```

Both `a` and `b` now see the appended value.

This is the root of most copy-related confusion in Python.

### 2. Function arguments are object references

Python is sometimes described as "pass by object reference" or "pass by sharing."

```python
def add_point(points):
    points.append((1, 2))

pts = []
add_point(pts)
```

`pts` is mutated because both caller and callee refer to the same list object.

### 3. Assignment is not copying

```python
a = [[1, 2], [3, 4]]
b = a           # same object
c = a[:]        # shallow copy of outer list
d = copy.deepcopy(a)  # recursive copy
```

For this repo, the difference between shallow and deep copy matters a lot.

### 4. Python performance is mostly about data shape and call placement

Coming from C++ or Java, it is tempting to think in terms of:

- method call overhead
- branch prediction
- inlining
- individual arithmetic operations

Those matter much less here than:

- how many Python objects exist
- how often you allocate new lists and dicts
- whether work happens in Python or inside NumPy/SciPy C code
- whether your algorithm is quadratic

## Copying and Mutation: Learn This First

This repo currently pays a lot for recursive copying. Before you refactor anything, make these distinctions feel natural.

### Shallow copy

Copies only the outer container.

```python
outer = [[1], [2]]
shallow = outer.copy()
shallow[0].append(99)
print(outer)   # [[1, 99], [2]]
```

### Deep copy

Recursively copies nested objects.

```python
import copy

outer = [[1], [2]]
deep = copy.deepcopy(outer)
deep[0].append(99)
print(outer)   # [[1], [2]]
```

### Why `deepcopy` is expensive

`deepcopy` walks the whole object graph:

- every list
- every dict
- every tuple-like structure that needs handling
- every nested custom object

In BioVision, that means copying:

- timepoints
- slices
- colors
- outlines
- point lists
- cell objects

That is exactly why the performance doc tells you to remove it first.

### Practical rule

Before copying, ask:

1. Is the callee actually mutating this object?
2. If yes, can I rewrite the callee to be pure?
3. If not, can I copy only the top-level container instead of everything?

## The Python Features You Should Use Heavily

## `dataclasses`

Use them when a class is mostly data plus a few methods.

```python
from dataclasses import dataclass, field

@dataclass(slots=True)
class Cell:
    id: int
    color: tuple[int, int, int]
    outlines: list
    center_xy: tuple[float, float] = field(init=False)

    def __post_init__(self) -> None:
        self.center_xy = compute_center(self.outlines[0])
```

Why this is good:

- less boilerplate
- easier to read than hand-written constructors
- `slots=True` reduces per-instance memory and speeds attribute lookup slightly

Use this for `Cell` and `Cell3D` once you start caching geometry.

## Type hints

Type hints do not make CPython faster, but they make refactors safer.

```python
def compute_center(outline: list[tuple[float, float]]) -> tuple[float, float]:
    ...
```

For performance refactors, they help because:

- you are changing data structures
- you want to know what shape each function expects

## Context managers

Use `with` for file and image handling.

```python
with open(path, "rb") as f:
    data = pickle.load(f)

with Image.open(path) as img:
    arr = np.asarray(img)
```

This is mainly correctness and resource hygiene, but it is standard Python.

## `pathlib`

Prefer `pathlib.Path` for new code.

```python
from pathlib import Path

root = Path("A1")
for tp_dir in root.iterdir():
    if tp_dir.is_dir():
        ...
```

Not a performance feature, just cleaner code for file-heavy pipelines.

## Standard-library modules worth knowing

- `dataclasses`
- `typing`
- `pathlib`
- `csv`
- `time`
- `concurrent.futures`
- `collections`
- `itertools`

## Profiling and Measurement

Do not optimize without timing.

### `time.perf_counter`

Use this for timing small sections.

```python
from time import perf_counter

t0 = perf_counter()
run_matching()
dt = perf_counter() - t0
print(f"matching: {dt:.3f}s")
```

Use `perf_counter`, not `time.time`, for performance measurements.

### `py-spy`

This is the easiest way to see where time goes in a real run.

```bash
py-spy record --format flamegraph --output output.svg -- python full_pipeline.py ...
```

Good for:

- overall hotspots
- seeing if you are stuck in Python code or native library code

### `cProfile`

Useful when you want function call counts and total time.

```bash
python -m cProfile -o stats.prof full_pipeline.py ...
```

Then inspect with:

```bash
python -m pstats stats.prof
```

### Benchmark rule

For each refactor:

1. keep a baseline timing
2. change one major thing
3. rerun the same dataset
4. compare wall time and memory

## NumPy: The Main Performance Lever

If you only study one library for this repo, study NumPy.

## What NumPy gives you

- contiguous numeric arrays
- vectorized operations in C
- slicing without Python loops
- boolean masks
- broadcasting

## Basic array creation

```python
import numpy as np

pts = np.array([[1, 2], [3, 4]], dtype=np.float32)
```

Prefer explicit dtypes when performance or memory matters.

Common dtypes here:

- `np.uint8` for images
- `np.int32` for indices or face arrays
- `np.float32` or `np.float64` for geometry

## Shape matters

```python
pts.shape   # (n_points, 2)
```

For outlines, the ideal shape is:

- `(n, 2)` for XY points
- `(n, 3)` for XYZ points

That is much better than a Python list of `[x, y]` pairs.

## Vectorized math

```python
center = pts.mean(axis=0)
mins = pts.min(axis=0)
maxs = pts.max(axis=0)
width = maxs - mins
```

This replaces Python loops like:

```python
x_sum = 0
for x, y in pts:
    x_sum += x
```

## Boolean masks

```python
rgb = img_arr[:, :, :3]
mask = np.all(rgb == color, axis=2)
ys, xs = np.nonzero(mask)
```

This is the pattern you will use for:

- marker extraction
- color filtering
- image segmentation post-processing

## Broadcasting

Broadcasting lets you apply operations across arrays without explicit loops.

```python
shifted = pts - center
```

If `pts` is `(n, 2)` and `center` is `(2,)`, NumPy broadcasts automatically.

## Views vs copies

This is critical.

```python
a = np.arange(10)
b = a[2:6]      # usually a view
c = a.copy()    # definite copy
```

Mutating `b` may mutate `a`.

```python
b[:] = 0
print(a)
```

Rule:

- slicing often returns a view
- `.copy()` returns a real copy
- `np.asarray(x)` avoids copying if `x` is already an array of the right type

## Common NumPy traps

### Trap 1: object dtype

Bad:

```python
np.array([[1, 2], [3, "x"]])
```

or arrays built from inconsistent nested structures.

Once NumPy falls back to `dtype=object`, you lose most performance benefits.

### Trap 2: tiny arrays in tight loops

Vectorization is best when you operate on moderately large arrays. Creating lots of tiny temporary arrays can still be expensive.

### Trap 3: converting back to Python too early

Avoid doing this repeatedly:

```python
pts.tolist()
```

Stay in array form until the last boundary where Python objects are required.

## SciPy: The Other Big Lever

SciPy contains exactly the kinds of building blocks this repo needs.

## `scipy.ndimage.label`

Use this to replace Python BFS for connected components.

```python
from scipy import ndimage

structure = np.ones((3, 3), dtype=np.uint8)
labels, n = ndimage.label(mask, structure=structure)
```

Then extract component coordinates:

```python
for label_id in range(1, n + 1):
    ys, xs = np.nonzero(labels == label_id)
```

This is a direct fit for `v10manual_segmentation_formatter.py`.

## `scipy.spatial.cKDTree`

Use this for nearest-neighbor queries during matching.

```python
from scipy.spatial import cKDTree

prev_centers = np.array([...], dtype=np.float32)
tree = cKDTree(prev_centers)
idxs = tree.query_ball_point(cur_center, r=max_radius)
```

This is how you stop generating every possible pair.

## `scipy.optimize.linear_sum_assignment`

Use this when you want a principled one-to-one assignment after candidate pruning.

```python
from scipy.optimize import linear_sum_assignment

row_idx, col_idx = linear_sum_assignment(cost_matrix)
```

You probably do not want to run this on a dense global matrix if the dataset is large. Use it after spatial gating.

## Useful image/geometry stack for this repo

- `Pillow` for image loading
- `numpy` for array math
- `scipy.ndimage` for labeling/morphology
- `scipy.spatial` for KD-trees
- `scipy.optimize` for assignment
- `trimesh` for mesh objects

## Concurrency: What You Need To Know

### The GIL summary

CPython has the Global Interpreter Lock.

Very short version:

- threads are not a great way to speed up CPU-heavy Python loops
- processes are usually the right tool for CPU-bound Python work
- NumPy/SciPy code may release the GIL internally, but do not assume that will save a Python-heavy loop

## `ThreadPoolExecutor` vs `ProcessPoolExecutor`

Use threads for:

- I/O-heavy tasks
- waiting on files or network

Use processes for:

- matching
- mesh generation
- Python loops over many cells

## Multiprocessing cost

Processes are not free.

You pay for:

- pickling task arguments
- copying data between processes
- process startup

That means this repo should parallelize only at coarse boundaries, such as:

- per timepoint
- per `Cell3D`
- per large batch

Do not parallelize tiny inner loops.

## Minimal process-pool pattern

```python
from concurrent.futures import ProcessPoolExecutor

def build_mesh(cell):
    return get_solid_mesh_objs(cell)

with ProcessPoolExecutor() as ex:
    all_meshes = list(ex.map(build_mesh, cells3D))
```

Before doing this, make sure:

- the work unit is big enough
- the arguments are not giant nested Python graphs if you can avoid it

## Serialization and File Output

## Pickle basics

Pickle is Python-specific serialization.

Use:

```python
pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
```

This is the right default in modern Python.

## When pickle is fine

- internal caches
- Python-only intermediate files
- quick iteration

## When pickle is not ideal

- very large numeric payloads
- interoperability with other tools

For large arrays, `.npz` is often better:

```python
np.savez_compressed(path, vertices=verts, faces=faces)
```

## Stream output when possible

Building giant Python lists of dicts is easy, but not always memory-efficient.

For CSV:

```python
import csv

with open(path, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Cell ID", "Timepoint", "X", "Y", "Z"])
    for row in rows:
        writer.writerow(row)
```

This is simpler and lighter than building a full DataFrame if you do not need Pandas transformations first.

## Repo-Specific Recipes

These are the Python patterns most directly useful for implementing the improvements from the first markdown file.

## Recipe 1: cache geometry on construction

```python
from dataclasses import dataclass, field
import numpy as np

@dataclass(slots=True)
class Cell:
    id: int
    color: tuple[int, int, int]
    outlines: list[np.ndarray]
    starting_slice: int
    top_slice: int
    centers: list[tuple[float, float]] = field(init=False)
    bbox_min: np.ndarray = field(init=False)
    bbox_max: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.centers = [tuple(outline.mean(axis=0)) for outline in self.outlines]
        stacked = np.vstack(self.outlines)
        self.bbox_min = stacked.min(axis=0)
        self.bbox_max = stacked.max(axis=0)
```

Why this matters:

- compute once
- reuse everywhere
- makes matching code cleaner

## Recipe 2: candidate-gated matching with KD-tree

```python
import numpy as np
from scipy.spatial import cKDTree

prev_centers = np.array([cell.center_xyz for cell in prev_cells], dtype=np.float32)
tree = cKDTree(prev_centers)

candidates = []
for cur_idx, cur_cell in enumerate(cur_cells):
    idxs = tree.query_ball_point(cur_cell.center_xyz, r=cur_cell.max_match_radius)
    for prev_idx in idxs:
        dist = np.linalg.norm(cur_cell.center_xyz - prev_centers[prev_idx])
        candidates.append((dist, cur_idx, prev_idx))

candidates.sort()
```

This is usually much better than building every `cur x prev` pair.

## Recipe 3: connected components without Python BFS

```python
import numpy as np
from scipy import ndimage

mask = np.all(rgb == color, axis=2)
structure = np.ones((3, 3), dtype=np.uint8)
labels, n = ndimage.label(mask, structure=structure)

components = []
for label_id in range(1, n + 1):
    ys, xs = np.nonzero(labels == label_id)
    if xs.size == 0:
        continue
    component = np.column_stack((xs, ys))
    components.append(component)
```

This is the direct replacement shape to learn for Step 1.

## Recipe 4: array-based centers and widths

```python
pts = np.asarray(outline, dtype=np.float32)
center = pts.mean(axis=0)
mins = pts.min(axis=0)
maxs = pts.max(axis=0)
width_xy = maxs - mins
```

This replaces manual loops and repeated list comprehensions.

## Recipe 5: preallocate mesh arrays

```python
n_rings = len(contours)
n = num_points
n_verts = n_rings * n + 2
n_faces = (n_rings - 1) * n * 2 + 2 * n

verts = np.empty((n_verts, 3), dtype=np.float32)
faces = np.empty((n_faces, 3), dtype=np.int32)
```

Then fill by index instead of repeated `append`.

## Recipe 6: avoid accidental copies with `np.asarray`

```python
pts = np.asarray(outline, dtype=np.float32)
```

Use this when you want:

- an array view if possible
- a conversion if needed

Use `.copy()` only when you explicitly need ownership.

## Recipe 7: compare outputs safely after refactors

For numeric geometry:

```python
np.allclose(a, b, atol=1e-5)
```

For exact arrays:

```python
np.array_equal(a, b)
```

For CSV-like structured output:

- compare row counts
- compare IDs
- compare summary statistics

This is how you refactor without breaking biology-facing behavior.

## Refactor Style That Works Well In Python

### 1. Make functions pure where possible

Prefer:

```python
def compute_contours(mask: np.ndarray) -> list[np.ndarray]:
    ...
```

over:

```python
def mutate_existing_structure(obj) -> None:
    ...
```

Pure functions are easier to:

- test
- benchmark
- parallelize
- reason about without `deepcopy`

### 2. Push mutation to the edges

In a pipeline, it is often best if:

- loaders create data
- transforms return new data
- writers serialize data

That structure makes performance work simpler.

### 3. Keep hot loops boring

In Python hot loops:

- avoid repeated attribute lookups if you can hoist them
- avoid creating lots of tiny temporary lists
- avoid exceptions for normal control flow
- avoid function calls inside extremely tight loops unless the call is to NumPy/SciPy code

Do not overdo this. Algorithm and data-structure changes matter more.

## What Not To Waste Time On First

Do not start with:

- replacing `sum(coord ** 2 for coord in displ)` with micro-optimized math
- worrying about single `if` statements
- rewriting everything into list comprehensions just because they look "Pythonic"
- premature Cython or Rust rewrites

Start with:

- `deepcopy`
- repeated pickle loads
- repeated geometry recomputation
- all-pairs matching
- Python BFS over pixels

## A Good Learning Sequence For This Repo

### Phase 1: enough Python to remove the biggest bottlenecks

Study and practice:

1. reference semantics vs copying
2. `dataclass(slots=True)`
3. `time.perf_counter`
4. `np.array`, `np.asarray`, `mean`, `min`, `max`, `vstack`
5. `scipy.ndimage.label`
6. `scipy.spatial.cKDTree`

That is enough to implement a lot of the performance doc.

### Phase 2: enough scientific Python to refactor the heavy paths

Study and practice:

1. views vs copies in NumPy
2. boolean masking
3. broadcasting
4. process pools
5. `linear_sum_assignment`

### Phase 3: enough engineering practice to refactor safely

Study and practice:

1. adding timers around each stage
2. comparing outputs with `np.allclose`
3. keeping work on one benchmark dataset while iterating

## Practical Implementation Plan

If I were learning just enough Python to implement the performance improvements here, I would do it in this order:

1. Refactor one module to remove `deepcopy` safely.
2. Convert one geometry path from list-of-lists to `np.ndarray`.
3. Replace one Python BFS with `ndimage.label`.
4. Add one KD-tree-based candidate pruning step.
5. Parallelize one coarse mesh-building stage with `ProcessPoolExecutor`.

That sequence teaches the exact Python tools this codebase needs.

## A Few Style Notes For This Repo

### Prefer explicit over clever

This codebase is computational and domain-specific. A slightly longer function that is obvious is better than a compact trick.

### Keep comments focused on why

Bad:

```python
# add 1 to x
x += 1
```

Good:

```python
# Cache bounds once so the matching threshold does not rescan outlines.
```

### Add small helper functions for shape conversions

Examples:

- `outline_to_array`
- `stacked_points`
- `cell_center_xyz`
- `candidate_pairs_for_timepoint`

That keeps the pipeline readable while you move more work into arrays.

## Minimal Reference Sheet

These are the calls most likely to matter for your next few refactors.

### Python

```python
from dataclasses import dataclass, field
from time import perf_counter
from concurrent.futures import ProcessPoolExecutor
import pickle
import csv
```

### NumPy

```python
import numpy as np

np.array(...)
np.asarray(...)
np.vstack(...)
np.column_stack(...)
np.nonzero(...)
np.all(...)
np.any(...)
np.mean(...)
np.min(...)
np.max(...)
np.linalg.norm(...)
np.allclose(...)
```

### SciPy

```python
from scipy import ndimage
from scipy.spatial import cKDTree
from scipy.optimize import linear_sum_assignment
```

### Pickle

```python
pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
obj = pickle.load(f)
```

## Final Advice

You do not need "formal Python experience" to do this work well.

Given your background, the main things to internalize are:

- Python reference semantics
- when copying is real vs accidental
- how much performance changes once data lives in arrays
- when to use processes instead of threads
- how to lean on SciPy instead of hand-writing heavy Python loops

Once those click, the improvements in `PYTHON_PERFORMANCE_IMPROVEMENTS.md` become straightforward engineering work rather than language-learning work.
