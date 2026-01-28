"""
This code uses single_stack_cell_matching, which is the cell matching algorithm applied to a single stack.
Then, with that information (in the form of a list of cell objects named "cells")

"""

import triple_wireframe

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
                wfsx = triple_wireframe.triple_wireframe_creation(outline_list = copy.deepcopy(cell.outlines), x_or_y = "x", starting_slice=cell.starting_slice, wf_dist_arg=(3/0.198)/2.5, wf_offset_arg=1)
                wfsy = triple_wireframe.triple_wireframe_creation(outline_list = copy.deepcopy(cell.outlines), x_or_y = "y", starting_slice=cell.starting_slice, wf_dist_arg=(3/0.198)/2.5, wf_offset_arg=1)
                result[tp].append({color : wfsx+wfsy})
        with open(output_dir + "R" + str(color[0]) + "G" + str(color[1]) + "B" + str(color[2]) +".txt", 'w') as f:
            f.write(str(result))



#This wouldnt be used to create wireframes. It uses cell matching to recolor. All cells should be in (253, 0, 0)
def recolor(path, output_file):
    colors = [(250,0,0), (0,250,0), (0,0,250), (250,250,0), (0,250,250), (250,0,250), (250,250,250), (250,125,0), (250,0,125), (125,250,0), (0,250,125), (125,0,250), (0,125,250)]


    data = get_data(path=path)
    result = {}

    for tp in range(0, len(data.keys())):
        cells = single_stack_cell_matching.compute_stack(stack_list=data[tp],
                                                         color = (253,0,0))
        
        idx = 0
        for cell in cells:
            cell.color = colors[idx%len(colors)]
            print(cell.color)
            idx+=1

        result[tp] = []

        for cur_slice in data[tp]:
            res_slice = {}

            segmentations = cur_slice[(253,0,0)]
            for seg in segmentations:
                for cell in cells:
                    if seg in cell.outlines:    #This means the seg belongs to cell
                        if cell.color in res_slice.keys():
                            res_slice[cell.color].append(seg)
                        else:
                            res_slice[cell.color] = [seg]
            result[tp].append(res_slice)
    with open(output_file, 'w') as f:
        f.write(str(result))


"""
recolor(path = "C:/Users/areil/Desktop/Terra/Programs/Program Outputs/CROPPED Crawfish stack.txt",
        output_file="C:/Users/areil/Desktop/Terra/Programs/Program Outputs/CROPPED Crawfish stack RECOLORED.txt")
"""
create_wireframes(path = "C:/Users/areil/Desktop/Terra/Programs/Program Outputs/ForTaraPos10.txt", #"C:/Users/areil/Desktop/Terra/Programs/Program Outputs/GC Iso 21tps.txt",
                  colors = [(255,0,0)],      #(255,0,0), (0,255,0), (0,0,255), (200,200,0), (255,0,255), (200,0,100), (0,255,255), (150,50,50), (0,100,0), (255,200,100)
                  output_dir = "C:/Users/areil/Desktop/Terra/Programs/Program Outputs/TWF ForTaraPos10 TEST/")
