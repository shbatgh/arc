import os
import math
import random

def create_center_dict(slice_outlines):     #takes txt_outlines for a single slice and converts it into a dictionary in the form {center: outlines, ...}
    center_dict = {}
    for outline in slice_outlines:
        center = (sum([coord[0] for coord in outline])/len(outline), sum([coord[1] for coord in outline])/len(outline))
        center_dict[center] = outline
    return(center_dict)

def line_to_group(line):
    group = [[int(line[i]), int(line[i+1])] for i in range(0, len(line), 2)]       #Adjusted to reference
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

    print("Length slice_paths,", len(slice_paths))

    for slice_txt_path in slice_paths:
        slice_outlines = []
        f = open(slice_txt_path, "r")          #Groups come from segmentation data    
        for line in f:
            line = line.split(',')
            slice_outlines.append(line_to_group(line))

        stack_list.append(create_center_dict(slice_outlines))
    
    for i in range(adjustment_off_first_slice(slice_paths)):
        stack_list = [{}] + stack_list

    return(stack_list)
    


#------------------------------By now, we have a stack list, with each element being a dictionary {center: outline, center: outline, ...}
#C:/Users/areil/Desktop/Terra/Programs/Program Outputs/test2-A1 AI segmentations/seg_t4/txt_outlines

cell_count = 0      #Number of cells, used for making cell_id
cells = []          #list containing all cell objects

def create_center_list(stack_list):         #Creates an empty list of dictionaries. The dictionaries will be in the form 
    center_list=[]
    for slice_num in range (len(stack_list)):
        center_list.append({})
    return (center_list)

class Cell:         #Cell class
    def __init__(self, id, starting_slice, initial_center, initial_outline):
        self.id = id
        self.starting_slice = starting_slice
        self.centers = [initial_center]
        self.outlines = [initial_outline]
        self.color = (random.randint(0,256), random.randint(0,256), random.randint(0,256))


def create_cell(starting_slice, initial_center, initial_outline):           #creates a cell
    global cell_count
    cell_count+=1
    new_cell = Cell(id = 'Cell' + str(cell_count),
                    starting_slice=starting_slice,
                    initial_center=initial_center,
                    initial_outline=initial_outline)
    
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

    print("starting slice", cell.starting_slice)
    print("how many slices up?", len(cell.centers)-1)

    center_list[cell.starting_slice + len(cell.centers)-1][cell.id] = center
    

def initial_cells (stack_list):     #Creates sells on the first slice
    for center,outline in stack_list[0].items():
        create_cell(starting_slice=0,
                    initial_center=center,
                    initial_outline=outline)

def group_cells(stack_list):
    add_count = 0
    global center_list
    for cur_slice_num in range (1, len(stack_list)):
        slice_dict = stack_list[cur_slice_num]
        prev_center_dict = center_list[cur_slice_num - 1]
        for c_center, c_outline in slice_dict.items():
            cell_found_marker = False
            for prev_id, prev_center in prev_center_dict.items():
                prev_cell = identify_cell(prev_id)
                if math.dist(c_center, prev_center) <15 and prev_cell.starting_slice+len(prev_cell.centers)==cur_slice_num:
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
    print(add_count)





#----------------------------Up to now, we have a list of cell objects, with atributes id, starting_slice, centers, outlines, and color------

def identify_cell_from_center(center):
    for cell in cells:
        if center in cell.centers:
            return(cell)

def adjust_outline(outline, ref_point):
    ref_x, ref_y = ref_point[0], ref_point[1]
    adjusted_outline = []
    for coord in outline:
        cur_x, cur_y = coord[0], coord[1]
        adjusted_outline.append([cur_x-ref_x, cur_y-ref_y])
    return(adjusted_outline)



def format_stack_list(stack_list, ref_point):
    formatted_stack_list = []
    for cur_slice_dict in stack_list:
        formatted_slice_dict = {}
        for cur_center, cur_outline in cur_slice_dict.items():
            cur_cell = identify_cell_from_center(cur_center)
            adjusted_outline = adjust_outline(outline=cur_outline,
                                              ref_point=ref_point)
            formatted_slice_dict[cur_cell.color] = [adjusted_outline]
        formatted_stack_list.append(formatted_slice_dict)
    return(formatted_stack_list)





stack_list = create_stack_list(stack_path="C:/Users/areil/Desktop/Terra/Programs/Program Outputs/test2-A1 AI segmentations/seg_t06/txt_outlines")

n_slices = len(stack_list)

center_list = create_center_list(stack_list)

group_cells(stack_list)


formatted_stack_list = format_stack_list(stack_list = stack_list, 
                                         ref_point = [105, 113])

temporary_changed_dict = {0:[], 1:[], 2:[], 3:[], 4:[], 5: formatted_stack_list, 6:[], 7:[], 8:[], 9:[], 10:[], 11:[], 12:[], 13:[], 14:[], 15:[], 16:[], 17:[], 18:[], 19:[]}

with open("C:/Users/areil/Desktop/Terra/Programs/Program Outputs/test16-A1 t06 AI Formatted new.txt", 'w') as f:
    f.write(str(temporary_changed_dict))