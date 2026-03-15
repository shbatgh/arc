import os
import math
import random

import adjust_algorithm

def create_center_dict(slice_outlines):     #takes txt_outlines for a single slice and converts it into a dictionary in the form {center: outlines, ...}
    center_dict = {}
    for outline in slice_outlines:
        center = (sum([coord[0] for coord in outline])/len(outline), sum([coord[1] for coord in outline])/len(outline))
        center_dict[center] = outline
    return(center_dict)

def line_to_group(line):
    group = [[int(line[i]), int(line[i+1])] for i in range(0, len(line), 2)]       #NOT Adjusted to reference
    group+= [group[0], group[1], group[2]]                                              #Loops around so wireframes are complete
    return(group)

def adjustment_off_first_slice(slice_paths):    #Takes slice paths list, and returns how many first txt_outlines are missing. For example, if slice paths starts with 2.txt..., there is 1 missing outline

    first_slice = ""
    break_marker = False

    searching_for_num = list(os.path.basename(os.path.normpath(slice_paths[0])))
    for char in searching_for_num:
        if char.isdigit():
            first_slice += char
            break_marker = True
        elif break_marker == True:
            break
    first_slice = int(first_slice)

    return (first_slice-1)




def create_stack_list(stack_path):      #Takes the directory where all txt_outlines are stored, has elements in the form {center: outlines....}
    stack_list = []
    slice_paths = [f.path for f in os.scandir(stack_path) if f.is_file()]

    #print("Length slice_paths,", len(slice_paths))

    for slice_txt_path in slice_paths:
        slice_outlines = []
        f = open(slice_txt_path, "r")          #Groups come from segmentation data    
        for line in f:
            line = line.split(',')
            slice_outlines.append(line_to_group(line))

        stack_list.append(create_center_dict(slice_outlines))
    
    for i in range(adjustment_off_first_slice(slice_paths)):
        stack_list = [{}] + stack_list

    print("Stack list length", len(stack_list))

    return(stack_list)
    


#------------------------------By now, we have a stack list, with each element being a dictionary {center: outline, center: outline, ...}
#C:/Users/areil/Desktop/Terra/Programs/Program Outputs/test2-A1 AI segmentations/seg_t4/txt_outlines


colors = [(253,0,0), (0,253,0), (0,0,253), (253,253,253), (253,253,0), (253,0,253), (0,253,253), (253,128,0), (253,0,128), (128,253,0), (0,253,128), (0,128,253), (128,0,253), (128,128,128)]        #, (64,0,0), (0,64,0), (0,0,64), (64,64,0), (64,0,64), (0,64,64)

def find_cell_perimeter(outline):       #Unused so far
    return(len(outline))

def create_center_list(stack_list):         #Creates an empty list of dictionaries. The dictionaries will be in the form 
    center_list=[]
    for slice_num in range (len(stack_list)):
        center_list.append({})
    return (center_list)

class Cell:         #Cell class
    def __init__(self, id, starting_slice, initial_center, initial_outline, c_color):
        self.id = id
        self.starting_slice = starting_slice
        self.centers = [initial_center]
        self.outlines = [initial_outline]
        self.color = c_color
    
    def find_3D_center(self):           #Unused so far
        x_avg = sum([coord[0] for coord in self.centers])/len(self.centers)
        y_avg = sum([coord[1] for coord in self.centers])/len(self.centers)
        z_avg = (3/0.198)* (self.starting_slice + (len(self.centers)/2))                                          #(3/0.198) conversion from x,y to z. Second term gets average slice
        return([x_avg, y_avg, z_avg])




def create_cell(starting_slice, initial_center, initial_outline):           #creates a cell
    global cell_count
    cell_count+=1
    new_cell = Cell(id = 'Cell' + str(cell_count),
                    starting_slice=starting_slice,
                    initial_center=initial_center,
                    initial_outline=initial_outline,
                    c_color = colors[cell_count%len(colors)])
    
    cells.append(new_cell)

    global center_list
    center_list[starting_slice][new_cell.id] = initial_center

def identify_cell(cell_id):
    for cell in cells:
        if cell.id == cell_id:
            return(cell)

def add_to_cell(id, center, outline):           #Adds outlines and centers to cells
    global center_list
    cell = identify_cell(cell_id=id)
    cell.centers.append(center)
    cell.outlines.append(outline)

    #print("starting slice", cell.starting_slice)
    #print("how many slices up?", len(cell.centers)-1)

    center_list[cell.starting_slice + len(cell.centers)-1][cell.id] = center
    

def initial_cells (stack_list):     #Creates sells on the first slice
    print(stack_list[0])
    for center,outline in stack_list[0].items():
        create_cell(starting_slice=0,
                    initial_center=center,
                    initial_outline=outline)

def group_cells(stack_list):
    add_count = 0
    global center_list, cell_count
    for cur_slice_num in range (1, len(stack_list)):
        slice_dict = stack_list[cur_slice_num]
        prev_center_dict = center_list[cur_slice_num - 1]
        for c_center, c_outline in slice_dict.items():
            cell_found_marker = False
            for prev_id, prev_center in prev_center_dict.items():
                prev_cell = identify_cell(prev_id)
                if math.dist(c_center, prev_center) <radius and prev_cell.starting_slice+len(prev_cell.centers)==cur_slice_num:
                    add_count+=1
                    add_to_cell(id=prev_id,
                                center=c_center,
                                outline=c_outline)
                    cell_found_marker = True
                    break
            
            if cell_found_marker == False:
                create_cell(starting_slice=cur_slice_num,
                            initial_center=c_center,
                            initial_outline=c_outline)
    print("Segmentations belonging to other cells:", add_count)
    print("Number of cells:", cell_count)



#---------------Now I needa clean up stuff (cells that are too long are really 2 cells on top of eachother)






#----------------------------Up to now, we have a list of cell objects, with atributes id, starting_slice, centers, outlines, and color------

def identify_cell_from_center(center):
    #print([cell.centers for cell in cells])
    #print(center)
    for cell in cells:
        if center in cell.centers:
            return(cell)

def adjust_outline(outline, ref_point, rot_point):
    adjusted_group = adjust_algorithm.adjust_group(group =outline,
                                                   reference_point = ref_point,
                                                   rotation_point = rot_point,
                                                   should_rotate = True)
    return(adjusted_group)


def add_outline_to_dict(color, dict, outline):
    if color in dict.keys():
        dict[color].append(outline)
    else:
        dict[color] = [outline]



def format_stack_list(stack_list, ref_point, rot_point):
    formatted_stack_list = []
    for cur_slice_dict in stack_list:
        formatted_slice_dict = {}
        for cur_center, cur_outline in cur_slice_dict.items():
            cur_cell = identify_cell_from_center(cur_center)
            adjusted_outline = adjust_outline(outline=cur_outline,
                                              ref_point=ref_point,
                                              rot_point=rot_point)
            add_outline_to_dict(color=cur_cell.color,
                                dict=formatted_slice_dict,
                                outline=adjusted_outline)
        formatted_stack_list.append(formatted_slice_dict)
    return(formatted_stack_list)







#--------- Up to now, we render a full stack. Combine everything to make it multiple timepoints

radius = 30
path_to_tps = "C:/Users/areil/Desktop/Terra/Unprocessed Animations/greengo3tps"
ref_list = [[111, 80], [100, 121], [103, 123], [105, 118], [112, 111], [105, 113], [105, 108], [114, 99], [103, 105], [106, 104], [100, 108], [97, 102], [98, 101], [100, 101], [96, 99], [100, 95], [99, 95], [99, 95], [100, 93], [107, 83], [107, 83], [114, 75], [106, 79], [112, 76], [114, 79], [111, 81], [101, 89], [109, 86], [110, 85], [108, 87], [107, 87], [104, 87], [108, 84], [95, 96], [88, 97], [96, 92], [89, 94], [84, 101], [83, 99], [83, 101], [80, 109], [74, 109], [88, 118], [120, 122], [141, 140], [162, 161]]
rot_list = [[270, 277], [266, 307], [273, 305], [275, 295], [275, 303], [269, 304], [278, 295], [263, 304], [263, 307], [278, 292], [274, 299], [271, 303], [269, 288], [272, 284], [265, 285], [271, 289], [276, 280], [279, 271], [281, 274], [278, 269], [284, 264], [287, 263], [286, 254], [289, 265], [295, 266], [291, 282], [290, 288], [296, 285], [300, 289], [299, 299], [306, 307], [318, 286], [320, 297], [323, 293], [310, 305], [307, 301], [324, 299], [323, 293], [327, 291], [313, 293], [320, 287], [315, 291], [331, 309], [355, 338], [363, 370], [378, 403]]
#Got from program outputs, test4 reflist A1


stack_paths = [os.path.normpath(f.path) for f in os.scandir(path_to_tps) if f.is_dir()]
all_cells = []
frame_dict = {}

tp_num = -1
for cur_stack_path in stack_paths:
    tp_num +=1
    print("\n\nStack: ", tp_num)
    cell_count = 0      #Number of cells, used for making cell_id
    cells = []          #list containing all cell objects. Gets reset every iteration, so is added to a separate list at the end
    stack_list = create_stack_list(stack_path=cur_stack_path)
    center_list = create_center_list(stack_list)
    initial_cells(stack_list)
    group_cells(stack_list)

    formatted_stack_list = format_stack_list(stack_list = stack_list, 
                                            ref_point = ref_list[tp_num],
                                            rot_point = rot_list[tp_num])

    frame_dict[tp_num] = formatted_stack_list

    all_cells.append(cells)


#---------------------Finished with the frame dictionary, now output it in a txt_file

with open("C:/Users/areil/Desktop/Terra/Programs/Program Outputs/greengo3tps test.txt", 'w') as f:
    f.write(str(frame_dict))

#round centers to 3rd decimal point