import argparse
import json
import pickle
import re
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    # Allow `python BioVision/pipeline.py` from the repo root.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from BioVision.processing.translators import (
    color_extractor,
    formatting_preparation,
    lexographic_renaming,
    v10manual_segmentation_formatter,
)

PROJECT_ROOT = Path(__file__).resolve().parent
PROCESSING_DIR = PROJECT_ROOT / "processing"
QUANT_SCRIPT = PROCESSING_DIR / "pickled_quant_data.py"
DEFAULT_SEGMENT_SCRIPT = PROJECT_ROOT.parent.parent / "arc-c++" / "tools" / "segment_images_to_animation.py"


def resolve_path(path_text):
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


def ensure_parent(path_obj):
    path_obj.parent.mkdir(parents=True, exist_ok=True)


def parse_rgb(text_value):
    parts = [p.strip() for p in text_value.split(",")]
    if len(parts) != 3:
        raise ValueError(f"Expected R,G,B format but got: {text_value}")
    return tuple(int(p) for p in parts)


def parse_optional_image_dims(text_value):
    if text_value is None:
        return None
    parts = [p.strip() for p in text_value.split(",")]
    if len(parts) != 2:
        raise ValueError(f"Expected WIDTH,HEIGHT format but got: {text_value}")
    return [int(parts[0]), int(parts[1])]


def sorted_dirs(path):
    dirs = [p for p in path.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.name)
    return dirs


def run_command(cmd, python_executable=None):
    if python_executable is not None and cmd and cmd[0] == "python":
        cmd = [python_executable] + cmd[1:]
    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT)


def strip_profile_args(argv):
    filtered = []
    idx = 0
    while idx < len(argv):
        arg = argv[idx]

        if arg == "--_profiled-run":
            idx += 1
            continue

        if arg == "--profile-flamegraph":
            idx += 2
            continue
        if arg.startswith("--profile-flamegraph="):
            idx += 1
            continue

        if arg == "--profile-rate":
            idx += 2
            continue
        if arg.startswith("--profile-rate="):
            idx += 1
            continue

        if arg in ("--profile-subprocesses", "--no-profile-subprocesses"):
            idx += 1
            continue

        filtered.append(arg)
        idx += 1

    return filtered


def run_with_pyspy_flamegraph(args):
    pyspy_exe = shutil.which("py-spy")
    if pyspy_exe is None:
        raise RuntimeError(
            "py-spy is required for --profile-flamegraph but was not found on PATH. "
            "Install it and rerun."
        )

    flamegraph_output = resolve_path(args.profile_flamegraph)
    ensure_parent(flamegraph_output)

    child_args = strip_profile_args(sys.argv[1:])
    child_args.append("--_profiled-run")

    cmd = [
        pyspy_exe,
        "record",
        "--format",
        "flamegraph",
        "--output",
        str(flamegraph_output),
        "--rate",
        str(args.profile_rate),
    ]
    if args.profile_subprocesses:
        cmd.append("--subprocesses")

    cmd.extend([
        "--",
        args.python,
        str(Path(__file__).resolve()),
    ])
    cmd.extend(child_args)

    print("Running pipeline under py-spy")
    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT)
    print(f"Flamegraph written: {flamegraph_output}")


def run_lexographic_renaming(target_dir):
    lexographic_renaming.rename(path=str(target_dir), file_or_folder="folder", name_length="auto")
    for cur_tp in sorted_dirs(target_dir):
        lexographic_renaming.rename(path=str(cur_tp), file_or_folder="file", name_length="auto")


def build_zero_ref_lists(path_to_timepoints):
    n_timepoints = len(sorted_dirs(path_to_timepoints))
    ref_list = [[0, 0] for _ in range(n_timepoints)]
    rot_list = [[1, 0] for _ in range(n_timepoints)]
    return ref_list, rot_list


def build_ref_lists(path_to_timepoints, image_dims, args):
    ref_list, rot_list = build_zero_ref_lists(path_to_timepoints)

    if args.find_reference_points:
        ref_color = parse_rgb(args.reference_point_color)
        ref_list = formatting_preparation.find_ref_points_multiple_slices(
            path_to_timepoints=str(path_to_timepoints),
            reference_point_color=ref_color,
            image_dimensions=image_dims,
        )

    if args.find_rotation_points:
        rot_color = parse_rgb(args.rotation_point_color)
        rot_list = formatting_preparation.find_ref_points_multiple_slices(
            path_to_timepoints=str(path_to_timepoints),
            reference_point_color=rot_color,
            image_dimensions=image_dims,
        )

    return ref_list, rot_list


def outlines_to_wireframe_pickle(args, wireframe_pkl):
    outlines_dir = resolve_path(args.outlines_dir)
    if not outlines_dir.exists():
        raise FileNotFoundError(f"Outlines directory not found: {outlines_dir}")

    if not args.skip_lexographic_renaming:
        print("Running lexographic renaming on outlines directory")
        run_lexographic_renaming(outlines_dir)

    image_dims = parse_optional_image_dims(args.image_dims)
    if image_dims is None:
        image_dims = formatting_preparation.find_image_dimensions(path_to_timepoints=str(outlines_dir))

    ref_list, rot_list = build_ref_lists(outlines_dir, image_dims, args)

    frame_dict, manual_time_taken = v10manual_segmentation_formatter.prepare_manual_data(
        path_to_timepoints=str(outlines_dir),
        reference_point_list=ref_list,
        rotation_point_list=rot_list,
        image_dimensions=image_dims,
        sort_large_groups=not args.no_sort_large_groups,
        rotate=args.rotate,
    )
    print(f"Manual data formatting time taken: {manual_time_taken}")

    ensure_parent(wireframe_pkl)
    with open(wireframe_pkl, "wb") as f:
        f.write(b"WIREFRAME\n")
        pickle.dump(frame_dict, f)
    print(f"Wireframe pickle written: {wireframe_pkl}")


def default_segmentation_json_path(images_dir, segmentation_output_dir, model_name):
    model_safe = model_name.replace("-", "_")
    return segmentation_output_dir / f"{images_dir.name}_{model_safe}_raw.json"


def run_image_segmentation(args):
    images_dir = resolve_path(args.images_dir)
    if not images_dir.exists():
        raise FileNotFoundError(f"Images directory not found: {images_dir}")

    segmentation_output_dir = resolve_path(args.segmentation_output_dir)
    segmentation_output_dir.mkdir(parents=True, exist_ok=True)
    segment_script = resolve_path(args.segmentation_script)
    if not segment_script.exists():
        raise FileNotFoundError(f"Segmentation script not found: {segment_script}")

    cmd = [
        "python",
        str(segment_script),
        "--input",
        str(images_dir),
        "--output",
        str(segmentation_output_dir),
        "--model",
        args.segmentation_model,
        "--device",
        args.segmentation_device,
        "--diameter",
        str(args.segmentation_diameter),
        "--min-area",
        str(args.segmentation_min_area),
        "--z-spacing",
        str(args.segmentation_z_spacing),
    ]
    if args.segmentation_animation_json:
        cmd.extend(["--animation-json", str(resolve_path(args.segmentation_animation_json))])

    print("Running segmentation")
    run_command(cmd, python_executable=args.python)

    if args.segmentation_animation_json:
        return resolve_path(args.segmentation_animation_json)
    return default_segmentation_json_path(
        images_dir=images_dir,
        segmentation_output_dir=segmentation_output_dir,
        model_name=args.segmentation_model,
    )


def parse_color_from_arc_key(raw_key):
    match = re.search(r"\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]", raw_key)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def parse_int_token(text):
    token = re.search(r"(\d+)", str(text))
    if token is None:
        return 10**9
    return int(token.group(1))


def images_to_wireframe_pickle(args, wireframe_pkl):
    animation_json = run_image_segmentation(args)
    if not animation_json.exists():
        raise FileNotFoundError(f"Segmentation animation JSON not found: {animation_json}")

    with open(animation_json, "r", encoding="utf-8") as f:
        parsed = json.load(f)
    payload = parsed.get("payload", {})
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError(f"Animation JSON payload is missing/empty: {animation_json}")

    frame_dict = {}
    tp_keys = sorted(payload.keys(), key=parse_int_token)
    for output_tp_idx, tp_key in enumerate(tp_keys):
        stack_list = []
        for slice_dict in payload[tp_key]:
            new_slice_dict = {}
            for raw_color, groups in slice_dict.items():
                color = parse_color_from_arc_key(raw_color)
                if color is None:
                    continue
                converted_groups = []
                for group in groups:
                    converted = [[float(point[0]), float(point[1])] for point in group if len(point) >= 2]
                    if len(converted) >= 3:
                        converted_groups.append(converted)
                if converted_groups:
                    if color in new_slice_dict:
                        new_slice_dict[color] += converted_groups
                    else:
                        new_slice_dict[color] = converted_groups
            stack_list.append(new_slice_dict)
        frame_dict[output_tp_idx] = stack_list

    if len(frame_dict) == 0:
        raise RuntimeError("No wireframe frames were generated from the segmentation payload.")

    ensure_parent(wireframe_pkl)
    with open(wireframe_pkl, "wb") as f:
        f.write(b"WIREFRAME\n")
        pickle.dump(frame_dict, f)
    print(f"Wireframe pickle written: {wireframe_pkl}")


def run_quantification(args, wireframe_pkl):
    tracers_output = resolve_path(args.tracers_output) if args.tracers_output else wireframe_pkl.with_name(
        f"{wireframe_pkl.stem} TRACERS.pkl"
    )
    quant_output = resolve_path(args.quant_output) if args.quant_output else wireframe_pkl.with_name(
        f"{wireframe_pkl.stem} QUANT DATA.csv"
    )
    meshes_output = resolve_path(args.meshes_output) if args.meshes_output else wireframe_pkl.with_name(
        f"{wireframe_pkl.stem} SOLIDS.pkl"
    )
    matched_cells_path = resolve_path(args.matched_cells_path) if args.matched_cells_path else wireframe_pkl.with_name(
        "working_matched_cells.pkl"
    )
    tp_path = resolve_path(args.tp_path) if args.tp_path else wireframe_pkl.with_name(
        "working_matched_cells_tp_num.pkl"
    )

    for output_path in [tracers_output, quant_output, meshes_output, matched_cells_path, tp_path]:
        ensure_parent(output_path)

    print("Extracting colors from wireframe pickle")
    _, parsed_data = color_extractor.get_data(file_path=str(wireframe_pkl))
    extracted_colors = color_extractor.extract(dict_data=parsed_data, skip_slice=args.skip_slice)
    print(f"Extracted {len(extracted_colors)} colors")
    if not extracted_colors:
        raise RuntimeError("No colors were extracted from the wireframe pickle. Aborting quantification step.")

    quant_cmd = [
        "python",
        str(QUANT_SCRIPT),
        "--input-pkl",
        str(wireframe_pkl),
        "--colors",
        repr(extracted_colors),
        "--matched-cells-path",
        str(matched_cells_path),
        "--tp-path",
        str(tp_path),
        "--tracers-output",
        str(tracers_output),
        "--quant-output",
        str(quant_output),
        "--meshes-output",
        str(meshes_output),
    ]
    if args.skip_match_cells:
        quant_cmd.append("--skip-match-cells")

    print("Running quantification")
    run_command(quant_cmd, python_executable=args.python)
    print("Quantification complete")
    print(f"Tracers: {tracers_output}")
    print(f"Quant CSV: {quant_output}")
    print(f"Meshes: {meshes_output}")


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Pipeline for generating wireframe pickle data and optional quant outputs.\n"
            "Modes:\n"
            "- existing: use an existing wireframe .pkl\n"
            "- outlines: generate wireframe .pkl from outline images\n"
            "- images: segment images then generate wireframe .pkl from ARC RAW json"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["existing", "outlines", "images"],
        default="existing",
        help="Pipeline input mode.",
    )
    parser.add_argument(
        "--wireframe-pkl",
        default="./output/wireframe.pkl",
        help="Output wireframe .pkl path (or existing input path in existing mode).",
    )
    parser.add_argument(
        "--run-quant",
        action="store_true",
        help="After wireframe generation/load, run pickled_quant_data.py.",
    )
    parser.add_argument(
        "--profile-flamegraph",
        nargs="?",
        const="./output/pipeline_flamegraph.svg",
        default=None,
        help="Run the pipeline under py-spy and write a flamegraph SVG (default path if omitted).",
    )
    parser.add_argument(
        "--profile-rate",
        type=int,
        default=100,
        help="Sampling rate for py-spy flamegraph profiling.",
    )
    parser.add_argument(
        "--profile-subprocesses",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include Python subprocesses (segmentation/quant scripts) in py-spy profiling when supported.",
    )
    parser.add_argument(
        "--_profiled-run",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    # Existing quant stage options
    parser.add_argument("--tracers-output", default=None, help="Output path for tracers .pkl.")
    parser.add_argument("--quant-output", default=None, help="Output path for quant CSV.")
    parser.add_argument("--meshes-output", default=None, help="Output path for meshes .pkl.")
    parser.add_argument("--matched-cells-path", default=None, help="Intermediate matched cells .pkl path.")
    parser.add_argument("--tp-path", default=None, help="Intermediate timepoint-count .pkl path.")
    parser.add_argument("--skip-slice", type=int, default=0, help="Color extractor skip_slice argument.")
    parser.add_argument("--skip-match-cells", action="store_true", help="Reuse existing matched cell files.")

    # Outlines mode options
    parser.add_argument("--outlines-dir", default=None, help="Root directory containing t1/t2/... outline image folders.")
    parser.add_argument("--skip-lexographic-renaming", action="store_true", help="Skip renaming pass in outlines mode.")
    parser.add_argument("--image-dims", default=None, help="Image dimensions as WIDTH,HEIGHT.")
    parser.add_argument("--find-reference-points", action="store_true", help="Detect reference points from colored markers.")
    parser.add_argument("--find-rotation-points", action="store_true", help="Detect rotation points from colored markers.")
    parser.add_argument("--reference-point-color", default="255,255,0", help="Reference point marker color as R,G,B.")
    parser.add_argument("--rotation-point-color", default="0,255,0", help="Rotation point marker color as R,G,B.")
    parser.add_argument("--rotate", action="store_true", help="Enable rotation in outline->pickle conversion.")
    parser.add_argument("--no-sort-large-groups", action="store_true", help="Disable large-group sorting in formatter.")

    # Images mode options
    parser.add_argument("--images-dir", default=None, help="Root directory of source images for segmentation.")
    parser.add_argument("--segmentation-script", default=str(DEFAULT_SEGMENT_SCRIPT), help="Path to segment_images_to_animation.py.")
    parser.add_argument("--segmentation-output-dir", default="./output/segmentation", help="Output root for segmentation artifacts.")
    parser.add_argument("--segmentation-model", choices=["cellpose", "cellpose-sam", "cellsam"], default="cellpose")
    parser.add_argument("--segmentation-device", choices=["auto", "cpu", "gpu"], default="auto")
    parser.add_argument("--segmentation-diameter", type=float, default=0.0)
    parser.add_argument("--segmentation-min-area", type=int, default=25)
    parser.add_argument("--segmentation-z-spacing", type=float, default=(3.0 / 0.198) * 0.5)
    parser.add_argument("--segmentation-animation-json", default=None, help="Optional explicit path for segmentation RAW JSON.")

    parser.add_argument("--python", default=sys.executable, help="Python executable used for child scripts.")
    return parser


def main():
    args = build_arg_parser().parse_args()
    if args.profile_flamegraph and not args._profiled_run:
        run_with_pyspy_flamegraph(args)
        return

    wireframe_pkl = resolve_path(args.wireframe_pkl)

    if args.mode == "existing":
        if not wireframe_pkl.exists():
            raise FileNotFoundError(f"Wireframe .pkl not found: {wireframe_pkl}")
    elif args.mode == "outlines":
        if not args.outlines_dir:
            raise ValueError("--outlines-dir is required in --mode outlines")
        outlines_to_wireframe_pickle(args, wireframe_pkl)
    elif args.mode == "images":
        if not args.images_dir:
            raise ValueError("--images-dir is required in --mode images")
        images_to_wireframe_pickle(args, wireframe_pkl)

    print(f"Wireframe ready: {wireframe_pkl}")
    if args.run_quant:
        run_quantification(args, wireframe_pkl)
    else:
        print("Skipping quantification. Use --run-quant to enable it.")


if __name__ == "__main__":
    main()
