"""Run Perf/BioVision/main.py pipeline on a raw dataset to produce an animation bundle."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
import subprocess
import sys
from pathlib import Path

from Arc.core.isolation_config import IsolationConfig

PIPELINE_SCRIPT = Path(__file__).resolve().parent.parent.parent / "Perf" / "BioVision" / "main.py"
ProgressCallback = Callable[[int, str], None]


def _emit_progress(
    progress_cb: ProgressCallback | None,
    value: int,
    label: str,
) -> None:
    if progress_cb is None:
        return
    progress_cb(max(0, min(100, int(value))), label)


def _count_timepoint_dirs(dataset_path: Path) -> int:
    return sum(1 for child in dataset_path.iterdir() if child.is_dir())


def _parse_progress_line(
    line: str,
    *,
    formatted_timepoints: int,
    total_timepoints: int,
) -> tuple[int | None, str | None, int]:
    stripped = line.strip()
    if not stripped:
        return None, None, formatted_timepoints

    if stripped.startswith("Isolating cells by"):
        return 1, "Isolating cells by color...", formatted_timepoints

    if stripped.startswith("Done.") and "outline files written" in stripped:
        return 2, stripped, formatted_timepoints

    if stripped.startswith("Formatting stack "):
        next_formatted = formatted_timepoints + 1
        if total_timepoints > 0:
            next_formatted = min(next_formatted, total_timepoints)
            progress = max(
                1,
                int((next_formatted * 20 + total_timepoints - 1) / total_timepoints),
            )
            label = f"Formatting outlines ({next_formatted}/{total_timepoints})..."
        else:
            progress = 20
            label = "Formatting outlines..."
        return progress, label, next_formatted

    if stripped.startswith("Finding reference points"):
        return 3, "Finding reference points...", formatted_timepoints

    if stripped.startswith("Finding rotation points"):
        return 6, "Finding rotation points...", formatted_timepoints

    if stripped.startswith("Image dimensions:"):
        return 3, "Reading image dimensions...", formatted_timepoints

    if stripped.startswith("Manual data formatting time taken:"):
        return 22, "Outline formatting complete", formatted_timepoints

    if stripped.startswith("Wireframe pickle written:"):
        return 25, "Wireframe generated", formatted_timepoints

    if stripped.startswith("Extracted ") and " colors" in stripped:
        return 30, stripped, formatted_timepoints

    if stripped.startswith("Verbose stage log:"):
        return 35, "Preparing quant stage...", formatted_timepoints

    if stripped == "Matching cells":
        return 40, "Matching cells...", formatted_timepoints

    if stripped.startswith("Matched ") and " cells across " in stripped:
        return 70, stripped, formatted_timepoints

    if stripped == "Writing tracers":
        return 78, "Writing tracers...", formatted_timepoints

    if stripped.startswith("Writing quant tables, mesh pickle, animation bundle"):
        return 85, "Writing animation bundle artifacts...", formatted_timepoints

    if stripped.startswith("Wrote animation bundle:"):
        return 95, "Animation bundle written", formatted_timepoints

    if stripped.startswith("Animation Bundle:"):
        return 100, "Pipeline complete", formatted_timepoints

    return None, None, formatted_timepoints


def run_pipeline(
    dataset_dir: str,
    output_dir: str | None = None,
    progress_cb: ProgressCallback | None = None,
    isolation_config: IsolationConfig | None = None,
) -> Path:
    """Invoke the BioVision pipeline and return the resulting bundle directory.

    Args:
        dataset_dir: Path to the raw dataset (contains t1/, t2/, ... folders).
        output_dir: Optional output directory. If None, defaults to pipeline's choice.

    Returns:
        Path to the animation bundle directory.

    Raises:
        FileNotFoundError: If the pipeline script doesn't exist.
        RuntimeError: If the pipeline subprocess fails.
    """
    if not PIPELINE_SCRIPT.exists():
        raise FileNotFoundError(f"Pipeline script not found: {PIPELINE_SCRIPT}")

    dataset_path = Path(dataset_dir).resolve()
    if not dataset_path.is_dir():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_path}")

    cmd = [
        sys.executable,
        "-u",
        str(PIPELINE_SCRIPT),
        "--_profiled-run",
        "--outlines-dir", str(dataset_path),
        "--use-cp-outlines",
        "--animation-format", "npz-only",
        "--quant-table-format", "parquet-only",
    ]

    if isolation_config is not None:
        cmd.extend(isolation_config.to_cli_args())

    if output_dir is not None:
        out_path = Path(output_dir).resolve()
        cmd.extend(["--output-dir", str(out_path)])

    total_timepoints = _count_timepoint_dirs(dataset_path)
    formatted_timepoints = 0
    current_progress = 1
    _emit_progress(progress_cb, current_progress, f"Starting pipeline: {dataset_path.name}...")

    output_lines: deque[str] = deque(maxlen=200)
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    ) as process:
        if process.stdout is None:
            raise RuntimeError("Pipeline failed to produce stdout")

        for raw_line in process.stdout:
            output_lines.append(raw_line.rstrip())
            progress, label, formatted_timepoints = _parse_progress_line(
                raw_line,
                formatted_timepoints=formatted_timepoints,
                total_timepoints=total_timepoints,
            )
            if progress is None or label is None:
                continue
            current_progress = max(current_progress, progress)
            _emit_progress(progress_cb, current_progress, label)

        returncode = process.wait()

    if returncode != 0:
        recent_output = "\n".join(line for line in output_lines if line).strip()
        raise RuntimeError(
            f"Pipeline failed (exit {returncode}):\n{recent_output or 'No output captured.'}"
        )

    # Find the animation bundle in the output
    # The pipeline writes to <output_dir>/<dataset_name> ANIMATION/
    dataset_name = dataset_path.name
    if output_dir:
        base = Path(output_dir).resolve()
    else:
        base = PIPELINE_SCRIPT.parent / "output" / f"{dataset_name}_profile"

    bundle_dir = base / f"{dataset_name} ANIMATION"
    if not bundle_dir.is_dir():
        # Fallback: search for animation_meshes.npz under base
        for candidate in base.rglob("animation_meshes.npz"):
            bundle_dir = candidate.parent
            break
        else:
            raise RuntimeError(
                f"Pipeline completed but bundle not found under {base}. "
                f"stdout: {' '.join(output_lines)[:500]}"
            )

    _emit_progress(progress_cb, 100, f"Pipeline complete: {bundle_dir.name}")
    return bundle_dir
