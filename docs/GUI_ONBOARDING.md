# GUI Onboarding Guide

This document is the deep technical guide for the ARC desktop GUI stack in `Arc/app/` and its runtime coupling to `Arc/core/`.

## Scope

Covered:
- app boot flow (`Arc/main.py`)
- Qt widget topology (`Arc/app/main_window.py`)
- VTK rendering and picking (`Arc/render/vtk_backend.py`)
- timeline playback (`Arc/app/timeline.py`)
- property sidebar behavior (`Arc/app/sidebar.py`)
- clustering UI stub (`Arc/app/clustering_panel.py`)
- data types (`Arc/core/render_types.py`)

Not covered:
- `arc-c++/` (experimental)
- Blender add-on scripts in `BioVision/visualizing`

## Mental Model

ARC GUI is a thin orchestrator over three independent domains:

1. **Data domain**
   - `Project` -> `Scene` -> `Cell`
2. **Rendering domain**
   - VTK actor graph managed through vedo `Plotter`
3. **Analysis domain**
   - clustering jobs executed in a Qt worker thread

The main window owns all three and synchronizes them by signal/slot events.

## Boot Sequence

Entry: `Arc/main.py`

1. Create `QApplication`
2. Apply stylesheet from `Arc/resources/styles/dark.qss`
3. Instantiate `MainWindow`
4. Show window and enter event loop (`app.exec()`)

Important details:
- GUI style object names (`TimelineTimepointLabel`, `SidebarTitle`, etc.) are expected by the QSS file.

## MainWindow Composition

`Arc/app/main_window.py`

Child widgets:
- `Viewport` (left, expanding) — wraps `Arc/render/vtk_backend.py`
- `QTabWidget` on right with:
  - `Sidebar` tab (`Selection`)
  - `ClusteringPanel` tab (`Clustering`)
- `Timeline` at bottom

## Import Flow (End to End)

Trigger path:

```text
File menu -> Import Dataset Folder...
  -> get_import_folder()
  -> mode picker (Solid/Mesh/Raw)
  -> load_dataset_from_root(folder, mode)
  -> track cells across scenes
  -> find or generate clustering CSV
  -> initialize timeline and render first scene
```

### Detailed behavior

1. `load_dataset_from_root()` returns `(project, timepoints)`.
2. If no valid timepoints, user sees info dialog and state is unchanged.
3. On success:
   - previous cluster map/colors are cleared
   - `_track_cells()` computes 4D track IDs
   - `_setup_clustering_data()` chooses CSV source
   - timeline range is reset and index 0 is displayed

## Scene Display Pipeline

`MainWindow._show_timepoint_index(index)`:

1. clamps index to valid slider range
2. resolves actual timepoint value (`tN`) from `_timepoints`
3. gets corresponding `Scene` from `project.scenes`
4. applies cluster colors (if clustering already ran)
5. calls `viewer.display_scene(scene)`
6. updates timeline label (`t<timepoint>`)

Side effect expectation:
- every timepoint switch rebuilds render actors via `display_scene()` (clear + add meshes + reset camera)

## Render Backend Internals

`Arc/render/vtk_backend.py`

### Core objects

- VTK render window and renderer
- `vtkCellPicker` for cell selection
- actor lookup map for cell_id resolution
- Blender-like interactor style (`Arc/render/vtk_interactor.py`)

### Picking

Left-click resolves picked actor and maps to `cell_id`.

### Rendering lifecycle

- Scene display clears previous actors, adds new ones from `RenderScene`
- Camera resets on each scene switch

## Timeline Mechanics

`Arc/app/timeline.py`

Components:
- play/pause button
- current timepoint label
- horizontal slider
- `QTimer` (250 ms interval)

Playback behavior:
- when slider reaches max, wraps to zero
- `set_range(count)` resets playback state and slider bounds

Because timepoint display is keyed off slider value changed signal, playback and manual scrubbing use identical scene update code.

## Sidebar Mechanics

`Arc/app/sidebar.py`

- Displays a 2-column `QTableWidget`
- `update_properties(dict)` fully repopulates rows on each selection

No diffing/caching is applied; this is simple but deterministic.

## Selection Data Contract

`MainWindow._on_cell_picked(cell_id)` assembles display properties from:
- geometry: `volume`, `area`, `center` (`Cell` wrapper)
- scene context: current timepoint
- tracking metadata: `display_id`, `track_id`, `t_start`, `t_end`
- clustering metadata: `cluster`
- any other metadata keys not in skip set

Skip keys:
- `curves`, `display_id`, `track_id`, `t_start`, `t_end`, `id`

If you add new metadata at load time, it auto-surfaces unless filtered.

## Clustering Panel Internals

`Arc/app/clustering_panel.py`

### UI features

- method dropdown: `kmeans`, `spectral`, `hdbscan`
- cluster count spinbox (disabled for HDBSCAN)
- correlated feature removal toggle + threshold
- feature checkbox list (`AVAILABLE_FEATURES` map)
- CSV chooser and run button

### Worker thread lifecycle

`ClusteringWorker(QThread)`:

1. `load_data()`
2. `extract_features()`
3. `perform_clustering(...)`
4. build `cluster_map` from resulting dataframe
5. compute summary (`n_clusters`, `silhouette_score`)
6. emit `finished(result_dict)`

Main window receives result and:
- stores cluster map
- generates color palette (`tab10`, gray for outliers `-1`)
- writes cluster id into each cell metadata
- re-renders current scene with cluster colors

## Color Mapping Strategy

- cluster colors stored in `_cluster_colors`
- key is cluster id
- value is `(r, g, b)` float triplet
- mapping is track-based, not per-observation ID-based

This is critical: color consistency over time depends on `track_id` consistency.

## Data Layer Contracts

### `RenderScene` / `RenderFrame` / `RenderCellMesh` (`Arc/core/render_types.py`)

- `RenderScene` contains a list of `RenderFrame` (one per timepoint)
- `RenderFrame` contains a list of `RenderCellMesh`
- `RenderCellMesh` has `cell_id`, `geometry` (vertices/faces), `style` (color/opacity), `metadata`

## Threading and Safety Notes

- UI updates happen on main Qt thread.
- Clustering calculations run in `QThread`; worker emits plain dict payloads.
- dataset reconstruction uses process pool in `pipeline_runner` for isolation from BioVision globals.

Never call GUI-mutating methods directly from worker threads.

## Styling and Visual System

Stylesheet: `Arc/resources/styles/dark.qss`

Key points:
- global typography, menu, button, slider, table, scrollbar styling
- targeted selectors by object name (`SidebarTitle`, `TimelineTimepointLabel`, etc.)

When adding widgets:
- set `objectName` if you want predictable styling hooks
- keep panel width assumptions in mind (right tab is fixed width 280)

## Extension Recipes

### Add a new sidebar field from geometry

1. compute value in `_on_cell_picked()`
2. add key/value to `props`
3. ensure value stringification is stable

### Add a new clustering feature checkbox

1. update `AVAILABLE_FEATURES` in `clustering_panel.py`
2. ensure mapped column exists in clustering output
3. if naming differs, update feature mapping in `cell_clustering.py::_map_selected_features`

### Add a new menu action

1. define `QAction` in `_build_menu()`
2. connect to slot method
3. keep long work off main thread

### Preserve camera between frames

Gate camera reset in `Arc/render/vtk_backend.py` scene display.

## Known Pitfalls

- Scene display always clears and rebuilds actors; any actor-side state is transient.
- Clustering relies on integer-convertible `cell_id`/`Cell ID` in analyzer output.
- If mesh loading fails per timepoint, scene may be absent; always guard for missing keys.

## Validation Checklist for GUI Changes

1. Import each mode (`raw`, `mesh`, `solid`) on sample dataset.
2. Scrub timeline and verify no stale actor picks.
3. Select cells in multiple frames and confirm sidebar updates.
4. Run each clustering method with a valid CSV.
5. Re-run clustering with different selected features.
6. Confirm cluster colors remain consistent across timepoints.
7. Check first import and cache reload paths both work.

## Code Pointers

- `Arc/main.py`
- `Arc/app/main_window.py`
- `Arc/app/segmentation_viewer.py`
- `Arc/app/viewport.py`
- `Arc/app/timeline.py`
- `Arc/app/sidebar.py`
- `Arc/app/clustering_panel.py`
- `Arc/core/render_types.py`
- `Arc/io/raw_outline_loader.py`
- `Arc/io/pipeline_runner.py`
- `Arc/render/vtk_backend.py`
- `Arc/render/vtk_interactor.py`

