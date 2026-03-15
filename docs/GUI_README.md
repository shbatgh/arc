# ARC GUI

ARC is a desktop application for visualizing time-resolved 3D cell meshes. It loads animation bundles produced by the BioVision processing pipeline and renders them as interactive solid-mesh scenes with per-cell coloring, timeline playback, cell selection, and quantitative property inspection.

Built with PySide6 (Qt 6) and VTK 9.5+. No vedo dependency -- VTK is used directly for full control over interactor styles, cell picking, and actor management.

## Running

```bash
uv run python Arc/main.py
```

Requires Python >= 3.13. All dependencies are declared in `pyproject.toml` and installed via `uv sync`.

## Input Formats

The GUI accepts data through two paths, both of which converge on the same render input: the `.npz` animation bundle.

### Pre-computed animation bundle (fast path)

**File > Open Animation Bundle** loads a bundle directory or `.npz` file directly. A bundle is a directory containing:

| File | Contents |
|---|---|
| `animation_meshes.npz` | Binary mesh arrays: vertices (float16, Nx3), faces (uint32, Mx3), per-mesh vertex/face offsets, per-mesh timepoints, per-mesh RGB colors (uint8), per-mesh cell IDs |
| `animation_metadata.json` | Dataset name, num_timepoints, z_spacing, mesh/vertex/face counts, format version |
| `animation_quant.parquet` | Per-cell per-timepoint measurements: volume, surface_area, center (x/y/z), displacement, distance |

The file dialog accepts the `.npz` file, the `.json` metadata file, or the bundle directory itself -- all resolve to the same bundle.

### Raw dataset (pipeline path)

**File > Open Dataset** accepts a raw outline dataset directory structured as:

```
dataset_root/
  t1/, t2/, ..., tN/
    *_cp_outlines.txt
```

This invokes `Perf/BioVision/main.py` as a subprocess with flags `--outlines-dir <dir> --use-cp-outlines --animation-format npz-only --quant-table-format parquet-only`. The pipeline runs in a background thread. When it finishes, the resulting bundle is loaded automatically.

## Window Layout

```
+------------------------------------------+
| Menu Bar                                 |
+-------------------------------+----------+
|                               | Selection|
|       3D Viewport             | tab      |
|       (VTK render area)       |----------+
|                               |Clustering|
|                               | tab      |
+-------------------------------+----------+
| [Play/Pause] [1 / 46] [====slider====]  |
+------------------------------------------+
| Status bar                    [progress] |
+------------------------------------------+
```

- **3D Viewport** -- the main rendering area, fills all available horizontal space (min 400px wide)
- **Right panel** -- fixed 280px wide tab widget with Selection and Clustering tabs
- **Timeline** -- fixed 56px tall bar at the bottom
- **Status bar** -- shows load status messages and an indeterminate progress bar during I/O
- The viewport and right panel are separated by a draggable `QSplitter`

## 3D Viewport

The viewport embeds VTK inside Qt via `QVTKRenderWindowInteractor` with a `vtkGenericOpenGLRenderWindow`. It renders solid triangle meshes with per-cell RGB colors from the bundle.

### Navigation (Blender-like controls)

The interactor style is ported from the C++ codebase (`arc-c++/src/render/vtk/vtk_render_backend.cpp`). VTK's default key bindings (notably `w`/`s` for wireframe/surface toggle) are suppressed.

#### Mouse

| Input | Action |
|---|---|
| Left click | Select cell (pick) |
| Alt + Left drag | Orbit (rotate around focal point) |
| Middle drag | Orbit |
| Shift + Middle drag | Pan |
| Ctrl + Middle drag | Dolly (zoom) |
| Right drag | Dolly (zoom) |

#### Keyboard -- free-fly camera

| Key | Action |
|---|---|
| `W` | Move forward |
| `S` | Move backward |
| `A` | Strafe left |
| `D` | Strafe right |
| `Q` | Move up |
| `E` | Move down |
| `F` | Fit scene (reset camera to show all actors) |
| Arrow Left/Right | Yaw (rotate view horizontally) |
| Arrow Up/Down | Pitch (rotate view vertically) |

Hold `Shift` with any WASD/QE key for 4x movement speed. Movement distance scales with camera-to-focal-point distance (8% of distance per step, minimum 5.0 units).

#### Keyboard -- axis snap views

| Key | Action |
|---|---|
| `1` / Numpad 1 | Front view (look along -Y) |
| Ctrl + `1` | Back view (look along +Y) |
| `3` / Numpad 3 | Right view (look along +X) |
| Ctrl + `3` | Left view (look along -X) |
| `7` / Numpad 7 | Top view (look along +Z) |
| Ctrl + `7` | Bottom view (look along -Z) |

Axis views set the view-up vector appropriately (Z-up for front/side views, Y-up for top view) and maintain the current camera-to-focal-point distance.

### Cell picking

Left-clicking a mesh performs a `vtkCellPicker` hit test (tolerance 0.0005). If a cell actor is hit, the `on_cell_picked` callback fires and the Selection sidebar updates. Alt+Left is excluded from picking (it triggers orbit instead).

The backend maintains bidirectional lookup maps between VTK actors and cell IDs (`_actors_by_cell` and `_cell_by_actor`) so picked actors resolve to cell identity in O(1).

## Menus

### File

- **Open Animation Bundle...** -- file dialog filtered for `.npz` / `.json` / all files. Loads in a background `QThread` with indeterminate progress bar.
- **Open Dataset...** -- directory chooser. Runs the BioVision pipeline as a subprocess in a background `QThread`, then auto-loads the resulting bundle.
- **Quit** -- closes the window.

### View

- **Wireframe** (checkable) -- toggles all meshes between solid surface and wireframe representation. Rebuilds the active frame's actors.
- **Fit Scene** -- calls `vtkRenderer.ResetCamera()` to frame all visible actors.

## Selection Sidebar

A read-only two-column `QTableWidget` (Property / Value). Updated on cell pick with:

- `cell_id` -- the cell's string identifier from the bundle
- `color` -- the cell's RGB color as normalized floats
- Quantitative properties from the parquet table (if loaded): `volume`, `surface_area`, `center_x`, `center_y`, `center_z`, `displacement`, `distance`

The quant lookup uses a `(cell_id, timepoint)` composite key, so properties reflect the specific timepoint currently displayed.

## Timeline

A horizontal panel with three elements:

- **Play/Pause button** (60px) -- toggles a `QTimer` at 120ms interval
- **Label** (80px) -- shows `current / total` (1-indexed)
- **Slider** -- scrubs between timepoints, emits `timepoint_changed(int)` on value change

During playback the slider auto-advances and wraps from the last frame back to the first. Dragging the slider during playback updates the display immediately.

When a bundle is loaded, the timeline configures itself from the scene's frame count. Each slider position maps to a `RenderFrame` timepoint via the `_timepoint_list` index.

## Clustering Panel (stub)

The Clustering tab provides UI controls for future clustering functionality:

- **Method** combo: KMeans, Spectral, HDBSCAN
- **k** spinner: range 2-50, default 5
- **Feature checkboxes**: volume, surface_area, displacement, distance (all checked by default)
- **Run Clustering** button (disabled)
- **Results** text area (read-only, placeholder text)

Clustering execution is not wired up -- this is a Phase 2 feature.

## Architecture

### Module map

```
Arc/
  main.py                        Entry point
  __init__.py

  core/
    render_types.py              Data types (dataclasses + enums)

  io/
    bundle_loader.py             .npz bundle -> RenderScene
    pipeline_runner.py           Subprocess wrapper for BioVision pipeline

  render/
    backend.py                   IRenderBackend Protocol
    vtk_backend.py               VTK implementation (~370 lines)
    vtk_interactor.py            BlenderLikeInteractorStyle

  app/
    main_window.py               QMainWindow orchestration
    viewport.py                  QVTKRenderWindowInteractor wrapper
    sidebar.py                   Cell property table
    timeline.py                  Play/pause + slider
    clustering_panel.py          UI stub
    theme.py                     Dark Fusion palette + QSS
```

### Render types (`Arc/core/render_types.py`)

All data flows through these types, ported from `arc-c++/src/render/api/render_types.hpp`:

- **`MeshGeometry`** -- holds `vertices` (Nx3 float32 numpy array) and `faces` (Mx3 uint32 numpy array) plus a `PrimitiveType` (Triangles or Lines). Using numpy arrays instead of Python lists enables near-zero-copy transfer to VTK via `numpy_to_vtk`.
- **`CellStyle`** -- per-cell color (RGB float tuple), opacity, wireframe flag, visibility, line width.
- **`RenderCellMesh`** -- one mesh: cell_id, track_id, geometry, style, metadata dict.
- **`RenderFrame`** -- one timepoint: list of `RenderCellMesh`.
- **`RenderScene`** -- the full animation: list of `RenderFrame`.
- **`RenderInitOptions`** -- background color, axes toggle.

### Render backend (`Arc/render/vtk_backend.py`)

`VtkRenderBackend` implements the `IRenderBackend` protocol (defined in `backend.py`). Key behaviors:

- **Scene management**: `set_scene()` indexes frames by timepoint in `_frames_by_tp`. `set_timepoint()` triggers `_rebuild_active_frame()` which clears all actors, builds new ones for the target frame, and renders.
- **Actor construction**: `_build_actor()` converts numpy vertex/face arrays to VTK data structures using `numpy_to_vtk` for points and `numpy_to_vtkIdTypeArray` for cell connectivity. Triangle connectivity is packed as `[3, i0, i1, i2, ...]` for `vtkCellArray.SetCells()`.
- **Style application**: `_apply_style()` sets color, opacity, line width, visibility, and representation (surface vs wireframe) on each actor's `vtkProperty`.
- **Picking**: A `vtkCellPicker` (tolerance 0.0005) fires on left-click. The actor-to-cell-ID reverse map resolves the pick to a cell identity.
- **Camera**: WASD/QE free-fly and arrow key rotation use Rodrigues' rotation formula (`_rotate_axis_angle`). Axis snap views (1/3/7) set camera position at `focal + dist * axis` with appropriate view-up.

### Bundle loader (`Arc/io/bundle_loader.py`)

`load_bundle(path)` returns `(RenderScene, metadata_dict, quant_table)`:

1. Resolves the path to a bundle directory (accepts `.npz`, `.json`, or directory)
2. Loads `animation_metadata.json` for dataset name, timepoint count, z-spacing
3. Opens `animation_meshes.npz` with `np.load(allow_pickle=False)`
4. Bulk-converts all vertices from float16 to float32 in one operation (~0.2s for 30M vertices)
5. Iterates 8854 meshes, slicing vertex/face arrays by offsets, normalizing colors from uint8 to float, and assembling `RenderCellMesh` objects grouped into `RenderFrame` by timepoint
6. Loads `animation_quant.parquet` (via pandas) into a `(cell_id, timepoint) -> dict` lookup table

Total load time for the A1 dataset (30M vertices, 60M faces, 8854 meshes, 46 timepoints): ~6 seconds.

### Pipeline runner (`Arc/io/pipeline_runner.py`)

`run_pipeline(dataset_dir)` invokes `Perf/BioVision/main.py` as a subprocess:

```
python Perf/BioVision/main.py \
  --outlines-dir <dataset_dir> \
  --use-cp-outlines \
  --animation-format npz-only \
  --quant-table-format parquet-only
```

Returns the path to the resulting animation bundle directory. The GUI runs this in a `QThread` and auto-loads the bundle on completion.

### Threading model

Both bundle loading and pipeline execution run in background `QThread`s via `QObject.moveToThread()`. The workers emit `finished` or `error` signals back to the main thread. The main window shows an indeterminate `QProgressBar` during these operations. Worker objects are prevented from garbage collection by storing references on `self`.

### Theme (`Arc/app/theme.py`)

Dark theme using Qt's Fusion style with a custom `QPalette` and QSS overrides. Design tokens from the Figma design document:

| Token | Hex | Usage |
|---|---|---|
| Window | `#1A1C1F` | Main background |
| Base | `#141619` | Input fields, table cells, status bar |
| Surface | `#24272C` | Buttons, headers, menus, tooltips |
| Text | `#E8ECF0` | Primary text |
| Text Dim | `#8B919A` | Disabled text, placeholder, secondary labels |
| Accent | `#418CD2` | Selection highlight, slider handle, progress bar |
| Border | `#35393F` | All borders, grid lines, separators |

The QSS covers: menu bar, menus, tabs, tables, headers, sliders (groove + handle + sub-page), buttons (normal/hover/pressed/disabled), spin boxes, combo boxes, checkboxes, splitter handles, text edits, status bar, and progress bar.

## Test data

Pre-computed A1 bundle at `Perf/BioVision/output/A1_profile/A1 ANIMATION/`:

- 8,854 meshes across 46 timepoints
- 29,998,852 vertices (float16), 59,967,232 faces (uint32)
- 155,940 quantification rows in the parquet table
- Bundle size: ~271 MB (`.npz`) + 12 MB (`.parquet`)

## Not yet implemented

These features are planned for future phases:

- Clustering execution (UI is stubbed but the Run button is disabled)
- Tracer curve rendering (cell movement trajectories)
- Color filter panel (show/hide cells by RGB color, as in the Blender add-on)
- Z-scale control slider
- Video export
- Multiple simultaneous bundles
