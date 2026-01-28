"""
Run Cellpose SAM segmentation on all TIF files in the A1 dataset.

A1 Structure:
    A1/
    ├── t1/           (timepoint 1)
    │   ├── 1.tif     (Z-slice 1)
    │   ├── 2.tif     (Z-slice 2)
    │   └── ...       (up to 15.tif)
    ├── t2/           (timepoint 2)
    └── ...           (up to t46)

Outputs:
    - *_seg.npy: Segmentation masks, flows, and styles
    - *_cp_outlines.txt: Cell outlines in x,y format
    - *_cp_masks.png: Visualization of segmentation masks
"""

import os
import glob
import numpy as np
import cv2
from pathlib import Path

from cellpose import models, io
from cellpose.models import CellposeModel


def run_cellpose_sam(
    input_folder: str,
    model_type: str = "cyto3",
    use_gpu: bool = True,
    blur_kernel: tuple = (5, 5),
    diameter: float = None,
    save_outlines: bool = True,
    save_masks_png: bool = True,
):
    """
    Run Cellpose segmentation on all TIF files in the input folder.

    Args:
        input_folder: Path to A1 folder containing timepoint subdirectories
        model_type: Cellpose model type ('cyto3', 'cyto', 'nuclei', or path to custom model)
        use_gpu: Whether to use GPU acceleration
        blur_kernel: Gaussian blur kernel size before segmentation
        diameter: Expected cell diameter (None for auto-detection)
        save_outlines: Save cell outlines to *_cp_outlines.txt
        save_masks_png: Save mask visualization to *_cp_masks.png
    """
    input_folder = Path(input_folder)

    # Initialize Cellpose model
    print(f"Loading Cellpose model: {model_type}")
    model = CellposeModel(gpu=use_gpu, pretrained_model=model_type)

    # Get all timepoint directories
    timepoint_dirs = sorted(
        [d for d in input_folder.iterdir() if d.is_dir() and d.name.startswith('t')],
        key=lambda x: int(x.name[1:]) if x.name[1:].isdigit() else 0
    )

    if not timepoint_dirs:
        print(f"No timepoint directories found in {input_folder}")
        return

    print(f"Found {len(timepoint_dirs)} timepoint directories")

    total_images = 0
    processed_images = 0

    for tp_dir in timepoint_dirs:
        # Get all TIF files in this timepoint
        tif_files = sorted(
            glob.glob(str(tp_dir / "*.tif")),
            key=lambda x: int(Path(x).stem) if Path(x).stem.isdigit() else 0
        )

        if not tif_files:
            print(f"No TIF files in {tp_dir.name}, skipping...")
            continue

        print(f"\nProcessing {tp_dir.name}: {len(tif_files)} images")

        for img_file in tif_files:
            img_path = Path(img_file)
            base_name = img_path.stem
            total_images += 1

            try:
                # Read image
                img = io.imread(img_file)

                # Convert grayscale to RGB if needed
                if img.ndim == 2:
                    img = np.stack([img] * 3, axis=-1)
                elif img.ndim == 3 and img.shape[2] == 1:
                    img = np.concatenate([img] * 3, axis=2)

                # Apply Gaussian blur
                img_blurred = cv2.GaussianBlur(img, blur_kernel, 0)

                # Run segmentation (Cellpose v4.0.1+ API)
                masks, flows, styles = model.eval(
                    img_blurred,
                    diameter=diameter,
                )

                # Save segmentation data
                seg_data = {'masks': masks, 'flows': flows, 'styles': styles}
                seg_file = tp_dir / f"{base_name}_seg.npy"
                np.save(seg_file, seg_data)

                # Save outlines
                if save_outlines:
                    outline_file = tp_dir / f"{base_name}_cp_outlines.txt"
                    save_outlines_to_file(masks, outline_file)

                # Save mask visualization
                if save_masks_png:
                    mask_file = tp_dir / f"{base_name}_cp_masks.png"
                    save_mask_visualization(masks, mask_file)

                processed_images += 1
                print(f"  {base_name}.tif: {masks.max()} cells detected")

            except Exception as e:
                print(f"  Error processing {base_name}.tif: {e}")

    print(f"\nComplete! Processed {processed_images}/{total_images} images")


def save_outlines_to_file(masks: np.ndarray, output_file: Path):
    """Extract cell outlines from masks and save to text file."""
    with open(output_file, 'w') as f:
        labels = np.unique(masks)
        for label in labels:
            if label == 0:  # Skip background
                continue

            # Create binary mask for this cell
            cell_mask = (masks == label).astype(np.uint8) * 255

            # Find contours
            contours, _ = cv2.findContours(
                cell_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            if not contours:
                continue

            # Use the largest contour
            largest_contour = max(contours, key=cv2.contourArea)
            largest_contour = largest_contour.squeeze()

            if largest_contour.ndim == 1:
                largest_contour = np.expand_dims(largest_contour, axis=0)

            # Format as x,y,x,y,...
            coord_pairs = [f"{pt[0]},{pt[1]}" for pt in largest_contour]
            outline_str = ",".join(coord_pairs)
            f.write(outline_str + "\n")


def save_mask_visualization(masks: np.ndarray, output_file: Path):
    """Save mask visualization as PNG."""
    # Normalize masks to 16-bit for better visualization
    if masks.max() > 0:
        mask_vis = (masks.astype(np.float32) / masks.max() * 65535).astype(np.uint16)
    else:
        mask_vis = masks.astype(np.uint16)

    cv2.imwrite(str(output_file), mask_vis)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run Cellpose SAM segmentation on A1 dataset"
    )
    parser.add_argument(
        "input_folder",
        nargs="?",
        default="/home/sam/dev/arc/A1",
        help="Path to A1 folder (default: /home/sam/dev/arc/A1)"
    )
    parser.add_argument(
        "--model", "-m",
        default="cyto3",
        help="Model type: cyto3, cyto, nuclei, or path to custom model"
    )
    parser.add_argument(
        "--no-gpu",
        action="store_true",
        help="Disable GPU acceleration"
    )
    parser.add_argument(
        "--blur",
        type=int,
        default=5,
        help="Gaussian blur kernel size (default: 5)"
    )
    parser.add_argument(
        "--diameter", "-d",
        type=float,
        default=None,
        help="Expected cell diameter (default: auto-detect)"
    )
    parser.add_argument(
        "--no-outlines",
        action="store_true",
        help="Skip saving outline files"
    )
    parser.add_argument(
        "--no-masks",
        action="store_true",
        help="Skip saving mask PNG files"
    )

    args = parser.parse_args()

    run_cellpose_sam(
        input_folder=args.input_folder,
        model_type=args.model,
        use_gpu=not args.no_gpu,
        blur_kernel=(args.blur, args.blur),
        diameter=args.diameter,
        save_outlines=not args.no_outlines,
        save_masks_png=not args.no_masks,
    )
