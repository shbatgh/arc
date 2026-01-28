#SAME AS FORMATTING PREPARATION< BUT FOR SVG

#NOT WORKED ON YET



from PIL import Image
import os

import svg_translator

def find_reference_points(path_to_timepoints, reference_point_color):
    timepoint_folders = [f.path for f in os.scandir(path_to_timepoints) if f.is_dir()]
    print("Finding reference points on timepoints: ", end='')
    reference_point_list = []

    n_timepoints = len(timepoint_folders)

    for tp_num in range(n_timepoints):
        print(str(tp_num+1) + ' ', end='')
        ref_point_found = False

        svg_paths = [f.path for f in os.scandir(timepoint_folders[tp_num]) if f.is_file()]
        
        for slice_path in svg_paths:
            if ref_point_found:
                continue

            slice_data = svg_translator.extract_slice_from_svg(slice_path)
            
            if reference_point_color not in slice_data.keys():
                continue

            reference_cell_x = [point[0] for point in slice_data[reference_point_color][0]]
            reference_cell_y = [point[1] for point in slice_data[reference_point_color][0]]

            reference_point_list.append([int(sum(reference_cell_x) / len(reference_cell_x)), int(sum(reference_cell_y) / len(reference_cell_y))])
            ref_point_found = True

        if not ref_point_found: 
            print("No reference point found on timepoint t" + str(tp_num+1))
            reference_point_list.append([0,0])
    print("\n")


    return(reference_point_list)



#WHY AM I NOT USING THIS??? WTF
def find_ref_points_multiple_slices(path_to_timepoints, reference_point_color):
    timepoint_folders = [f.path for f in os.scandir(path_to_timepoints) if f.is_dir()]
    print("Finding reference points on timepoints: ", end='')
    reference_point_list = []

    n_timepoints = len(timepoint_folders)

    for tp_num in range(n_timepoints):
        print(str(tp_num+1) + ' ', end='')

        slice_images = [f.path for f in os.scandir(timepoint_folders[tp_num]) if f.is_file()]
        reference_cell_x, reference_cell_y = [], []
        
        for slice_path in slice_images:
            slice_data = svg_translator.extract_slice_from_svg(slice_path)
            
            if reference_point_color not in slice_data.keys():
                continue

            target_cell_list = slice_data[reference_point_color][0]
            if len(slice_data[reference_point_color]) > 1:
                print("ERROR, but will continue. " + str(len(slice_data[reference_point_color])) + " reference colored-cells present. Will take the largest cell of the color.", end="")
                max_idx = 0
                for idx in range (1, len(slice_data[reference_point_color])):
                    if len(slice_data[reference_point_color][idx]) > len(slice_data[reference_point_color][max_idx]):
                        max_idx = idx
                target_cell_list = slice_data[reference_point_color][max_idx]
                print("  ...Index chosen: " + str(max_idx))

            reference_cell_x += [point[0] for point in target_cell_list]
            reference_cell_y += [point[1] for point in target_cell_list]
    
        if len(reference_cell_x) != 0:
            reference_point_list.append([int(sum(reference_cell_x) / len(reference_cell_x)), int(sum(reference_cell_y) / len(reference_cell_y))])
        else:
            print("No reference point found on timepoint t" + str(tp_num+1))
            reference_point_list.append([0,0])
    print("\n")

    return(reference_point_list)