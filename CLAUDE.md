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

# Install dev dependencies (PyInstaller, ipykernel)
uv sync --only-dev

# Build distributables
uv run pyinstaller linux_build.spec --clean --noconfirm    # Linux
uv run pyinstaller mac_build.spec --clean --noconfirm      # macOS
uv run pyinstaller windows_build.spec --clean --noconfirm   # Windows
```

**Note:** The `arc` CLI script (from pyproject.toml `project.scripts`) points to `src/arc/main.py`, which is a VTK cube demo — NOT the main application. Always use `Arc/main.py` for the real app.

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
- `main_window.py` — orchestration: import flow, tracking, clustering wiring
- `viewer_3d.py` — VTK/vedo viewport, cell picking, camera controls
- `timeline.py` — playback slider with 250ms timer loop
- `sidebar.py` — selected-cell property table
- `clustering_panel.py` — clustering controls + QThread worker

**`Arc/core/`** — data model and I/O:
- `cell.py` — wrapper over vedo Mesh (volume, area, center)
- `scene.py` — per-timepoint container (dict of Cell objects)
- `project.py` — collection of Scenes keyed by timepoint
- `cell4d.py` — cross-timepoint tracker (greedy centroid-distance, threshold=50.0)
- `io/mesh_loader.py` — dataset parsing, reconstruction dispatch, pickle caching

**`BioVision/`** — geometry and analysis pipeline. ARC uses a focused subset:
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

GitHub Actions workflows in `.github/workflows/` build platform binaries on push to main/master and PRs:
- `build_linux.yml` — Ubuntu, installs system deps (libEGL, libGL, libxkbcommon, libdbus)
- `build_macos.yml` — creates DMG artifact
- `build_windows.yml` — Windows binary

All use Python 3.13 + uv.

## Key Technical Details

- Python >=3.13, managed with `uv`
- GUI: PySide6 (Qt6), VTK 9.5+, vedo
- Scientific: NumPy 2.0+, SciPy, scikit-learn, pandas, Cellpose 4.0+
- Tracking uses purely centroid-distance matching with no split/merge lineage
- Clustering maps results to cells via `track_id`; colors persist across timepoints
- VTK picking maps clicked actors to `cell_id` metadata
