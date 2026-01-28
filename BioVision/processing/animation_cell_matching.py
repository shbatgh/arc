##Input is a list of "cells" objects. Each cells object is a list of cell objects that are in a single stack.

"""
Approach:

Copy same stratey as single_stack_cell_matching, just in one higher dimension.

Need new class, cell3D, which has different atributes:
- id, color remain the same
- starting_slice --> starting_tp
- top_slice --> final_tp (not used in other code anyway)
- centers --> centers3D
- outlines --> cell_objs
- Add cell3D_count and cells3D list maybe?? (previously cell_count and cells)
- function to add cell_obj to cells_list (previously add_outline)


1. create initial cell3D objs in first tp

2. Repeat this process iteratively, comparing cur tp to the previous one
    a. 

Fuck this shit bruh im not figuring out how i did it b4, Im just gonna copy and paste my old code and bump it up one dimension thats my approach.


"""

##Cell-matching algorithm for a single timepoint. Outputs cells, which is a list of cell objects. Works for a specified color.

import math
import copy

cell3D_count = 0
cells3D = []
dist_travel_multiplier = 6    #Change this multiplier. Smaller for tighter ranges to classify two cell objs as the same cell.
#Gives a limit to how far a cell can move b4 being considered a new cell. It is multiplied by the approximated width of the cell
#A multiplier of 3 would mean that the cell can travel 3 times its width btwn 2 tps

#----Class below is fixed
class Cell3D:         #Cell3D class
    def __init__(self, id, starting_tp, initial_cell_obj, c_color):
        self.id = id
        self.color = c_color

        self.starting_tp = starting_tp
        self.final_tp = starting_tp

        self.centers3D = [find_3D_center(initial_cell_obj)]
        self.cells_list = [initial_cell_obj]
        

        global cell3D_count, cells3D
        cell3D_count +=1
        cells3D.append(self)
    
    def add_cell(self, new_cell_obj):
        self.final_tp +=1
        self.cells_list.append(new_cell_obj)
        self.centers3D.append(find_3D_center(new_cell_obj))




#----Function below is fixed
def find_3D_center(cell_obj): #Finds the center of a 3D cell. averages all the x and y points in all outlines, then finds the middle slice for the z
    length = 0
    x_sum, y_sum = 0, 0

    for point_list in cell_obj.outlines:
        length += len(point_list)

        for [x, y] in point_list:
            x_sum +=x
            y_sum +=y
    
    z = (cell_obj.top_slice + cell_obj.starting_slice) * 0.5 * (3/0.198) * 0.5      #Finds middle slice. Later, maybe rework with the math that incorporates top and bottom outlines' radii

    return((x_sum/length, y_sum/length, z))



#----Function below is fixed
def approx_width(cell_obj, axis): #FIX. ALSO FIGURE OUT WHAT THE POINT IS
    if axis =="x":
        comp = 0
    elif axis == "y":
        comp = 1
    else: #axis must be z
        return(len(cell_obj.outlines) * (3/0.198))
    
    res_min = cell_obj.outlines[0][0][comp]
    res_max = cell_obj.outlines[0][1][comp]

    for point_list in cell_obj.outlines:
        for p in point_list:
            val = p[comp]
            if val < res_min:
                res_min = val
            elif val > res_max:
                res_max = val
        return(res_max - res_min)



#----Function below did not need changing
def matchedSortFn(e):
    return(e[1])



#----Function below is fixed
def match_cells(cur_cells, prev_cells):      #Matches up all combinations between cells in adjacent tps. Sorts by the distance between centers.
    
    matched_list = []                        #Each element is 2 paired cells. Each element has the format: [{center1: cell1, center2: cell2}, distance]
    for cur_c in cur_cells:
        cur_center = find_3D_center(cur_c)
        for prev_c in prev_cells:
            prev_center = find_3D_center(prev_c)
            matched_list.append([{cur_center: cur_c, prev_center: prev_c}, math.dist(cur_center, prev_center)])
    matched_list.sort(key = matchedSortFn)
    return(matched_list)



#----Function below did not need changing
def remove_pairs(matched_list, center):                    #Removes all elements in a list that have an outline with the following center
    new_matched_list = []
    for pair in matched_list:
        if (center not in pair[0].keys()):                 #Creates new list, only adds elements that do not have the center.
            new_matched_list.append(pair)
    return(new_matched_list)



#----Function below is fixed
def find_max_error(cell_obj1, cell_obj2):              #Finds the maximum error a cell can change position in different slices to still be considered the same cell.
    approx_r1 = (approx_width(cell_obj1, "x") + approx_width(cell_obj1, "y") + approx_width(cell_obj1, "z"))/3         #Approximates the radius to do this.
    approx_r2 = (approx_width(cell_obj2, "x") + approx_width(cell_obj2, "y") + approx_width(cell_obj2, "z"))/3
    result = (approx_r1+approx_r2) * 0.5 * dist_travel_multiplier      #Change this multiplier. Smaller for tighter ranges to classify two cell objs as the same cell.
    return(result)
#Gives a limit to how far a cell can move btwn timepoints



#----Function below did not need changing
def appears_before(matched_list, center, loc):
    found = False
    for e in matched_list[:loc]:
        if center in e[0].keys():
            found = True
            break
    return(found)



#----Function below did not need changing
def tag_centers(matched_list, center, starting_idx):
    tagged = []
    for cur_idx in range(starting_idx, len(matched_list)):
        pair = matched_list[cur_idx]
        c_centers = list(pair[0].keys()).copy()
        if center in c_centers:
            c_centers.remove(center)
            center_pos_tag = c_centers[0]
            if not appears_before(matched_list=matched_list, center=center_pos_tag, loc=cur_idx):
                tagged.append(center_pos_tag)
    return(tagged)



#----Function below is fixed
def filter_pairs(matched_list):
    filtered = []
    idx = 0
    while idx < len(matched_list):
        filtered.append(matched_list[idx])

        paired_centers = list(matched_list[idx][0].keys())
        tagged = [paired_centers[0], paired_centers[1]]
        tagged += tag_centers(matched_list=matched_list, center=paired_centers[0], starting_idx=idx+1)
        tagged += tag_centers(matched_list=matched_list, center=paired_centers[1], starting_idx=idx+1)

        for center in tagged:
            matched_list = remove_pairs(matched_list = matched_list, center=center)
    new_filtered = []
    for pair in filtered:
        cell_objs = list(pair[0].values())
        max_error = find_max_error(cell_objs[0], cell_objs[1])
        if pair[1]<max_error:
            new_filtered.append(pair)
    return(new_filtered)



#----Function below is fixed
def identify_cell(center, color):
    for c_obj in cells3D:
        if (c_obj.color == color) and (center in c_obj.centers3D):
            return(c_obj)

    print("No Cell Found with center: ", center)
    return(None)



#----Function below is fixed
def compute_tp(all_raw_cells, tp_num, color):
    cur_cells = [cell for cell in copy.deepcopy(all_raw_cells[tp_num]) if cell.color == color]
    prev_cells = [cell for cell in copy.deepcopy(all_raw_cells[tp_num-1]) if cell.color == color]


    if len(cur_cells) == 0:
        print("No cells on current tp (???? should rarely happen lol)")
        return()
    if len(prev_cells) == 0:
        for cell_obj in cur_cells:
            new_cell3D = Cell3D(id = str(cell3D_count) + "_" + str(color) + "_Cell3D",
                              starting_tp = tp_num,
                              initial_cell_obj = cell_obj,
                              c_color = color)
        return()
    
    matched_list = match_cells(cur_cells=cur_cells,
                               prev_cells=prev_cells)
    
    filtered_list = filter_pairs(matched_list=matched_list)

    for pair in filtered_list:
        cur_cell_obj = list(pair[0].values())[0]
        prev_center = list(pair[0].keys())[1]

        cell_3D_obj = identify_cell(prev_center, color)
        cell_3D_obj.add_cell(new_cell_obj=cur_cell_obj)

        cur_cells.remove(cur_cell_obj)
    
    for cell_obj in cur_cells:
        print("Cell divided or new cell found, timepoint: ", tp_num)
        new_cell3D = Cell3D(id = str(cell3D_count) + "_" + str(color) + "_Cell3D",
                            starting_tp = tp_num,
                            initial_cell_obj = cell_obj,
                            c_color = color)



#----Function below is fixed
def first_timepoint_cells(first_tp_cells, color):
    for cell in first_tp_cells:
        if cell.color == color:
            new_cell3D = Cell3D(id = str(cell3D_count) + "_" + str(color) + "_Cell3D",
                                starting_tp = 0,
                                initial_cell_obj = cell,
                                c_color = color)



#----Function below is fixed
def compute_animation(all_raw_cells, color):
    global cells3D
    cells3D = []
    first_timepoint_cells(first_tp_cells=all_raw_cells[0],
                          color=color)
    for tp in range(1, len(all_raw_cells)):
        compute_tp(all_raw_cells=all_raw_cells,
                   tp_num=tp,
                   color=color)
    
    print("Number of cells:", cell3D_count)
    return(cells3D)



#------Above is the algorithm, below are the functions used to run it

import ast
import single_stack_cell_matching


def get_raw_cell_data(path, color):
    with open(path, 'r') as f:   #blender_format_adjusted or blender_format
        d = f.read()
    data = ast.literal_eval(d)
    f.close()

    all_raw_cells = []

    for tp in range(0, len(data.keys())):
        cur_cell_objs = single_stack_cell_matching.compute_stack(stack_list = copy.deepcopy(data[tp]),
                                                                    color = color)
        all_raw_cells.append(cur_cell_objs)
    
    return(all_raw_cells)


"""
#Below is used when you run this script by itself, not from some other script

all_raw_cells = get_raw_cell_data("C:/Users/areil/Desktop/Terra/Programs/Program Outputs/ForTaraPos10.txt", (255,0,0))
compute_animation(all_raw_cells, (255,0,0))

"""


