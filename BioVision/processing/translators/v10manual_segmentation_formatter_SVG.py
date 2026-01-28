"""
SAME AS V10manual_segmentation_formatter except for svg
#Didn't touch format_stack or prepare_manual_data (except getting rid of meaningless inputs now like width and height)
"""
import time
import sys
import os

import adjust_algorithm

import svg_translator

sparse = True

sys.setrecursionlimit(1500)


def format_slice(slice_path, reference_point, rotation_point):
    slice_data = svg_translator.extract_slice_from_svg(slice_path)
    
    for color, cells_list in slice_data.items():
        for idx, cur_cell in enumerate(cells_list):
            adjusted_cell = adjust_algorithm.adjust_group(group = cur_cell,
                                                        reference_point = reference_point,
                                                        rotation_point = rotation_point,
                                                        should_rotate = should_rotate)
            adjusted_cell.append(adjusted_cell[0])
            adjusted_cell.append(adjusted_cell[1])
            adjusted_cell.append(adjusted_cell[2])

            slice_data[color][idx] = adjusted_cell
    return(slice_data)


""" NEED TO APPEND FIRST COORDS TO WRAP AROUND?? (FOR ABOVE FUNC, format_slice) ENDED UP DOING IT. Remember, repeats are removed in point cloud for mesh creation so doesn't matter
fin_coords.append(fin_coords[0])
fin_coords.append(fin_coords[1])
fin_coords.append(fin_coords[2])

"""


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
        



def prepare_manual_data(path_to_timepoints, reference_point_list, rotation_point_list, rotate):
    global should_rotate
    should_rotate = rotate

    start_manual_time = time.time()
    print("Preparing Manual Data")


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