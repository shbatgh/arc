##Cell-matching algorithm for a single timepoint. Outputs cells, which is a list of cell objects. Works for a specified color.

import math

cell_count = 0
cells = []


class Cell:         #Cell class
    def __init__(self, id, starting_slice, initial_outline, c_color):
        self.id = id
        self.color = c_color

        self.starting_slice = starting_slice
        self.top_slice = starting_slice

        self.centers = [find_center(initial_outline)]
        self.outlines = [initial_outline]
        

        global cell_count, cells
        cell_count +=1
        cells.append(self)
    
    def add_outline(self, new_outline):
        self.top_slice +=1
        self.outlines.append(new_outline)
        self.centers.append(find_center(new_outline))







def find_center(point_list):                 #Finds the center of a outline
    length = len(point_list)
    if length == 0:
        return(None)
    
    x_sum, y_sum = 0, 0
    for [x, y] in point_list:
        x_sum +=x
        y_sum +=y
    return((x_sum/length, y_sum/length))

def approx_width(point_list, x_or_y):
    comp = 0
    if x_or_y =="y":
        comp = 1
    res_min = point_list[0][comp]
    res_max = point_list[1][comp]
    for p in point_list:
        val = p[comp]
        if val < res_min:
            res_min = val
        elif val > res_max:
            res_max = val
    return(res_max - res_min)
    

def find_segs(slice_dict, color):            #Finds all segmentations of a certain color on a slice
    if color not in slice_dict.keys():
        return([])
    return(slice_dict[color].copy())

def matchedSortFn(e):
    return(e[1])

def match_cells(cur_cells, prev_cells):      #Matches up all combinations between cells in the slice above and below. Sorts by the distance between centers.

    matched_list = []                        #Each element is [pair_dict, distance]
    for cur_c in cur_cells:
        cur_center = find_center(cur_c)
        if cur_center is None:
            continue
        for prev_c in prev_cells:
            prev_center = find_center(prev_c)
            if prev_center is None:
                continue
            pair = {
                "cur_center": cur_center,
                "prev_center": prev_center,
                "cur_outline": cur_c,
                "prev_outline": prev_c,
            }
            matched_list.append([pair, math.dist(cur_center, prev_center)])
    matched_list.sort(key = matchedSortFn)
    return(matched_list)


def remove_pairs(matched_list, center):                    #Removes all elements in a list that have an outline with the following center
    new_matched_list = []
    for pair in matched_list:
        info = pair[0]
        if center not in (info["cur_center"], info["prev_center"]):
            new_matched_list.append(pair)
    return(new_matched_list)

def find_max_error(point_list1, point_list2):              #Finds the maximum error a cell can change position in different slices to still be considered the same cell.
    approx_r1 = max([approx_width(point_list1, "x"), approx_width(point_list1, "y")])         #Approximates the radius to do this.
    approx_r2 = max([approx_width(point_list2, "x"), approx_width(point_list2, "y")])
    result = max(approx_r1, approx_r2) * 0.5      #Change this multiplier. Smaller for tighter ranges to classify two segs as the same cell.
    return(result)

def appears_before(matched_list, center, loc):
    found = False
    for e in matched_list[:loc]:
        info = e[0]
        if center in (info["cur_center"], info["prev_center"]):
            found = True
            break
    return(found)

def tag_centers(matched_list, center, starting_idx):
    tagged = []
    for cur_idx in range(starting_idx, len(matched_list)):
        pair = matched_list[cur_idx]
        info = pair[0]
        if center == info["cur_center"]:
            center_pos_tag = info["prev_center"]
        elif center == info["prev_center"]:
            center_pos_tag = info["cur_center"]
        else:
            continue
        if not appears_before(matched_list=matched_list, center=center_pos_tag, loc=cur_idx):
            tagged.append(center_pos_tag)
    return(tagged)


def filter_pairs(matched_list):
    filtered = []
    idx = 0
    while idx < len(matched_list):
        filtered.append(matched_list[idx])

        info = matched_list[idx][0]
        paired_centers = [info["cur_center"], info["prev_center"]]
        tagged = [paired_centers[0], paired_centers[1]]
        tagged += tag_centers(matched_list=matched_list, center=paired_centers[0], starting_idx=idx+1)
        tagged += tag_centers(matched_list=matched_list, center=paired_centers[1], starting_idx=idx+1)

        for center in tagged:
            matched_list = remove_pairs(matched_list = matched_list, center=center)
    new_filtered = []
    for pair in filtered:
        info = pair[0]
        max_error = find_max_error(info["cur_outline"], info["prev_outline"])
        if pair[1]<max_error:
            new_filtered.append(pair)
    return(new_filtered)

def identify_cell(center, color):
    for c_obj in cells:
        if (c_obj.color == color) and (center in c_obj.centers):
            return(c_obj)

    print("No Cell Found with center: ", center)
    return(None)


def compute_slice(stack_list, slice_num, color):
    cur_segs = find_segs(slice_dict=stack_list[slice_num], color=color)
    prev_segs = find_segs(slice_dict=stack_list[slice_num-1], color=color)

    if len(cur_segs) == 0:
        return()
    if len(prev_segs) == 0:
        for seg in cur_segs:
            new_cell = Cell(id = "Cell"+str(color)+" "+str(cell_count),
                            starting_slice = slice_num,
                            initial_outline = seg,
                            c_color = color)
        return()
    
    matched_list = match_cells(cur_cells=cur_segs,
                               prev_cells=prev_segs)
    
    filtered_list = filter_pairs(matched_list=matched_list)

    for pair in filtered_list:
        info = pair[0]
        cur_outline = info["cur_outline"]
        prev_center = info["prev_center"]

        cell_obj = identify_cell(prev_center, color)
        if cell_obj is None:
            continue
        cell_obj.add_outline(new_outline=cur_outline)

        cur_segs.remove(cur_outline)
    
    for seg in cur_segs:
        new_cell = Cell(id = "Cell"+str(color)+" "+str(cell_count),
                        starting_slice = slice_num,
                        initial_outline = seg,
                        c_color = color)

def first_slice_cells(slice_dict, color):
    cur_segs = find_segs(slice_dict=slice_dict, color=color)
    for seg in cur_segs:
        new_cell = Cell(id = "Cell"+str(color)+" "+str(cell_count),
                        starting_slice = 0,
                        initial_outline = seg,
                        c_color = color)

def compute_stack(stack_list, color):
    global cells
    cells = []
    first_slice_cells(slice_dict=stack_list[0],
                      color=color)
    for slice_num in range(1, len(stack_list)):
        compute_slice(stack_list=stack_list,
                      slice_num=slice_num,
                      color=color)
    
    return(cells)
