##Fills a cell with splining methods:
try:
    from . import new_triple_wireframe
    from . import cap_finder_own_approach
    from . import catmull_rom_spline_injecter
except ImportError:  # Allow running as a script.
    import new_triple_wireframe
    import cap_finder_own_approach
    import catmull_rom_spline_injecter

import copy

def point_filler(cell, tens, cont, bias, points_per_segment, top_spline = True, spline=True):
    wfsx = new_triple_wireframe.triple_wireframe_creation(outline_list = copy.deepcopy(cell.outlines), x_or_y = "x", starting_slice=cell.starting_slice, wf_dist_arg=(3/0.198)/5, wf_offset_arg=1.5)
    wfsy = new_triple_wireframe.triple_wireframe_creation(outline_list = copy.deepcopy(cell.outlines), x_or_y = "y", starting_slice=cell.starting_slice, wf_dist_arg=(3/0.198)/5, wf_offset_arg=1.5)

    if not spline:
        #just circuit
        wfsx = spline_and_circuit(wfs=wfsx, points_per_segment=points_per_segment, spline=False)
        wfsy = spline_and_circuit(wfs=wfsy, points_per_segment=points_per_segment, spline=False)
        return(wfsx, wfsy)
    
    #print("Doing Top Cap")        
    _, XZ_top_capped, YZ_top_capped = cap_finder_own_approach.execute(all_XZ_outlines=wfsy,
                                                                        all_YZ_outlines=wfsx,
                                                                        top_or_bottom="top",
                                                                        tension_arg= tens,
                                                                        continuity_arg= cont,
                                                                        bias_arg= bias)

    #print("Doing Bottom Cap")
    _, XZ_capped, YZ_capped = cap_finder_own_approach.execute(all_XZ_outlines=XZ_top_capped,
                                                                all_YZ_outlines=YZ_top_capped,
                                                                top_or_bottom="bottom",
                                                                tension_arg= tens,
                                                                continuity_arg= cont,
                                                                bias_arg= bias)

    #Convert XZ_capped and YZ_capped to numpy arrays for Catmull-Rom interpolation
    #XZ_capped = [np.array(e) for e in XZ_capped]
    #YZ_capped = [np.array(e) for e in YZ_capped]

    #print("\nCatmull rom injection")
    splined_xz = spline_and_circuit(XZ_capped, points_per_segment=points_per_segment, top_spline=top_spline)
    splined_yz = spline_and_circuit(YZ_capped, points_per_segment=points_per_segment, top_spline=top_spline)
    
    return(splined_xz, splined_yz)


def spline_and_circuit(wfs, points_per_segment, top_spline, spline=True):
    res = []
    for idx in range(len(wfs)):
        if spline:
            splined = catmull_rom_spline_injecter.inject_catmull_rom_points(copy.deepcopy(wfs[idx]), points_per_segment=points_per_segment, top_spline=top_spline)
        else:
            splined = copy.deepcopy(wfs[idx])
        splined.append(splined[0])
        splined.append(splined[1])
        splined.append(splined[2])
        res.append(splined)
    
    return(res)
