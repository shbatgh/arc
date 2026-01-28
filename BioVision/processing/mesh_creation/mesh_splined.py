"""
Same as mesh_interpolated, just using splined wireframes
"""
import cell_point_filler

import sys
sys.path.append('C:/Users/areil/Desktop/BioVision/processing')
import single_stack_cell_matching

import copy
import ast
import numpy as np


##---Changeable variables for caps
tens = -0.5
cont = 0
bias = 0
points_per_segment = 2



def get_data(path):
    with open(path, 'r') as f:   #blender_format_adjusted or blender_format
        d = f.read()

    data = ast.literal_eval(d)
    return(data)



def create_wireframes(path, colors, output_dir, spline=True):
    print("Featching Data...")
    data = get_data(path=path)

    result = {}
    for tp in range(0, len(data.keys())):
        result[tp] = []


    for color in colors:
        print("\n\nCurrent color: ", color)
        for tp in range(0, len(data.keys())):          #0, len(data.keys())
            cells = single_stack_cell_matching.compute_stack(stack_list=data[tp],
                                                             color = color)
            for cell in cells:
                print("\n\nCurrent cell: ", cell.id)
                splined_xz, splined_yz = cell_point_filler.point_filler(cell, tens, cont, bias, points_per_segment, spline=spline)
                result[tp].append({color : splined_xz+splined_yz})

    with open(output_dir + "mesh_wires_splined 3tps.txt", 'w') as f:
        f.write(str(result))



create_wireframes(path = "C:/Users/areil/Desktop/Terra/Programs/Program Outputs/ForTaraPos10 3tps.txt", #"C:/Users/areil/Desktop/Terra/Programs/Program Outputs/GC Iso 21tps.txt",
                  colors = [(255,0,255)],      #(255,0,0), (0,255,0), (0,0,255), (200,200,0), (255,0,255), (200,0,100), (0,255,255), (150,50,50), (0,100,0), (255,200,100)
                  output_dir = "C:/Users/areil/Desktop/Terra/Programs/Program Outputs/",
                  spline=True)