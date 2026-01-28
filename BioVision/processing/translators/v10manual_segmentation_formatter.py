"""
NEW MANUAL SEGMENTATION FORMATTER

This code converts the self segmented images to the output dictionary given:
    - Reference points
    - Path to timepoints
    - Colors on draw image (recursive and brute-force)

Assuming:
    - Timepoints are labeled    t1, t2, ...,    tn
    - Images are labeled        1,  2,  ...,    n


Notes:
Maybe check num_slices business

Have a clause that makes sure that the points checked in get_surrounding_colored_points isn't outside the boundary of the image
-

fix gap in wireframe



DID NOT TEST NEW METHOD YET
"""
import time
from PIL import Image
import sys
import os
import math

import adjust_algorithm
import sort_angle_algorithm
import sort_loose_travelling_salesman_algorithm

sparse = True

sys.setrecursionlimit(1500)


def get_surrounding_colored_points(pix, point_coords, color, loose):                       #returns dictionary: {[*x,y*]: (*color*), [*x,y*]: (*color*), [*x,y*]: (*color*)}
    coords1 = [point_coords[0] - 1, point_coords[1] - 1]
    coords2 = [point_coords[0] - 1, point_coords[1]]
    coords3 = [point_coords[0] - 1, point_coords[1] + 1]

    coords4 = [point_coords[0], point_coords[1] - 1]
    coords5 = [point_coords[0], point_coords[1] + 1]

    coords6 = [point_coords[0] + 1, point_coords[1] - 1]
    coords7 = [point_coords[0] + 1, point_coords[1]]
    coords8 = [point_coords[0] + 1, point_coords[1] + 1]

    coords_list = [coords1, coords2, coords3, coords4, coords5, coords6, coords7, coords8]

    if loose:
        ys = [-2, -1, 0, 1, 2]
        #left_side
        for y in ys:
            coords_list.append([point_coords[0] - 2, point_coords[1] + y])
        #right_side
        for y in ys:
            coords_list.append([point_coords[0] + 2, point_coords[1] + y])

        xs = [-1, 0, 1]
        #bottom_side
        for x in xs:
            coords_list.append([point_coords[0] + x, point_coords[1] - 2])
        #top_side
        for x in xs:
            coords_list.append([point_coords[0] + x, point_coords[1] + 2])

    #Check if coords are in image boundaries.
    if not (1<point_coords[0] and point_coords[0]<width-2 and 1<point_coords[1] and point_coords[1]<height-2):
        for coord in coords_list.copy():
            if not (0<=coord[0] and coord[0]<=width-1 and 0<=coord[1] and coord[1]<=height-1):
                coords_list.remove(coord)

    surrounding_points = []

    for coord in coords_list:
        cur_x, cur_y = coord[0], coord[1]
        coord_color = pix[cur_x, cur_y][:3]
        if (coord_color == color):
            surrounding_points.append(coord)
    return(surrounding_points)


def create_outline_lists(pix, starting_point, color): #maybe still need checked_points clause
    final_point_list =[starting_point]
    queued_points = get_surrounding_colored_points(pix = pix,
                                                   point_coords=starting_point,
                                                   color = color,
                                                   loose=True)
    while len(queued_points) >0:
        temporary_list = []
        for q_point in queued_points:
            for pos_new_point in get_surrounding_colored_points(pix=pix, point_coords=q_point, color=color, loose=True):
                if (pos_new_point not in temporary_list) and (pos_new_point not in final_point_list):
                    temporary_list.append(pos_new_point)
        queued_points = temporary_list

        final_point_list += queued_points
    return (final_point_list)


def add_to_dict(dict, color, group):
    if color in dict.keys():
        dict[color].append(group)
    else:
        dict[color] = [group]

#Remember to adjust to reference point
def sorted_group(group, reference_point, rotation_point, color):       #Color is added as an argument in case we want to use different sorting algorithms for different colors

    if color in [(0,0,255), (0,255,255), (255,0,255), (255, 150, 0), (255,0,0), (100, 50, 255)]:     #(0,0,255), (0,255,255), (255,0,255), (0,255,0)
        sorted_group = sort_loose_travelling_salesman_algorithm.sort_group(group)
    else:
        sorted_group = sort_angle_algorithm.sort_group(sort, group)

    adjusted_group = adjust_algorithm.adjust_group(group =sorted_group,
                                                   reference_point = reference_point,
                                                   rotation_point = rotation_point,
                                                   should_rotate = should_rotate)
    
        
    #Takes only some points----
    if sparse:
        fin_coords = []
        step = 1
        if color in [(0,255,0), (255,0,255), (255,0,0)]:
            step = 1       #Sometimes fucks with stuff
        for i in range (0, len(adjusted_group), step):
            fin_coords.append(adjusted_group[i])
        fin_coords.append(fin_coords[0])
        fin_coords.append(fin_coords[1])
        fin_coords.append(fin_coords[2])
        return(fin_coords)

    return(adjusted_group)



def format_slice(slice_path, reference_point, rotation_point):
    #print("New Slice")
    slice_dict = {}

    cur_img = Image.open(slice_path)
    pix = cur_img.load()

    checked_points = []
    for x in range(width):
        for y in range(height):
            color = pix[x,y][:3]
            if (color != (0,0,0) and color != (255, 255, 255)) and ([x,y] not in checked_points):
                #print(color)
                cur_group = create_outline_lists(pix=pix,
                                                 starting_point= [x,y],
                                                 color=color)
                checked_points+=cur_group           #Make sure the above function isn't run on the same outline more than once
                
                add_to_dict(dict=slice_dict,
                            color=color,
                            group=sorted_group(cur_group, reference_point, rotation_point, color))
        
    return(slice_dict)

#Sample imgs: 'C:/Users/areil/Desktop/Germarium_Visualization/Images/Sample_Stacks/3-01.png'


def format_stack(timepoint, reference_point, rotation_point):                #timepoint is the path to the stack
    cur_path = timepoint_folders[timepoint]
    print("\nFormatting stack " + os.path.basename(os.path.normpath(cur_path)))       #takes last parts
    slice_images = [ f.path for f in os.scandir(cur_path) if f.is_file() ]
    
    n_slices = len(slice_images)                                        #Might raise an error

    stack_list=[]
    for slice_num in range(n_slices):          #slices are numbered 1 through n
        cur_slice = format_slice(slice_path=slice_images[slice_num],
                                 reference_point=reference_point,
                                 rotation_point = rotation_point)
        stack_list.append(cur_slice)
    return(stack_list)
        



def prepare_manual_data(path_to_timepoints, reference_point_list, rotation_point_list, image_dimensions, sort_large_groups, rotate):
    global should_rotate
    should_rotate = rotate

    start_manual_time = time.time()
    print("Preparing Manual Data")

    global sort
    sort = sort_large_groups
    global width, height
    width, height = image_dimensions[0], image_dimensions[1]


    global timepoint_folders
    timepoint_folders = [f.path for f in os.scandir(path_to_timepoints) if f.is_dir()]
    n_timepoints = len(timepoint_folders)
    

    frame_dict = {}
    for tp_num in range(n_timepoints):
        cur_refp=reference_point_list[tp_num]       #Is [0,0] if no ref list was inputted
        cur_rotp=rotation_point_list[tp_num]

        cur_stack = format_stack(timepoint=tp_num,              
                                 reference_point=cur_refp,
                                 rotation_point=cur_rotp)        #add to dict which houses stacks (frames)
        frame_dict[tp_num] = cur_stack

    manual_time_taken = time.time()-start_manual_time
    return(frame_dict, manual_time_taken)



#Testing stuff out
"""frame_dict, manual_time_taken = prepare_manual_data(path_to_timepoints='C:/Users/areil/Desktop/Terra/Unprocessed Animations/Germarium6_96dpi',
                                                    reference_point_list = [[95, 212], [43, 172], [50, 176], [63, 172], [63, 178], [60, 178], [61, 173], [79, 192], [61, 168], [57, 173], [58, 176], [54, 171], [49, 180], [41, 175], [37, 179], [33, 181], [33, 175], [28, 179], [22, 180], [24, 179], [17, 181]],
                                                    image_dimensions = [512, 512], 
                                                    sort_large_groups = True)

frame_dict, manual_time_taken = prepare_manual_data(path_to_timepoints='C:/Users/areil/Desktop/Terra/Unprocessed Animations/A1 manual data',
                                                    reference_point_list = [[300, 663]],
                                                    image_dimensions = [512, 512], 
                                                    sort_large_groups = True)



with open("C:/Users/areil/Desktop/Terra/Programs/Program Outputs/Test 12 A1 manual formatted data.txt", 'w') as f:
    f.write(str(frame_dict))

"""