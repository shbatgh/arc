# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

ARC is a desktop application that turns per-slice 2D cell outlines into time-resolved 3D objects, then lets users inspect, track, and cluster those objects. GUI built with PySide6 (Qt6) + VTK/vedo.

## Commands

```bash
# Install dependencies
uv sync

# Run the full desktop application
uv run python Arc/main.py

# Install dev dependencies (ipykernel)
uv sync --only-dev
```

There are no automated tests. Validation is manual (see `docs/GUI_ONBOARDING.md` for the testing checklist).

## Architecture

### Data Flow

```
2D outline files (_cp_outlines.txt)
  → Z-slice cell matching (BioVision)
  → 3D geometry generation (raw/mesh/solid modes)
  → per-timepoint Scenes of Cell objects
  → cross-timepoint tracking (greedy nearest-neighbor, cell4d)
  → feature table (CSV or auto-generated)
  → clustering (kmeans/spectral/hdbscan)
  → interactive GUI with VTK rendering + selection + cluster coloring
```

### Three Import Modes

- **raw**: XY wireframes only (fastest)
- **mesh**: XY + interpolated XZ/YZ tubes via Catmull-Rom splines
- **solid**: convex-hull meshes (heaviest, best volumetric behavior)

Mode determines reconstruction pipeline, VTK actor types, and cache file format.

### Key Modules

**`Arc/app/`** — Qt GUI layer:
- `main_window.py` — orchestration: import flow, segmentation, rendering wiring
- `segmentation_viewer.py` — Cellpose segmentation preview and outline editing
- `viewport.py` — thin wrapper embedding the VTK render backend into Qt
- `timeline.py` — playback slider with 250ms timer loop
- `sidebar.py` — selected-cell property table
- `clustering_panel.py` — clustering controls (placeholder, not yet connected)
- `isolation_dialog.py` — cell isolation mode dialog
- `theme.py` — application-wide palette and styling

**`Arc/core/`** — data types and configuration:
- `render_types.py` — dataclasses for RenderScene, RenderFrame, RenderCellMesh, etc.
- `isolation_config.py` — isolation mode configuration

**`Arc/io/`** — dataset loading and pipeline:
- `bundle_loader.py` — load `.arc` bundle files
- `pipeline_runner.py` — orchestrates BioVision processing pipeline
- `raw_outline_loader.py` — parse `_cp_outlines.txt` files into RenderScene
- `outline_editor.py` — outline manipulation utilities

**`Arc/render/`** — VTK rendering backend:
- `vtk_backend.py` — VTK scene management, picking, camera controls
- `vtk_interactor.py` — Blender-like mouse interaction style
- `backend.py` — abstract render backend interface

**`Perf/BioVision/`** — geometry and analysis pipeline. ARC uses a focused subset:
- `processing/single_stack_cell_matching.py` — Z-slice cell association
- `processing/mesh_creation/cell_point_filler.py` — spline interpolation
- `processing/solid_mesh_from_3D_outlines.py` — convex-hull mesh generation
- `clustering/cell_clustering.py` — clustering engine (KMeans, Spectral, HDBSCAN)

BioVision modules rely on mutable module-level globals; ARC uses `ProcessPoolExecutor` to isolate each timepoint in a separate process and avoid cross-contamination.

### Caching

Reconstruction results are cached as pickle files at `<dataset_parent>/<dataset_name>_<mode>.pkl`. Cache headers: `RAW\n`, `WIREFRAME\n` (mesh mode), `MESH\n` (solid mode). Caches are critical for iteration speed on large datasets.

### Dataset Contract

```
dataset_root/
  t1/, t2/, ..., tN/          # numeric timepoint folders
    *_cp_outlines.txt          # line format: x,y,x,y,...
```

### C++ Port (`arc-c++/`)

Experimental C++ port using CMake + vcpkg. Not part of the active development path — do not modify unless explicitly asked.

## CI/CD

GitHub Actions workflows in `.github/workflows/` run import smoke tests on push to main/master and PRs:
- `build_linux.yml` — Ubuntu, installs system deps (libEGL, libGL, libxkbcommon, libdbus)
- `build_macos.yml` — macOS
- `build_windows.yml` — Windows

All use Python 3.13 + uv.

## Key Technical Details

- Python >=3.13, managed with `uv`
- GUI: PySide6 (Qt6), VTK 9.5+, vedo
- Scientific: NumPy 2.0+, SciPy, scikit-learn, pandas, Cellpose 4.0+
- Tracking uses purely centroid-distance matching with no split/merge lineage
- Clustering maps results to cells via `track_id`; colors persist across timepoints
- VTK picking maps clicked actors to `cell_id` metadata
