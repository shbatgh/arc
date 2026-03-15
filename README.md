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
    main_window.py               # UI orchestration, import flow, tracking, clustering wiring
    viewer_3d.py                # VTK/vedo viewport, picking, camera controls
    timeline.py                 # playback and timepoint slider
    sidebar.py                  # selected-cell property table
    clustering_panel.py         # clustering controls + worker thread
  core/
    cell.py                     # cell wrapper over vedo mesh (volume/area/center)
    cell4d.py                   # cross-timepoint tracker (greedy nearest-neighbor)
    scene.py                    # per-timepoint container
    project.py                  # collection of scenes
    io/
      mesh_loader.py            # dataset parsing, reconstruction, caching

BioVision/
  processing/
    single_stack_cell_matching.py          # slice-to-slice cell association
    animation_cell_matching.py             # timepoint-to-timepoint association
    solid_mesh_from_3D_outlines.py         # convex-hull solid mesh generation
    mesh_creation/                         # wireframe generation, capping, splines, mesh repair
    segmentation/                          # Cellpose-based outline generation
    translators/                           # manual/SVG/AI data formatting utilities
    get_quant_data*.py                     # quantification and export scripts
  clustering/
    cell_clustering.py                     # clustering engine used by ARC clustering panel
  visualizing/
    pickled_renderer.py                    # Blender add-on for WIREFRAME/MESH/TRACER payloads

src/arc/
  main.py                                 # VTK cube demo entrypoint used by `arc` script
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

Optional developer dependencies (PyInstaller):

```bash
uv sync --only-dev
```

### Launch ARC (full app)

```bash
uv run python Arc/main.py
```

Important:
- `arc` CLI script from `pyproject.toml` points to `src/arc/main.py`, which is a small 3D cube demo.
- Use `Arc/main.py` for the production desktop application.

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

Entry point: `Arc/app/main_window.py` -> `import_dataset_folder()`

### Step 1: User chooses folder and mode

- File menu triggers folder chooser (`Arc/app/dialogs/import_dialog.py`)
- Mode chooser sets one of `Solid`, `Mesh`, `Raw`

### Step 2: Loader resolves cache or computes data

`Arc/core/io/mesh_loader.py::load_dataset_from_root()`:

1. Computes cache path: `<dataset_parent>/<dataset_name>_<mode>.pkl`
2. If cache exists:
   - loads via `_load_wireframe_cache()` for `raw/mesh`
   - loads via `_load_solid_cache()` for `solid`
3. If no cache:
   - enumerates valid timepoint folders
   - processes each timepoint in a `ProcessPoolExecutor`

### Step 3: Per-timepoint reconstruction in worker process

`_process_timepoint_task()`:

1. `_load_stack_from_timepoint()` builds `stack_list`
   - each slice becomes `{(255,0,0): [outline1, ...]}`
2. resets BioVision globals (`cell_count`, `cells`) in worker
3. calls `single_stack_cell_matching.compute_stack()`
4. per cell, `_compute_mesh_data_from_cell()` returns:
   - `raw`: XY curves
   - `mesh`: XY + splined XZ/YZ curves from `cell_point_filler.point_filler()`
   - `solid`: convex hull from `solid_mesh_from_3D_outlines.build_mesh()`

### Step 4: Scene assembly

- Wireframe modes: `_create_scene_from_wireframe_data()`
  - `mesh` mode converts curves to tubes via `_create_tube_from_curves()`
  - `raw` mode keeps line primitives
- Solid mode: `_create_scene_from_solid_data()` from vertices/faces
- Result is `Project.scenes[timepoint] = Scene(...)`

### Step 5: Cache write

- `raw`: header `RAW\n`
- `mesh`: header `WIREFRAME\n`
- `solid`: header `MESH\n`

Caches are pickle payloads with mode-specific structure and are reused on subsequent imports.

## Tracking Pipeline (Across Time)

After successful import, `MainWindow._track_cells()` executes `CellTracker.track_cells()` (`Arc/core/cell4d.py`).

Algorithm shape:

1. Initialize one track per cell in first timepoint.
2. For each next timepoint:
   - gather active tracks from previous frame
   - compute distance from each new cell center to each active track center
   - greedy assignment by ascending distance
   - enforce one-to-one match
   - create new track for unmatched cells
3. annotate each cell metadata with:
   - `track_id`
   - `t_start`
   - `t_end`
   - `display_id` (`t<start>-t<end>_<id>`) after final metadata update

Current tracker characteristics:
- purely centroid-distance based
- threshold is fixed (`max_distance=50.0`)
- no split/merge lineage modeling

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

ARC does not use all of BioVision. It relies on a focused subset:

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

1. Update logic in `Arc/core/cell4d.py`.
2. Keep metadata contract (`track_id`, `display_id`, `t_start`, `t_end`) intact.
3. Validate with dense datasets where cells are close.
4. Re-check clustering, because cluster mapping depends on stable track IDs.

### Add a new import mode

1. Extend mode handling in `Arc/app/main_window.py` and `Arc/core/io/mesh_loader.py`.
2. Define cache header/schema and save/load functions.
3. Ensure `Scene` builds pickable meshes for selection.
4. Confirm volume/area semantics for sidebar fields.

### Work with BioVision scripts

Most legacy scripts are path-hardcoded and workflow-specific. Treat them as reference code unless explicitly productized.

## Build and Distribution

### Local PyInstaller builds

- Linux: `uv run pyinstaller linux_build.spec --clean --noconfirm`
- macOS: `uv run pyinstaller mac_build.spec --clean --noconfirm`
- Windows: `uv run pyinstaller windows_build.spec --clean --noconfirm`

Specs package:
- `Arc/main.py`
- `Arc/resources`
- hidden imports for `cellpose` and `vedo`

### CI workflows

GitHub workflows in `.github/workflows/` build platform artifacts:
- `build_linux.yml`
- `build_macos.yml`
- `build_windows.yml`

## Operational Caveats

- First install is large (Qt, VTK, Cellpose, scientific stack).
- First import on large datasets is expensive; cache files are critical for iteration speed.
- BioVision matching modules rely on mutable module globals; ARC uses process isolation to avoid cross-timepoint contamination.
- `generated_cell_features.csv` is a fallback. Preferred scientific analyses should use curated quantification exports.
- `Arc/tests/` currently has no committed automated tests.

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

