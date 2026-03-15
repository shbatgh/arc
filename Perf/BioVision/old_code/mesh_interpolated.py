"""
Same as mesh_or_recolor, just using interpolated wireframes instead of really spikey ones. Also no recolor.

"""

import triple_wireframe_interpolated

import sys
sys.path.append('C:/Users/areil/Desktop/BioVision/processing')
import single_stack_cell_matching

import copy
import ast


def get_data(path):
    with open(path, 'r') as f:   #blender_format_adjusted or blender_format
        d = f.read()

    data = ast.literal_eval(d)
    return(data)



def create_wireframes(path, colors, output_dir):
    data = get_data(path=path)

    for color in colors:
        print("\n\nCurrent color: ", color)
        result = {} 

        for tp in range(0, len(data.keys())):
            result[tp] = []
            cells = single_stack_cell_matching.compute_stack(stack_list=data[tp],
                                                             color = color)
            for cell in cells:       
                wfsx = triple_wireframe_interpolated.triple_wireframe_creation(outline_list = copy.deepcopy(cell.outlines), x_or_y = "x", starting_slice=cell.starting_slice, wf_dist_arg=(3/0.198)/5, wf_offset_arg=1, num_interp=20)
                wfsy = triple_wireframe_interpolated.triple_wireframe_creation(outline_list = copy.deepcopy(cell.outlines), x_or_y = "y", starting_slice=cell.starting_slice, wf_dist_arg=(3/0.198)/5, wf_offset_arg=1, num_interp=20)
                result[tp].append({color : wfsx+wfsy})
        with open(output_dir + "R" + str(color[0]) + "G" + str(color[1]) + "B" + str(color[2]) +".txt", 'w') as f:
            f.write(str(result))

"""
recolor(path = "C:/Users/areil/Desktop/Terra/Programs/Program Outputs/CROPPED Crawfish stack.txt",
        output_file="C:/Users/areil/Desktop/Terra/Programs/Program Outputs/CROPPED Crawfish stack RECOLORED.txt")
"""
create_wireframes(path = "C:/Users/areil/Desktop/Terra/Programs/Program Outputs/ForTaraPos10.txt", #"C:/Users/areil/Desktop/Terra/Programs/Program Outputs/GC Iso 21tps.txt",
                  colors = [(255,0,0)],      #(255,0,0), (0,255,0), (0,0,255), (200,200,0), (255,0,255), (200,0,100), (0,255,255), (150,50,50), (0,100,0), (255,200,100)
                  output_dir = "C:/Users/areil/Desktop/Terra/Programs/Program Outputs/INTERPOLATED TWF ForTaraPos10/")
