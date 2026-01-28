import os
import adjust_algorithm

##Helper Methods
def add_to_dict(dict, color, group):
    if color in dict.keys():
        dict[color].append(group)
    else:
        dict[color] = [group]

def adjust_outline(outline, ref_point, rot_point):
    adjusted_group = adjust_algorithm.adjust_group(group =outline,
                                                   reference_point = ref_point,
                                                   rotation_point = rot_point,
                                                   should_rotate = True)
    return(adjusted_group)

##--------------------------



def line_to_group(line):
    group = [[int(line[i]), int(line[i+1])] for i in range(0, len(line), 2)]       #Adjusted to reference
    group+= [group[0], group[1], group[2]]                                              #Loops around so wireframes are complete
    return(group)

def format_slice(ref_point, rot_point, txt_outlines):
    slice_dict = {}

    #slice_txt_path = tp_path+'/seg_'+timepoint+'/txt_outlines/'+str(slice_num+1)+'_cp_outlines.txt'         #e.g. tp_path/seg_t1/txt_outlines/1_cp_outlines.txt
    #if not os.path.isfile(slice_txt_path):
        #return(slice_dict)

    f = open(txt_outlines, "r")          #Groups come from segmentation data
  
    for line in f:
        line = line.split(',')
        cur_group = line_to_group(line = line)
        
        adjusted_outline = adjust_outline(outline=cur_group,
                                          ref_point=ref_point,
                                          rot_point=rot_point)
        
        
        add_to_dict(dict = slice_dict,
                    color = (253,0,0),
                    group = adjusted_outline)
    return(slice_dict)


def format_stack(stack, ref_point, rot_point):
    print("Formatting stack")

    stack_txt_outlines = [ f.path for f in os.scandir(stack) if f.is_file() ]
    n_slices = len(stack_txt_outlines)
    
    stack_list=[]
    for slice_num in range(n_slices):          #slices are numbered 1 through n
        cur_slice = format_slice(ref_point=ref_point,
                                 rot_point=rot_point,
                                 txt_outlines = stack_txt_outlines[slice_num])
        print(cur_slice)
        stack_list.append(cur_slice)
    return(stack_list)


def interpretAISegData(path):
    timepoint_folders = [f.path for f in os.scandir(path) if f.is_dir()]
    n_timepoints = len(timepoint_folders)
    
    frame_dict = {}
    for tp_num in range(n_timepoints):
        stack=timepoint_folders[tp_num]
        cur_refp=ref_list[tp_num]
        cur_rotp=rot_list[tp_num]

        cur_stack = format_stack(stack=stack,              
                                 ref_point=cur_refp,
                                 rot_point=cur_rotp)        #add to dict which houses stacks (frames)
        
        frame_dict[tp_num] = cur_stack

    return(frame_dict)

path_to_tps = "C:/Users/areil/Desktop/Terra/Unprocessed Animations/Green Cell Isolation 21tps"
#ref_list = [[111, 80], [100, 121], [103, 123], [105, 118], [112, 111], [105, 113], [105, 108], [114, 99], [103, 105], [106, 104], [100, 108], [97, 102], [98, 101], [100, 101], [96, 99], [100, 95], [99, 95], [99, 95], [100, 93], [107, 83], [107, 83], [114, 75], [106, 79], [112, 76], [114, 79], [111, 81], [101, 89], [109, 86], [110, 85], [108, 87], [107, 87], [104, 87], [108, 84], [95, 96], [88, 97], [96, 92], [89, 94], [84, 101], [83, 99], [83, 101], [80, 109], [74, 109], [88, 118], [120, 122], [141, 140], [162, 161]]
#rot_list = [[236, 212], [244, 261], [249, 263], [231, 253], [254, 260], [248, 257], [248, 261], [253, 256], [249, 276], [255, 270], [243, 252], [236, 261], [237, 256], [243, 259], [248, 259], [249, 259], [258, 251], [252, 253], [250, 254], [250, 241], [258, 256], [262, 255], [254, 249], [242, 225], [274, 259], [267, 258], [272, 273], [276, 273], [283, 268], [274, 261], [305, 288], [316, 280], [316, 281], [317, 290], [309, 300], [305, 291], [309, 283], [310, 290], [319, 290], [307, 304], [332, 303], [319, 294], [332, 307], [351, 332], [354, 353], [367, 387]]
ref_list=[[0,0]]
rot_list=[[1,0]]


frame_dict = interpretAISegData(path_to_tps)

with open("C:/Users/areil/Desktop/Terra/Programs/Program Outputs/CROPPED Crawfish stack.txt", 'w') as f:
    f.write(str(frame_dict))
print("DONE")