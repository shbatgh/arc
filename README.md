# ARC Onboarding Handbook

This repository contains the **active Python ARC platform** for 3D cell reconstruction, tracking, clustering, and desktop visualization.

This document is written for new engineers who need to become productive quickly and safely.

## Scope and Non-Goals

This onboarding guide covers:
- `Arc/` (desktop GUI and runtime core)
- `BioVision/` (legacy but still critical geometry/analysis pipeline code)
- top-level operational scripts used by developers

This onboarding guide **does not cover `arc-c++/`**. That code is experimental and intentionally excluded from the active development path.

## Read This First

1. Start here (`README.md`) for architecture, setup, and contribution workflow.
2. Read `docs/GUI_ONBOARDING.md` for Qt/VTK internals and extension points.
3. Read `docs/BIOVISION_PIPELINE.md` for segmentation, matching, mesh synthesis, and clustering algorithms.

## System at a Glance

ARC is a desktop application that turns per-slice 2D cell outlines into time-resolved 3D objects and then lets users inspect and cluster those objects.

High-level data flow:

```text
2D outline files (_cp_outlines.txt)
  -> Z-slice cell matching (single stack)
  -> 3D geometry generation (raw/mesh/solid)
  -> per-timepoint scenes
  -> cross-timepoint tracking (track_id)
  -> feature table (existing CSV or generated)
  -> clustering (kmeans/spectral/hdbscan)
  -> interactive GUI rendering + selection + cluster coloring
```

## Repository Layout

```text
Arc/
  main.py                        # main app entrypoint (use this to run ARC)
  app/
    main_window.py               # UI orchestration, import flow, rendering wiring
    segmentation_viewer.py       # Cellpose segmentation preview + outline editing
    viewport.py                  # Qt wrapper for VTK render backend
    timeline.py                  # playback and timepoint slider
    sidebar.py                   # selected-cell property table
    clustering_panel.py          # clustering controls (placeholder)
    isolation_dialog.py          # cell isolation mode dialog
    theme.py                     # application-wide palette and styling
  core/
    render_types.py              # dataclasses (RenderScene, RenderFrame, RenderCellMesh, etc.)
    isolation_config.py          # isolation mode configuration
  io/
    bundle_loader.py             # load .arc bundle files
    pipeline_runner.py           # orchestrates BioVision processing pipeline
    raw_outline_loader.py        # parse _cp_outlines.txt into RenderScene
    outline_editor.py            # outline manipulation utilities
  render/
    vtk_backend.py               # VTK scene management, picking, camera
    vtk_interactor.py            # Blender-like mouse interaction style
    backend.py                   # abstract render backend interface

Perf/BioVision/
  processing/
    single_stack_cell_matching.py          # slice-to-slice cell association
    pickled_animation_cell_matching.py     # timepoint-to-timepoint association
    solid_mesh_from_3D_outlines.py         # convex-hull solid mesh generation
    mesh_creation/                         # wireframe generation, capping, splines
    segmentation/                          # Cellpose-based outline generation
    translators/                           # manual/SVG/AI data formatting utilities
    get_quant_data*.py                     # quantification and export scripts
  clustering/
    cell_clustering.py                     # clustering engine (KMeans, Spectral, HDBSCAN)
  visualizing/
    pickled_renderer.py                    # Blender add-on for WIREFRAME/MESH/TRACER payloads
```

## Runtime Modes

ARC supports three import modes:

- `raw`: horizontal XY curves only (fastest, least geometry)
- `mesh`: XY + interpolated XZ/YZ wireframes rendered as tubes
- `solid`: convex-hull solid meshes (heaviest but best volumetric behavior)

Mode affects both reconstruction pipeline and cache file used.

## Environment and Setup

### Prerequisites

- Python `>=3.13`
- `uv` (dependency resolver + runner)
- OS graphics stack capable of Qt + VTK

### Install

```bash
uv sync
```

Optional developer dependencies (ipykernel):

```bash
uv sync --only-dev
```

### Launch ARC (full app)

```bash
uv run python Arc/main.py
```

## Dataset Contract

Expected dataset structure:

```text
dataset_root/
  t1/
    1.tif
    1_cp_outlines.txt
    2.tif
    2_cp_outlines.txt
    ...
  t2/
  ...
```

What ARC actually requires for reconstruction:
- Timepoint folders with numeric names (`t1`, `t2`, ...; parsed by regex)
- Outline files ending in `_cp_outlines.txt` or `_outlines.txt`
- Each outline file line formatted as `x,y,x,y,...`

The `.tif` files are useful upstream but not required at render time if outlines already exist.

## Import and Reconstruction Pipeline

Entry point: `Arc/app/main_window.py`

### Step 1: User chooses folder

- File menu triggers folder chooser
- Raw outline mode: `Arc/io/raw_outline_loader.py` parses `_cp_outlines.txt` files directly
- Pipeline mode: `Arc/io/pipeline_runner.py` orchestrates BioVision processing

### Step 2: Raw outline loading

`raw_outline_loader.load_raw_outlines()`:

1. Finds timepoint directories and `_cp_outlines.txt` files
2. Parses outlines into `RenderCellMesh` objects with line-strip geometry
3. Assembles `RenderFrame` per timepoint, returns `RenderScene`

### Step 3: Scene rendering

- `Arc/render/vtk_backend.py` converts `RenderScene` to VTK actors
- Cell picking maps clicked actors to `cell_id` metadata

## Clustering Pipeline

### Data source resolution

`MainWindow._setup_clustering_data()` searches in dataset root and parent for:
- `quant_data.csv`
- `quant_daeta2.csv`
- `outline_data.csv`

If none exists, ARC generates `generated_cell_features.csv` from tracked cells.

### Feature generation fallback

`MainWindow._generate_clustering_csv()` aggregates per-track means:
- volume, surface area
- centroid means (x/y/z)
- total distance traveled
- lifespan metadata (`num_timepoints`, `t_start`, `t_end`)

### Clustering execution

`Arc/app/clustering_panel.py` runs a `QThread` worker:
1. `CellClusteringAnalyzer.load_data()`
2. `CellClusteringAnalyzer.extract_features()`
3. `CellClusteringAnalyzer.perform_clustering(...)`

Supported methods:
- `kmeans`
- `spectral`
- `hdbscan` (if installed)

Post-clustering:
- emits `cluster_map` keyed by tracked `cell_id`/`Cell ID`
- main window maps cluster -> color
- colors are applied per current scene based on each cell's `track_id`

## GUI Runtime Behavior

- Viewport: VTK-in-Qt (`QVTKRenderWindowInteractor`) via vedo `Plotter`
- Picking: `vtkCellPicker` maps clicked actor -> `cell_id`
- Timeline: slider + 250 ms timer for looping playback
- Sidebar: selected cell measurements and metadata table

Detailed GUI internals are documented in `docs/GUI_ONBOARDING.md`.

## BioVision Role in Current ARC

ARC does not use all of BioVision (`Perf/BioVision/`). It relies on a focused subset:

- `processing/single_stack_cell_matching.py`
- `processing/mesh_creation/cell_point_filler.py`
- `processing/solid_mesh_from_3D_outlines.py`
- `clustering/cell_clustering.py`

BioVision contains many additional scripts for manual/SVG formatting, Blender rendering, quant exports, and historical workflows. Those are documented in `docs/BIOVISION_PIPELINE.md`.

## New Engineer Playbook

### Add a new measured feature to clustering

1. Add feature computation in `BioVision/clustering/cell_clustering.py`.
2. Ensure output column is numeric and stable.
3. Expose it in `Arc/app/clustering_panel.py` (`AVAILABLE_FEATURES`).
4. Validate mapping logic in `_map_selected_features()` if naming differs.
5. Run UI and verify feature appears and clusters complete.

### Change matching behavior (tracking)

1. Update logic in `Perf/BioVision/processing/single_stack_cell_matching.py` (Z-slice) or `pickled_animation_cell_matching.py` (timepoint).
2. Validate with dense datasets where cells are close.

### Add a new import mode

1. Add a new loader in `Arc/io/` following `raw_outline_loader.py` pattern.
2. Return a `RenderScene` with appropriate `RenderCellMesh` objects.
3. Wire it into `Arc/app/main_window.py`.

### Work with BioVision scripts

Most legacy scripts are path-hardcoded and workflow-specific. Treat them as reference code unless explicitly productized.

## CI

GitHub workflows in `.github/workflows/` run import smoke tests:
- `build_linux.yml`
- `build_macos.yml`
- `build_windows.yml`

## Operational Caveats

- First install is large (Qt, VTK, Cellpose, scientific stack).
- First import on large datasets is expensive; cache files are critical for iteration speed.
- BioVision matching modules rely on mutable module globals; ARC uses process isolation to avoid cross-timepoint contamination.
- `generated_cell_features.csv` is a fallback. Preferred scientific analyses should use curated quantification exports.

## Troubleshooting Quick Table

| Symptom | Typical Cause | First Check |
|---|---|---|
| Import finds no timepoints | folder naming or no outline files | verify `tN` dirs and `_cp_outlines.txt` suffixes |
| Cells render but picking fails | actor->cell mapping missing | ensure meshes are pickable and have `cell_id` |
| Clustering panel disabled | no CSV located/generated | check status label, dataset root permissions |
| Clustering crashes | feature mismatch or low sample count | inspect console output from worker thread |
| Solid mode very slow | convex-hull creation for many cells | test `mesh` mode + cache first |

## Additional References

- `docs/GUI_ONBOARDING.md`
- `docs/BIOVISION_PIPELINE.md`
- `PERFORMANCE_GUIDE.md`
- `LAB_SCALING_PLAYBOOK.md`
- `MASSIVE_SPEED_RECOMMENDATIONS.md`

