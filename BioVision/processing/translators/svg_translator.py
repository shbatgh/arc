##SVG translator. This code converts a single slice image in SVG format to the structure that BlenderRenderer uses for a slice, which is shown below
"""
Slice:
{(R1, G1, B1): [outline1, outline2, ....], (R2, G2, B2): [outline1, outline2, ....], ....}

Each outline:
[[x1, y1], [x2, y2], [x3, y3], ....]
"""

import xml.etree.ElementTree as ET
from svgpathtools import parse_path

# Converts hex color (e.g. "#FFAA00") to (R, G, B) tuple
def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')  # Remove '#' from start
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))  # Convert pairs of hex to integers

# Parses one SVG file and converts it into your desired "slice" structure
def extract_slice_from_svg(svg_path):
    tree = ET.parse(svg_path)        # Load and parse the SVG XML structure
    root = tree.getroot()            # Get the root <svg> element


    slice_data = {}  # This will be the output slice dictionary
    
    # Loop over all <path> elements in the SVG
    for elem in root.iter('{http://www.w3.org/2000/svg}path'):
        d_attr = elem.attrib.get('d')                # Get the path's "d" attribute (defines its shape)
        stroke = elem.attrib.get('stroke', '#000000')# Get the path's stroke color (default black if missing)
        rgb = hex_to_rgb(stroke)                     # Convert color string to (R, G, B)

        path = parse_path(d_attr)                    # Parse the "d" attribute into a vector path object
        outline = []

        
        length = path.length()
        if length == 0:
            continue

        num_points = max(20, int(length / 2))  # 1 point every 2 units, min 10

        for i in range(num_points):
            pt = path.point(i / (num_points - 1))
            outline.append([pt.real, pt.imag])            # Extract x (real) and y (imaginary) components

        # Ensure the path is looped (first and last point nearly equal)
        if outline[-1] != outline[0]:
            outline.append(outline[0])

        # Add to the dictionary under the correct color
        if rgb not in slice_data:
            slice_data[rgb] = []
        slice_data[rgb].append(outline)  # Append the new outline to the list for that color
        

    return slice_data  # Output is in your required format

if __name__ == "__main__":      #TEST
    slice_data = extract_slice_from_svg("C:/Users/tajre/OneDrive/Desktop/Amy Unprocessed/TestSVG.svg")
    for key, val in slice_data.items():
        print(key, len(val), [len(cell) for cell in val])