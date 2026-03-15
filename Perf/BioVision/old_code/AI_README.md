# AI Pipeline README

This document covers the image-folder / AI-segmentation pipeline wrapped by
`profile_readme_pipeline.py`.

It is the current path for datasets like `A1`, and it intentionally does not
use `full_pipeline.py`.

## What This Script Does

`profile_readme_pipeline.py` is a wrapper around the current README pipeline:

1. AI segmentation from an image folder such as `A1`
2. Conversion of segmentation output into a `WIREFRAME` pickle
3. Color extraction from that wireframe
4. Cell matching across Z and time
5. Quantification export
6. Tracer export
7. Solid mesh export
8. Optional flamegraph generation with `py-spy`

Step 3 of the old README flow, Blender rendering, is not run by this script.

## Supported Input Modes

The script supports two mutually exclusive input modes:

- `--images-dir`: AI pipeline from raw image folders such as `A1`
- `--outlines-dir`: manual-outline README pipeline

This file focuses on `--images-dir`.

## AI Pipeline Overview

For `--images-dir`, the flow is:

```text
images folder
  -> segment_images_to_animation.py
  -> RAW segmentation JSON
  -> WIREFRAME pickle
  -> color extraction
  -> matched cells
  -> quant CSV
  -> TRACERS.pkl
  -> SOLIDS.pkl
  -> optional flamegraph SVG
```

The segmentation step is delegated to:

`../../arc-c++/tools/segment_images_to_animation.py`

By default, the segmentation model is `cellpose-sam`.

## Important Behavior in Image Mode

The segmentation JSON contains arbitrary segmentation colors. Those colors are
not stable biological IDs, so the wrapper normalizes all segmented contours to
one match color before matching.

Default:

- `--segmentation-match-color 255,0,0`

Debug-only option:

- `--preserve-segmentation-colors`

Do not use `--preserve-segmentation-colors` for normal A1-style runs. It tends
to destroy matching quality because segmentation colors are not identity labels.

## Basic Commands

Run the full profiled AI pipeline and generate a flamegraph:

```bash
uv run python profile_readme_pipeline.py \
  --images-dir A1 \
  --output-dir output/A1_profile
```

Run the pipeline directly without generating a flamegraph:

```bash
uv run python profile_readme_pipeline.py \
  --_profiled-run \
  --images-dir A1 \
  --output-dir output/A1_profile
```

Reuse an existing segmentation JSON instead of regenerating it:

```bash
uv run python profile_readme_pipeline.py \
  --_profiled-run \
  --images-dir A1 \
  --segmentation-json-input output/A1_profile/segmentation/A1_cellpose_sam_raw.json \
  --output-dir output/A1_profile_rerun
```

Generate a flamegraph while reusing an existing segmentation JSON:

```bash
uv run python profile_readme_pipeline.py \
  --images-dir A1 \
  --segmentation-json-input output/A1_profile/segmentation/A1_cellpose_sam_raw.json \
  --output-dir output/A1_profile_rerun
```

## Profiling Behavior

The script has two execution modes:

- default mode: runs under `py-spy` and writes a flamegraph
- `--_profiled-run`: runs the pipeline body directly with no flamegraph

If you use `--_profiled-run`, no flamegraph SVG will be created.

Useful profiling options:

- `--flamegraph-output`
- `--profile-rate`
- `--profile-subprocesses`
- `--py-spy`
- `--python`

By default, subprocesses such as segmentation are included in profiling.

## Segmentation Options

Useful image-mode segmentation flags:

- `--segmentation-model {cellpose,cellpose-sam,cellsam}`
- `--segmentation-device {auto,cpu,gpu}`
- `--segmentation-diameter`
- `--segmentation-min-area`
- `--segmentation-z-spacing`
- `--segmentation-output-dir`
- `--segmentation-output-json`
- `--segmentation-json-input`
- `--segmentation-match-color`
- `--preserve-segmentation-colors`

Default model:

- `cellpose-sam`

Default device:

- `auto`

## Output Files

By default, outputs go to:

`output/<dataset_name>_profile/`

For `A1`, typical outputs are:

- `output/A1_profile/A1.pkl`
- `output/A1_profile/A1 matched_cells.pkl`
- `output/A1_profile/A1 matched_cells_tp_num.pkl`
- `output/A1_profile/A1 QUANT DATA.csv`
- `output/A1_profile/A1 TRACERS.pkl`
- `output/A1_profile/A1 SOLIDS.pkl`
- `output/A1_profile/A1_pipeline.log`
- `output/A1_profile/A1_pipeline_flamegraph.svg`

Segmentation artifacts go under:

- `output/A1_profile/segmentation/`

Typical segmentation outputs:

- `output/A1_profile/segmentation/A1_cellpose_sam_raw.json`
- `output/A1_profile/segmentation/outlines/`
- `output/A1_profile/segmentation/masks/`

## What Each Output Means

`A1.pkl`

- `WIREFRAME` pickle used as the intermediate input to matching and quant
- in image mode, this is built from the RAW segmentation JSON

`A1 matched_cells.pkl`

- matched `Cell3D` objects across time

`A1 matched_cells_tp_num.pkl`

- timepoint count used by the quant exporter

`A1 QUANT DATA.csv`

- per-cell, per-timepoint measurements
- includes position, displacement, distance traveled, volume, and surface area

`A1 TRACERS.pkl`

- cell center trajectories over time

`A1 SOLIDS.pkl`

- solid mesh export with header `MESH`
- this is the main 3D geometry artifact from the pipeline

`A1_pipeline.log`

- very verbose matcher and mesh-generation log
- useful when tmux or terminal output would otherwise get flooded

`A1_pipeline_flamegraph.svg`

- flamegraph written by `py-spy`
- only produced when the outer profiling wrapper is used

## A1-Specific Notes

### Why the wireframe colors are normalized

For A1-style segmentation data, the raw segmentation colors are not real cell
identities. The wrapper therefore collapses them to one match color before the
matching stage.

### Why `A1.pkl` is not a good ARC C++ cell viewer artifact

In image mode, `A1.pkl` is a normalized-color intermediate used for matching.
That is fine for the Python pipeline, but it is not a good cell-level display
artifact for ARC C++ because many contours share the same color bucket.

For geometry viewing, use `A1 SOLIDS.pkl`, not `A1.pkl`.

## Logging and Stability Notes

The downstream matching and mesh stages can produce a very large amount of
output. By default, the script redirects that chatter into the pipeline log
instead of the terminal.

If you want the old noisy behavior, use:

```bash
--verbose-substeps
```

The mesh exporter also writes a more compact mesh payload than the old pipeline
to reduce peak memory use when building `SOLIDS.pkl`.

## Manual-Outline Mode

The same script also supports the current README-style manual-outline path:

```bash
uv run python profile_readme_pipeline.py \
  --outlines-dir path/to/manual_outlines \
  --run-lexographic-renaming \
  --find-reference-points \
  --find-rotation-points \
  --rotate
```

Optional flags for manual-outline mode include:

- `--svg`
- `--image-dims`
- `--find-reference-points`
- `--find-rotation-points`
- `--reference-point-color`
- `--rotation-point-color`
- `--rotate`
- `--no-sort-large-groups`
- `--skip-slice`

## Troubleshooting

### No flamegraph was created

You probably used `--_profiled-run`. That mode skips `py-spy`.

### `py-spy` not found

Install `py-spy` or pass `--py-spy` with the correct executable path.

### Matching looks wrong in image mode

Do not preserve segmentation colors unless you are debugging. Use the default
single normalized match color.

### The run is too noisy in tmux

Use the default log redirection and inspect `*_pipeline.log` instead of
streaming substep logs to the terminal.

### Segmentation is slow and you want to rerun later stages only

Reuse the existing RAW segmentation JSON with `--segmentation-json-input`.

## Summary

`profile_readme_pipeline.py` is the current wrapper for both:

- the README manual-outline pipeline
- the AI image-folder pipeline used for datasets like `A1`

For AI runs, the main idea is:

images -> segmentation JSON -> wireframe -> matching -> quant/tracers/solids

Use normal mode when you want a flamegraph, and use `--_profiled-run` when you
want to debug or test the pipeline without profiling.
