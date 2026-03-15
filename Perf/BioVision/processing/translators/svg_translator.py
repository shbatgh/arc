"""
SVG Translator

Parses a single SVG slice image and converts it into the wireframe slice
dictionary format used throughout the pipeline:

    {(R, G, B): [outline1, outline2, ...], ...}

where each outline is [[x1, y1], [x2, y2], ...].

Called by formatting_preparation_SVG.py and v10manual_segmentation_formatter_SVG.py.
"""

import xml.etree.ElementTree as ET
from svgpathtools import parse_path


def hex_to_rgb(hex_color):
    """Convert a hex color string (e.g. "#FFAA00") to an (R, G, B) tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def extract_slice_from_svg(svg_path):
    """Parse one SVG file and return a slice dictionary.

    Iterates over all <path> elements, converts each path's "d" attribute
    into a list of [x, y] sample points, and groups them by stroke color.

    Args:
        svg_path: Path to the SVG file.

    Returns:
        Dict mapping (R, G, B) tuples to lists of outlines.
    """
    tree = ET.parse(svg_path)
    root = tree.getroot()
    slice_data = {}

    for elem in root.iter("{http://www.w3.org/2000/svg}path"):
        d_attr = elem.attrib.get("d")
        stroke = elem.attrib.get("stroke", "#000000")
        rgb = hex_to_rgb(stroke)

        path = parse_path(d_attr)
        length = path.length()
        if length == 0:
            continue

        # Sample the path at regular intervals (1 point every 2 units, min 20)
        num_points = max(20, int(length / 2))
        outline = []
        for i in range(num_points):
            pt = path.point(i / (num_points - 1))
            outline.append([pt.real, pt.imag])

        # Close the path if not already closed
        if outline[-1] != outline[0]:
            outline.append(outline[0])

        if rgb not in slice_data:
            slice_data[rgb] = []
        slice_data[rgb].append(outline)

    return slice_data
