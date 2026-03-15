# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Perf/ contains BioVision — a pipeline that converts 2D manually-segmented biological cell images into 3D reconstructed meshes, tracks cells across timepoints, computes quantitative metrics (volume, surface area, displacement), and renders animations in Blender.

This is a **performance-focused** copy of BioVision. See the parent `../CLAUDE.md` for the broader Arc project context (the PySide6 GUI that consumes BioVision's output).

## Commands

```bash
# Install dependencies (from repo root)
uv sync

# Run the unified pipeline (three modes)
python Perf/BioVision/full_pipeline.py --mode existing --wireframe-pkl path/to/wireframe.pkl
python Perf/BioVision/full_pipeline.py --mode outlines --outlines-dir path/to/timepoints/
python Perf/BioVision/full_pipeline.py --mode images --images-dir path/to/images/

# Add quantification to any mode
python Perf/BioVision/full_pipeline.py --mode existing --wireframe-pkl path.pkl --run-quant

# Profile with flamegraph
python Perf/BioVision/full_pipeline.py --profile-flamegraph output.svg --mode outlines --outlines-dir path/

# Run modular pipeline steps individually
python Perf/BioVision/processing/translators/pickled_pre_visualization_phase.py  # Step 1: wireframe generation
python Perf/BioVision/processing/pickled_quant_data.py                           # Step 2: quantification + mesh
# Step 3: Install Perf/BioVision/visualizing/pickled_renderer.py as Blender add-on
```

## Architecture

### Two Pipeline Entry Points

1. **`full_pipeline.py`** (~3300 lines) — Self-contained single-file pipeline that inlines all processing modules. No project-local imports needed. Supports CLI args, built-in py-spy profiling. This is the primary entry point for performance work.

2. **`pipeline.py`** (~480 lines) — Orchestration wrapper that imports from `processing/` modules. Uses `sys.path` manipulation to import translators.

### Processing Pipeline (4 stages)

```
Stage 1: Preprocessing (processing/translators/)
  Images → outline extraction → point sorting → drift/rotation correction → WIREFRAME .pkl

Stage 2: Cell Matching & Mesh (processing/)
  WIREFRAME .pkl → single_stack_cell_matching (2D→3D per timepoint)
                  → animation_cell_matching (track across timepoints)
                  → mesh_creation/ (splines + contour stitching + sealing)
                  → MESH .pkl, TRACER .pkl, quant .csv

Stage 3: Analysis (Clustering/)
  Quant CSV → geometric features → KMeans/HDBSCAN clustering → UMAP visualization

Stage 4: Rendering (visualizing/)
  .pkl files → Blender add-on → animated 3D scene
```

### Key Module Relationships

- **`processing/single_stack_cell_matching.py`** — Groups 2D outlines across Z-slices into 3D cells using center proximity and cell width heuristics. Returns `Cell` objects.
- **`processing/animation_cell_matching.py`** / **`pickled_animation_cell_matching.py`** — Matches `Cell` objects across timepoints into `Cell3D` objects using center-to-center distance.
- **`processing/mesh_creation/`** — The mesh pipeline chain: `cell_point_filler.py` (entry) → `cap_finder_own_approach.py` (domed ends) → `catmull_rom_spline_injecter.py` (smooth curves) → `new_triple_wireframe.py` (3-plane cross-sections) → `contour_stitching_mesh.py` (watertight assembly) → `seal_mesh.py` (repair).
- **`processing/translators/sort_robust_outline.py`** — Nearest-neighbor + 2-opt outline point ordering. Critical for non-self-intersecting polygons.

### Pickle File Format Convention

All `.pkl` outputs use a header-based format: first line is a type tag (`WIREFRAME\n`, `MESH\n`, `TRACER\n`), followed by the pickled dict payload.

### Key Constants

```python
Z_SPACING = (3.0 / 0.198) * 0.5   # ~7.58, Z-slice physical spacing
DIST_MULTIPLIER = 0.7              # Cell matching distance threshold
MIN_LENGTH = 14                    # Min outline points to count as cell
# Kochanek-Bartels spline defaults
tens = -0.75; cont = 0; bias = 0
points_per_segment = 8             # Spline interpolation density
```

### Dataset Format

```
dataset/
  t1/                    # Timepoint folders
    01.png, 01_cp_outlines.txt   # Z-slices with Cellpose outlines
    02.png, 02_cp_outlines.txt
    ...
  t2/, t3/, ... t46/
```

Outline files: one line per cell outline, CSV `x,y,x,y,...` coordinate pairs.

### Directories to Ignore

- **`old_code/`** — Legacy implementations, not used by current pipeline
- **`A1/`** — Example dataset (46 timepoints, ~15 Z-slices each)
- **`output/`** — Generated segmentation artifacts
