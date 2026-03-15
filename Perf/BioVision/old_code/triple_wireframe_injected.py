#import ast
#Triple wireframe, except it uses mesh_injecter

import mesh_injecter
import mesh_filler
wf_height = 3/0.198

"""
def get_data(path):
    with open(path, 'r') as f:   #blender_format_adjusted or blender_format
        data = f.read()

    outline_list = ast.literal_eval(data)
    return(outline_list)
"""

def find_min_and_width(outline_list):
    min_val = outline_list[0][0][comp]
    max_val = outline_list[0][0][comp]
    for slice in outline_list:
        for coord in slice:
            if coord[comp] < min_val:
                min_val = coord[comp]
            elif coord[comp] > max_val:
                max_val = coord[comp]
    return(min_val, max_val-min_val)

def find_num_wfs(width):
    return(round(width/wf_dist) - 1)

def find_planes(min_val, width, num_wfs):
    plane_vals = [(width/2) - (((num_wfs - 1)/2)*wf_dist) + min_val]
    for i in range (num_wfs -1):
        plane_vals.append(plane_vals[-1] + wf_dist)
    return(plane_vals)

def find_dividing_line(outline):        #Finds average of cell for x or y. This is the dividing line between top or bottom
    switched_comp = (comp + 1)%2        #Changes 1 to 0 and 0 to 1
    sum = 0
    for coord in outline:
        sum += coord[switched_comp]
    return(sum/len(outline))

def sortFn(e):
    return(e[comp])

def create_sorted_outlines(outline_list):
    sorted_outlines = outline_list.copy()
    length = len(sorted_outlines)
    for idx in range(length):
        sorted_outlines[idx].sort(key = sortFn)
    
    for idx in range(length-1, -1, -1):     #going  backwards
        cur_outline = sorted_outlines[idx]
        dividing_line = find_dividing_line(cur_outline)
        switched_comp = (comp + 1)%2
        new_list = []
        i = 0
        while i < len(cur_outline):
            e = cur_outline[i]
            if e[switched_comp] > dividing_line:
                new_list.append(e)
                del cur_outline[i]
            else:
                i += 1
        sorted_outlines.append(new_list)
    return(sorted_outlines)


def find_point(p_list, plane_val, min_or_max):
    valids = []
    for point in p_list:
        if abs(plane_val-point[comp]) < wf_offset: #wf_offset is the acceptable error
            valids.append(point)

    if len(valids) ==0:
        return(-1)

    switched_comp = (comp + 1)%2
    extreme = valids[0][switched_comp]
    result = valids[0]

    if min_or_max == "min":
        for point in valids:
            if point[switched_comp] < extreme:
                extreme = point[switched_comp]
                result = point
    else:
        for point in valids:
            if point[switched_comp] > extreme:
                extreme = point[switched_comp]
                result = point
    return(result)


def create_wf_list(sorted_outlines, plane_val, z_start, num_interp):        #Going up then down
    wf_list = []
    num_slices = int(len(sorted_outlines)/2)
    #---Going up
    for idx in range(0, num_slices):
        cur_z = (z_start + idx*wf_height)/2
        point = find_point(p_list=sorted_outlines[idx],
                           plane_val=plane_val,
                           min_or_max="min")
        if point == -1:
            continue
        point.append(cur_z)
        wf_list.append(point)
    
    #---Going down
    for idx in range(num_slices, 2*num_slices):
        cur_z = (z_start + (2*num_slices - idx - 1)*wf_height)/2
        point = find_point(p_list=sorted_outlines[idx],
                           plane_val=plane_val,
                           min_or_max="max")
        if point == -1:
            continue
        point.append(cur_z)
        wf_list.append(point)

    #Maybe put something in between here to make the meshes more complex

    if len(wf_list)<3:  #Making sure wires are at least 3 points
        return(wf_list)   
    
    injected = mesh_injecter.inject_points_curved_arc(outline=wf_list, num_points_between=3, curvature_scale=0.5, exclude_caps=True)
    #interpolated = mesh_filler.smooth_loop_3D(points=wf_list, num_interp=num_interp)

    return(injected)


def triple_wireframe_creation(outline_list, x_or_y, starting_slice, wf_dist_arg, wf_offset_arg, num_interp):
    global wf_dist, wf_offset
    wf_dist = wf_dist_arg
    wf_offset = wf_offset_arg
    global comp
    comp = 0
    if x_or_y == "y":
        comp = 1
    
    min_val, width = find_min_and_width(outline_list)
    num_wfs = find_num_wfs(width)
    #print(min_val, width, num_wfs, "\n")
    plane_vals = find_planes(min_val, width, num_wfs)
    #print(plane_vals, "\n")
    sorted_outlines = create_sorted_outlines(outline_list)
    #print(sorted_outlines, "\n")

    wfs = []
    #print(plane_vals)
    for val in plane_vals:
        wf_list = create_wf_list(sorted_outlines=sorted_outlines,
                                 plane_val=val,
                                 z_start=starting_slice*wf_height,
                                 num_interp=num_interp)
        if len(wf_list)>2:
            wf_list.append(wf_list[0])
            wf_list.append(wf_list[1])
            wf_list.append(wf_list[2])
        wfs.append(wf_list)
    #print(wfs)
    #test_pv = []
    #for i in range(len(plane_vals)):
        #test_pv.append([wfs[1][1][0], plane_vals[i], wfs[1][1][2]])
    return(wfs)




"""
def find_width():
    finds dist from min to max of a cell along an axis

    
def find_num_wfs():
    width, floor divided by wf_dist - 1

    
def find_planes():
    return a list of all the values along a certain axis. Starting val:     (width/2) - (((num_wfs + 1)/2)*wf_dist) + min

def create_sorted_outlines():
    return a list of outline lists, sorted by x or y value

iterate thru each going up and down.

"""