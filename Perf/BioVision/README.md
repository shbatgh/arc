# BioVision

BioVision converts manually segmented 2D biological slice images into interactive 3D animations in Blender, with quantitative analysis of cell morphology and movement.

## Prerequisites

- Python 3.8+
- Blender 2.80+ (for rendering)
- Python packages: `numpy`, `pandas`, `pyarrow`, `Pillow`, `trimesh`, `pickle` (stdlib)

## Project Structure

```
biovision/
├── processing/
│   ├── translators/                  # Data preprocessing and format conversion
│   │   ├── pickled_pre_visualization_phase.py   # Main entry point (Step 1)
│   │   ├── formatting_preparation.py            # Reference/rotation point detection
│   │   ├── formatting_preparation_SVG.py        # SVG variant
│   │   ├── v10manual_segmentation_formatter.py  # PNG outline extraction
│   │   ├── v10manual_segmentation_formatter_SVG.py  # SVG outline extraction
│   │   ├── lexographic_renaming.py              # File naming standardization
│   │   ├── color_extractor.py                   # Extract cell colors from wireframe
│   │   ├── adjust_algorithm.py                  # Translation and rotation correction
│   │   ├── sort_angle_algorithm.py              # Outline point sorting (angle-based)
│   │   ├── sort_loose_travelling_salesman_algorithm.py  # Outline sorting (TSP-based)
│   │   └── sort_robust_outline.py               # Robust outline sorting
│   ├── mesh_creation/                # 3D mesh generation
│   │   ├── cell_point_filler.py                 # Spline interpolation
│   │   ├── contour_stitching_mesh.py            # Contour-to-mesh conversion
│   │   └── seal_mesh.py                         # Mesh repair/watertighting
│   ├── pickled_quant_data.py         # Quantitative analysis (Step 2)
│   ├── get_matched_cells.py          # Cell matching coordinator
│   ├── pickled_animation_cell_matching.py  # Cross-timepoint cell tracking
│   └── single_stack_cell_matching.py      # Within-timepoint cell matching
└── visualizing/
    └── pickled_renderer.py           # Blender add-on for rendering (Step 3)
```

## Pipeline Overview

```
 Input Images          Step 1                    Step 2                 Step 3
┌──────────┐    ┌──────────────────┐    ┌───────────────────┐    ┌──────────────┐
│ Timepoint│    │ pickled_pre_     │    │ pickled_quant_    │    │ pickled_     │
│ folders  │───>│ visualization_   │───>│ data.py           │───>│ renderer.py  │
│ of slice │    │ phase.py         │    │                   │    │ (Blender)    │
│ images   │    │                  │    │ Outputs:          │    │              │
│ (PNG/SVG)│    │ Output:          │    │ - quant .parquet  │    │ Renders:     │
│          │    │ WIREFRAME .pkl   │    │ - animation bundle│    │ - wireframes │
└──────────┘    └──────────────────┘    │ - MESH .pkl       │    │ - solid mesh │
                                        │ - TRACER .pkl     │    │ - tracers    │
                                        └───────────────────┘    └──────────────┘
```

## Input Data Format

Input data is a folder of timepoint subfolders, each containing numbered slice images (PNG or SVG):

```
my_animation/
├── t1/
│   ├── 01.png
│   ├── 02.png
│   └── ...
├── t2/
│   ├── 01.png
│   ├── 02.png
│   └── ...
└── ...
```

Each slice image contains manually drawn cell outlines as colored pixels. Each unique RGB color represents a different cell type or individual cell. Two special marker colors can also be drawn:

- **Reference point** (e.g. yellow `(255, 255, 0)`): Corrects for specimen drift between timepoints
- **Rotation point** (e.g. green `(0, 255, 0)`): Corrects for specimen rotation between timepoints

## Step 0: Lexographic Renaming (if needed)

If your files aren't named with leading zeros (e.g. `4.png` instead of `04.png`), the pipeline will fail to read slices in the correct order. Run the lexographic renaming utility first:

```python
import lexographic_renaming

# Rename timepoint folders (t1 -> t01, t2 -> t02, etc.)
lexographic_renaming.rename(
    path="path/to/my_animation",
    file_or_folder='folder',
    name_length='auto'  # or set an integer like 4
)

# Rename slice files within each timepoint
import os
for tp in [f.path for f in os.scandir("path/to/my_animation") if f.is_dir()]:
    lexographic_renaming.rename(
        path=tp,
        file_or_folder='file',
        name_length='auto'
    )
```

## Step 1: Generate Wireframe Data

Run `processing/translators/pickled_pre_visualization_phase.py`. This is an interactive script that walks you through two sub-steps:

### 1a. Formatting Preparation

Detects image dimensions, reference points, and rotation points from the input images.

**Configuration** (edit variables in the script):

| Variable | Description | Example |
|---|---|---|
| `path_to_timepoints` | Path to the folder of timepoint subfolders | `"C:/Data/my_animation"` |
| `reference_point_color` | RGB color of the reference point marker | `(255, 255, 0)` |
| `rotation_point_color` | RGB color of the rotation point marker | `(0, 255, 0)` |
| `manually_set_image_dims` | Image dimensions `[width, height]`, or `False` for auto-detect | `[512, 512]` |
| `SVG` | Set `True` at the top of the file if using SVG input | `False` |

The script will prompt you:
- **"Run formatting preparation?"** -- Yes, this must run first.
- **"Find reference points?"** -- Yes if your specimen drifts between timepoints. No sets all reference points to `[0, 0]`.
- **"Find rotation points?"** -- Yes if your specimen rotates between timepoints. No sets rotation to `None`.

### 1b. Manual Segmentation Formatter

Extracts cell outlines from the colored pixels in each slice image, sorts the outline points into the correct order, and applies reference point / rotation corrections.

**Configuration** (edit variables in the script):

| Variable | Description | Example |
|---|---|---|
| `output_file` | Path for the output `.pkl` file | `"C:/Output/my_animation.pkl"` |
| `path_to_timepoints` | Same as above | `"C:/Data/my_animation"` |
| `sort_large_groups` | Sort outlines from large cells (slower but cleaner) | `True` |
| `rotate` | Apply rotation correction | `True` |

**Output**: A `.pkl` file with the header `WIREFRAME` containing the structured outline data.

## Step 1.5: Color Extraction (between Step 1 and 2)

After generating the wireframe `.pkl`, you need to extract the list of cell colors to pass into Step 2. Run `processing/translators/color_extractor.py`:

```python
import color_extractor

header, parsed_data = color_extractor.get_data("path/to/my_animation.pkl")
colors = color_extractor.extract(parsed_data, skip_slice=0)
print(colors)
# Example output: [(255, 0, 0), (0, 0, 255), (0, 255, 255), ...]
```

Copy the printed color list -- you will paste it into the next step.

The `skip_slice` parameter can be used to ignore the first/last N slices when extracting colors (useful if edge slices have noise). Only outlines with more than 14 points are considered real cells.

## Step 2: Quantitative Analysis and Mesh Generation

Run `BioVision/main.py` for the current bundle export flow, or
`processing/pickled_quant_data.py` for the legacy CSV/pickle-only path. This stage:

1. **Matches cells across timepoints** -- Tracks which cell in timepoint N corresponds to which cell in timepoint N+1, using proximity-based matching.
2. **Generates 3D meshes** -- Converts 2D slice outlines into 3D solid meshes using spline interpolation and contour stitching.
3. **Computes quantitative data** -- Calculates position, displacement, distance traveled, volume, and surface area for each cell at each timepoint.
4. **Exports results** in multiple formats.

### Running

The script prompts **"Match cells?"** -- answer yes on first run to generate the matched cell data. On subsequent runs you can skip this if the matched cells `.pkl` already exists.

**Configuration** (edit variables in `__main__`):

| Variable | Description | Example |
|---|---|---|
| `path` | Path to the WIREFRAME `.pkl` from Step 1 | `"C:/Output/my_animation.pkl"` |
| `colors` | List of RGB tuples from the color extraction step | `[(255, 0, 0), (0, 0, 255)]` |
| `output_path` | Path to save matched cells `.pkl` | `"C:/Output/matched_cells.pkl"` |

`BioVision/main.py` writes the bundle-based outputs below while still keeping
the legacy animation pickle during migration.

### Outputs

| Output | Format | Description |
|---|---|---|
| Quantitative data | `.parquet` | Per-cell, per-timepoint metrics in a flat table written by `BioVision/main.py` |
| Animation bundle | directory with `.npz` + `.json` + `.parquet` | Binary mesh container, metadata manifest, and tabular quant data |
| Legacy quant table | `.csv` | Optional compatibility export while migrating away from the CSV path |
| Solid meshes | `.pkl` (header: `MESH`) | 3D mesh vertices and faces for each cell at each timepoint |
| Tracers | `.pkl` (header: `TRACER`) | Cell center trajectories over time |
| Matched cells | `.pkl` | Intermediate file of Cell3D objects for reuse |

### CSV Columns

| Column | Description |
|---|---|
| `Cell ID` | Unique cell identifier |
| `Timepoint` | Timepoint index |
| `Position` | 3D center `(x, y, z)` |
| `X Pos`, `Y Pos`, `Z Pos` | Individual position components |
| `Displacement Vector` | Movement from previous timepoint `(dx, dy, dz)` |
| `X Disp`, `Y Disp`, `Z Disp` | Individual displacement components |
| `Distance Traveled` | Euclidean distance moved from previous timepoint |
| `Volume` | Cell volume computed from 3D mesh |
| `Surface Area` | Cell surface area computed from 3D mesh |

### Mesh Parameters

These can be tuned at the top of `pickled_quant_data.py`:

| Parameter | Default | Description |
|---|---|---|
| `tens` | `-0.75` | Kochanek-Bartels spline tension |
| `cont` | `0` | Spline continuity |
| `bias` | `0` | Spline bias |
| `points_per_segment` | `8` | Interpolation density per spline segment |
| `round_decimal_place` | `1` | Decimal places in CSV output (`False` to disable) |

## Step 3: Render in Blender

`visualizing/pickled_renderer.py` is a Blender add-on that loads the `.pkl` files and creates an animated 3D scene.

### Installation

1. Open Blender
2. Go to **Edit > Preferences > Add-ons**
3. Click **Install** and select `pickled_renderer.py`
4. Enable the "BioVision" add-on

### Usage

1. Open the sidebar in the 3D Viewport (press `N`)
2. Find the **"Render File"** tab
3. Click **"Choose Path"** and select a `.pkl` file
4. Click **"Render"**
5. Use the timeline to scrub through timepoints (10 Blender frames = 1 biological timepoint)

### Supported File Types

| `.pkl` Header | What It Renders |
|---|---|
| `WIREFRAME` | NURBS curves tracing cell outlines per slice |
| `MESH` | 3D solid mesh geometry for each cell |
| `TRACER` | Continuous curves showing cell movement trajectories |

You can load multiple files into the same scene (e.g. wireframes + meshes + tracers together).

### Controls

- **Z Scale** slider: Exaggerate or compress the Z-axis (default `0.7`, range `0.01` - `5.0`). Useful because biological specimens are often very thin relative to their width.
- **Show/Hide Color** panel: Filter objects by RGB color to isolate specific cells.

## Full Example Workflow

```
1.  Rename files for correct ordering
      lexographic_renaming.py

2.  Run the pre-visualization phase
      pickled_pre_visualization_phase.py
      -> Outputs: my_animation.pkl (WIREFRAME)

3.  Extract colors from the wireframe
      color_extractor.py
      -> Outputs: list of RGB tuples

4.  Run quantitative analysis
      BioVision/main.py
      -> Outputs: animation_quant.parquet
                  animation_metadata.json
                  animation_meshes.npz
                  my_animation_SOLIDS.pkl (MESH)
                  my_animation_TRACERS.pkl (TRACER)

5.  Render in Blender
      Install pickled_renderer.py as add-on
      Load .pkl files and render
```

## Authors

Taj Chhabra and Samuel Boccara
