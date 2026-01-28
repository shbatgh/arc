from PIL import Image
import os

def find_image_dimensions(path_to_timepoints):
    timepoint_folders = [f.path for f in os.scandir(path_to_timepoints) if f.is_dir()]
    tp1_images = [f.path for f in os.scandir(timepoint_folders[0]) if f.is_file()]
    img1_path = tp1_images[0]

    sample_img = Image.open(img1_path)            #CHANGE IF MAKING THE IMAGE NAMES CHANGEABLE
    width, height = sample_img.size
    print("Image dimensions: " + str(width) +", " + str(height))
    return([width, height])




def find_reference_points(path_to_timepoints, reference_point_color, image_dimensions):
    timepoint_folders = [f.path for f in os.scandir(path_to_timepoints) if f.is_dir()]
    print("Finding reference points on timepoints: ", end='')
    width, height = image_dimensions[0], image_dimensions[1]
    reference_point_list = []

    n_timepoints = len(timepoint_folders)

    for tp_num in range(n_timepoints):
        print(str(tp_num+1) + ' ', end='')
        ref_point_found = False

        slice_images = [f.path for f in os.scandir(timepoint_folders[tp_num]) if f.is_file()]
        
        for slice_path in slice_images:
            if ref_point_found:
                continue
            cur_img = Image.open(slice_path)
            pix = cur_img.load()
            reference_cell_x, reference_cell_y = [], []

            for x in range(width):
                for y in range(height):
                    if (pix[x,y][:3] == reference_point_color):
                        reference_cell_x.append(x)
                        reference_cell_y.append(y)
            if len(reference_cell_x) != 0:
                reference_point_list.append([int(sum(reference_cell_x) / len(reference_cell_x)), int(sum(reference_cell_y) / len(reference_cell_y))])
                ref_point_found = True

        if not ref_point_found: 
            print("No reference point found on timepoint t" + str(tp_num+1))
            reference_point_list.append([0,0])
    print("\n")


    return(reference_point_list)




def find_ref_points_multiple_slices(path_to_timepoints, reference_point_color, image_dimensions):
    timepoint_folders = [f.path for f in os.scandir(path_to_timepoints) if f.is_dir()]
    print("Finding reference points on timepoints: ", end='')
    width, height = image_dimensions[0], image_dimensions[1]
    reference_point_list = []

    n_timepoints = len(timepoint_folders)

    for tp_num in range(n_timepoints):
        print(str(tp_num+1) + ' ', end='')

        slice_images = [f.path for f in os.scandir(timepoint_folders[tp_num]) if f.is_file()]
        reference_cell_x, reference_cell_y = [], []
        
        for slice_path in slice_images:
            cur_img = Image.open(slice_path)
            pix = cur_img.load()

            for x in range(width):
                for y in range(height):
                    if (pix[x,y][:3] == reference_point_color):
                        reference_cell_x.append(x)
                        reference_cell_y.append(y)
    
        if len(reference_cell_x) != 0:
            reference_point_list.append([int(sum(reference_cell_x) / len(reference_cell_x)), int(sum(reference_cell_y) / len(reference_cell_y))])
        else:
            print("No reference point found on timepoint t" + str(tp_num+1))
            reference_point_list.append([0,0])
    print("\n")

    return(reference_point_list)