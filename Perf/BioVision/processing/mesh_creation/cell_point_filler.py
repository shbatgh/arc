"""
Cell Point Filler

Orchestrates the conversion of raw Cell2D outlines into dense, splined
3D wireframe loops suitable for mesh generation.

Pipeline:
  1. Create vertical wireframe loops in XZ and YZ planes from the raw outlines
     (new_triple_wireframe).
  2. Find dome caps above/below the cell by estimating Z values at wireframe
     intersections (cap_finder_own_approach).
  3. Densify the wireframe loops with Catmull-Rom spline interpolation
     (catmull_rom_spline_injecter).

Called by pickled_quant_data.get_solid_mesh_objs().
"""

import copy

from . import cap_finder_own_approach, catmull_rom_spline_injecter, new_triple_wireframe

# Physical Z spacing per slice (microns to coordinate units)
Z_PER_SLICE = 3 / 0.198

# Wireframe cutting-plane spacing and tolerance
WF_DIST = Z_PER_SLICE / 5
WF_OFFSET = 1.5


def point_filler(cell, tens, cont, bias, points_per_segment, top_spline=True, spline=True):
    """Generate dense splined wireframe loops for a Cell2D.

    Args:
        cell:               Cell2D object with .outlines and .starting_slice.
        tens:               Kochanek-Bartels spline tension (e.g. -0.75).
        cont:               Kochanek-Bartels spline continuity (e.g. 0).
        bias:               Kochanek-Bartels spline bias (e.g. 0).
        points_per_segment: Number of interpolated points per spline segment.
        top_spline:         Whether to spline the top/bottom cap regions.
        spline:             If False, skip spline interpolation entirely.

    Returns:
        (splined_xz, splined_yz) - two lists of 3D point lists, each
        representing a closed wireframe loop.
    """
    # Step 1: Create vertical wireframe loops by slicing outlines with planes
    wfsx = new_triple_wireframe.triple_wireframe_creation(
        outline_list=copy.deepcopy(cell.outlines),
        x_or_y="x",
        starting_slice=cell.starting_slice,
        wf_dist_arg=WF_DIST,
        wf_offset_arg=WF_OFFSET,
    )
    wfsy = new_triple_wireframe.triple_wireframe_creation(
        outline_list=copy.deepcopy(cell.outlines),
        x_or_y="y",
        starting_slice=cell.starting_slice,
        wf_dist_arg=WF_DIST,
        wf_offset_arg=WF_OFFSET,
    )

    if not spline:
        wfsx = _spline_and_close(wfsx, points_per_segment, spline=False)
        wfsy = _spline_and_close(wfsy, points_per_segment, spline=False)
        return wfsx, wfsy

    # Step 2: Find dome caps (top then bottom)
    _, xz_top_capped, yz_top_capped = cap_finder_own_approach.execute(
        all_XZ_outlines=wfsy,
        all_YZ_outlines=wfsx,
        top_or_bottom="top",
        tension_arg=tens,
        continuity_arg=cont,
        bias_arg=bias,
    )
    _, xz_capped, yz_capped = cap_finder_own_approach.execute(
        all_XZ_outlines=xz_top_capped,
        all_YZ_outlines=yz_top_capped,
        top_or_bottom="bottom",
        tension_arg=tens,
        continuity_arg=cont,
        bias_arg=bias,
    )

    # Step 3: Densify with Catmull-Rom spline interpolation
    splined_xz = _spline_and_close(yz_capped, points_per_segment, top_spline=top_spline)
    splined_yz = _spline_and_close(xz_capped, points_per_segment, top_spline=top_spline)
    return splined_xz, splined_yz


def _spline_and_close(wfs, points_per_segment, top_spline=True, spline=True):
    """Apply spline interpolation to wireframe loops and close them.

    Each loop gets Catmull-Rom points injected between consecutive points,
    then the first 3 points are appended at the end to close the loop
    smoothly for downstream processing.
    """
    result = []
    for wf in wfs:
        if spline:
            splined = catmull_rom_spline_injecter.inject_catmull_rom_points(
                copy.deepcopy(wf),
                points_per_segment=points_per_segment,
                top_spline=top_spline,
            )
        else:
            splined = copy.deepcopy(wf)
        # Close the loop by repeating the first 3 points
        splined.append(splined[0])
        splined.append(splined[1])
        splined.append(splined[2])
        result.append(splined)
    return result
