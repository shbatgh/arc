

"""
Same as mesh_interpolated, just using splined wireframes
"""
import cell_point_filler

import sys
sys.path.append('C:/Users/tajre/OneDrive/Documents/GitHub/BioVision/processing')
import single_stack_cell_matching

import copy
import pickle
import numpy as np


##---Changeable variables for caps
tens = -0.65
cont = 0
bias = 0
points_per_segment = 6

def get_data(path):
    with open(path, "rb") as f:
        # skip header line
        header = f.readline()
        parsed_data = pickle.load(f)

    return parsed_data


def create_wireframes(path, colors, output_file, top_spline = True, spline=True):
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
                splined_xz, splined_yz = cell_point_filler.point_filler(cell, tens, cont, bias, points_per_segment, top_spline = top_spline, spline=spline)
                result[tp].append({color : splined_xz+splined_yz})

    with open(output_file, 'wb') as f:
        f.write(b"WIREFRAME\n")
        pickle.dump(result, f)


create_wireframes(path = "C:/Users/tajre/OneDrive/Desktop/Amy's Animations/TEST v3 Anisha to fix open solids.pkl", #"C:/Users/areil/Desktop/Terra/Programs/Program Outputs/GC Iso 21tps.txt",
                  colors = [(255, 50, 0), (0, 100, 200), (255, 0, 100)],      #(255,0,0), (0,255,0), (0,0,255), (200,200,0), (255,0,255), (200,0,100), (0,255,255), (150,50,50), (0,100,0), (255,200,100)
                  output_file = "C:/Users/tajre/OneDrive/Desktop/Amy's Animations/TEST no_top v3 Anisha open solids MESH.pkl",
                  top_spline = False,
                  spline=True)