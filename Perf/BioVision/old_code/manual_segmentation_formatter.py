"""
This code converts the self segmented images to the output dictionary given:
    - Reference points
    - Path to timepoints
    - Colors on draw image (recursive and brute-force)
    - Number of timepoints and slices

Assuming:
    - Timepoints are labeled    t1, t2, ...,    tn
    - Images are labeled        1,  2,  ...,    n


Notes:
Maybe check num_slices business

Have a clause that makes sure that the points checked in get_surrounding_colored_points isn't outside the boundary of the image


Iterate through folders instead of making the names before hand

[x[0] for x in os.walk('C:/Users/areil/Desktop/Terra/Unprocessed Animations/Germarium6_96dpi')]

[ f.path for f in os.scandir('C:/Users/areil/Desktop/Terra/Unprocessed Animations/Germarium6_96dpi') if f.is_dir() ]
[ f.path for f in os.scandir('C:/Users/areil/Desktop/Terra/Unprocessed Animations/Germarium6_96dpi/t01') if f.is_file() ]
"""
import time
from PIL import Image
import sys
import os

import large_group_sorter

sys.setrecursionlimit(1500)


def get_surrounding_colored_points(pix, point_coords, color):                       #returns dictionary: {[*x,y*]: (*color*), [*x,y*]: (*color*), [*x,y*]: (*color*)}
    coords1 = [point_coords[0] - 1, point_coords[1] - 1]
    coords2 = [point_coords[0] - 1, point_coords[1]]
    coords3 = [point_coords[0] - 1, point_coords[1] + 1]

    coords4 = [point_coords[0], point_coords[1] - 1]
    coords5 = [point_coords[0], point_coords[1] + 1]

    coords6 = [point_coords[0] + 1, point_coords[1] - 1]
    coords7 = [point_coords[0] + 1, point_coords[1]]
    coords8 = [point_coords[0] + 1, point_coords[1] + 1]

    

    coords_list = [coords1, coords2, coords3, coords4, coords5, coords6, coords7, coords8]
    surrounding_points = []

    for coord in coords_list:
        cur_x, cur_y = coord[0], coord[1]
        coord_color = pix[cur_x, cur_y][:3]
        if coord_color == color:
            surrounding_points.append(coord)
    return(surrounding_points)


def recursively_add_points(pix, point_list, point_coords, color, recursion_num, fin_p_list, reference_point, checked_points):
    if point_coords in point_list:
        return None
    point_list.append(point_coords)
    fin_p_list.append([point_coords[0]-reference_point[0], point_coords[1]-reference_point[1]])
    checked_points.append(point_coords)
    for surround_coords in get_surrounding_colored_points(pix, point_coords, color).copy():
        recursively_add_points(pix=pix,
                               point_list=point_list,
                               point_coords=surround_coords,
                               color=color,
                               recursion_num=recursion_num+1,
                               fin_p_list=fin_p_list,
                               reference_point=reference_point,
                               checked_points=checked_points)
    if recursion_num == 0:
        return(fin_p_list)


def group_cell_segmentations(pix, color, reference_point, checked_points):
    color_groups = []
    for x in range(width):
        for y in range(height):
            if (pix[x,y][:3] == color) and ([x,y] not in checked_points):
                cur_group = recursively_add_points(pix=pix,
                                                   point_list=[],
                                                   point_coords=[x,y],
                                                   color=color,
                                                   recursion_num=0,
                                                   fin_p_list=[],
                                                   reference_point=reference_point,
                                                   checked_points=checked_points)
                color_groups.append(cur_group)
    return(color_groups)


def group_large(pix, color, reference_point):         #Puts all pixels of a single color in a group, regards all pixels of that color as the same structure/cell
    group = []
    for x in range(width):
        for y in range(height):
            if pix[x,y][:3] == color:
                group.append([x-reference_point[0],y-reference_point[1]])
    if sort:
        group = large_group_sorter.sort_group(group)
    return(group)


def format_slice(slice_path, reference_point):
    slice_dict = {}

    checked_points = []
    cur_img = Image.open(slice_path)
    pix = cur_img.load()


    for color in r_colors:
        slice_dict[color] = group_cell_segmentations(pix, color, reference_point, checked_points)
    for color in bf_colors:
        slice_dict[color] = [group_large(pix, color, reference_point)]
    return(slice_dict)

#Sample imgs: 'C:/Users/areil/Desktop/Germarium_Visualization/Images/Sample_Stacks/3-01.png'


def format_stack(timepoint, reference_point):                #timepoint is the path to the stack
    cur_path = timepoint_folders[timepoint]
    print("Formatting stack " + os.path.basename(os.path.normpath(cur_path)))       #takes last parts
    slice_images = [ f.path for f in os.scandir(cur_path) if f.is_file() ]
    
    n_slices = len(slice_images)                                        #Might raise an error

    stack_list=[]
    for slice_num in range(n_slices):          #slices are numbered 1 through n
        cur_slice = format_slice(slice_path=slice_images[slice_num],
                                 reference_point=reference_point)
        stack_list.append(cur_slice)
    return(stack_list)
        



def prepare_manual_data(path_to_timepoints, recursive_colors, brute_force_colors, reference_point_list, image_dimensions, sort_large_groups):
    start_manual_time = time.time()
    print("Preparing Manual Data")

    global r_colors, bf_colors, sort
    r_colors, bf_colors, sort = recursive_colors, brute_force_colors, sort_large_groups
    global width, height
    width, height = image_dimensions[0], image_dimensions[1]


    global timepoint_folders
    timepoint_folders = [f.path for f in os.scandir(path_to_timepoints) if f.is_dir()]
    n_timepoints = len(timepoint_folders)
    

    frame_dict = {}
    for tp_num in range(n_timepoints):
        cur_refp=reference_point_list[tp_num]       #Is [0,0] if no ref list was inputted

        cur_stack = format_stack(timepoint=tp_num,              
                                 reference_point=cur_refp)        #add to dict which houses stacks (frames)
        frame_dict[tp_num] = cur_stack

    manual_time_taken = time.time()-start_manual_time
    return(frame_dict, manual_time_taken)