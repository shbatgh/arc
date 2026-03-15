"""
Notes:
Color map on x and y coords. Center of a cell determines the cell color. Regard it as the same cell based on centers. How will user fix any mistake?

Try applying AI segmentation on maunal segs, to get complete, sorted wireframes

Speed should be found in blender. Should be able to fix by making a segmentation a certain color.

"""
import time
from PIL import Image
import os

def add_to_dict(dict, color, group):
    if color in dict.keys():
        dict[color].append(group)
    else:
        dict[color] = [group]

def find_color(img_outlines, coords):           #Does not distinguish between frames
    img = Image.open(img_outlines)        #e.g. tp_path/seg_t1/outlines/1_outlines.txt
    pix = img.load()
    color = pix[int(coords[0]),int(coords[1])][:3]
    return(color)

#def make_color()

def line_to_group(line, reference_point):
    group = [[int(line[i]) - reference_point[0], int(line[i+1])- reference_point[1]] for i in range(0, len(line), 2)]       #Adjusted to reference
    group+= [group[0], group[1], group[2]]                                              #Loops around so wireframes are complete
    return(group)



def format_slice(reference_point, img_outlines, txt_outlines):
    slice_dict = {}

    #slice_txt_path = tp_path+'/seg_'+timepoint+'/txt_outlines/'+str(slice_num+1)+'_cp_outlines.txt'         #e.g. tp_path/seg_t1/txt_outlines/1_cp_outlines.txt
    #if not os.path.isfile(slice_txt_path):
        #return(slice_dict)

    f = open(txt_outlines, "r")          #Groups come from segmentation data    
    for line in f:
        line = line.split(',')
        cur_group = line_to_group(line=line,
                                  reference_point=reference_point)
        cur_color = find_color(img_outlines=img_outlines,
                               coords=[line[0], line[1]])
        
        add_to_dict(slice_dict, cur_color, cur_group)
    return(slice_dict)




def format_stack(timepoint, reference_point):
    cur_path = timepoint_folders[timepoint]
    print("Formatting stack " + os.path.basename(os.path.normpath(cur_path)))

    img_outline_path = os.path.normpath(cur_path) + "/outlines"
    txt_outline_path = os.path.normpath(cur_path) + "/txt_outlines"
    stack_img_outlines = [ f.path for f in os.scandir(img_outline_path) if f.is_file() ]
    stack_txt_outlines = [ f.path for f in os.scandir(txt_outline_path) if f.is_file() ]
    n_slices = len(stack_img_outlines)
    
    stack_list=[]
    for slice_num in range(n_slices):          #slices are numbered 1 through n
        cur_slice = format_slice(reference_point=reference_point,
                                 img_outlines = stack_img_outlines[slice_num],
                                 txt_outlines = stack_txt_outlines[slice_num])
        
        stack_list.append(cur_slice)
    return(stack_list)


def prepare_AI_data(path_to_timepoints, reference_point_list):
    start_AI_time = time.time()
    print("Preparing AI Data")


    global timepoint_folders
    timepoint_folders = [f.path for f in os.scandir(path_to_timepoints) if f.is_dir()]
    n_timepoints = len(timepoint_folders)
    
    frame_dict = {}
    for tp_num in range(n_timepoints):
        cur_refp=reference_point_list[tp_num]

        cur_stack = format_stack(timepoint=tp_num,              
                                 reference_point=cur_refp)        #add to dict which houses stacks (frames)
        
        frame_dict[tp_num] = cur_stack

    AI_time_taken = time.time()-start_AI_time
    return(frame_dict, AI_time_taken)
#######--------------------------------------------------------------------------------------------------------------------------------------------------------------------------
