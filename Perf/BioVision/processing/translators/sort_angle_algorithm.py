#Sorting algorithm by arctan
import math

def sortFn(coords):
    P_x, P_y = coords[0], coords[1]
    return(math.atan((P_y-center[1])/(P_x-center[0])))      #Returns angle made by the center, the point, and the x-axis (Adjusted to the center)


def split_group(group_lst, C_x):
    right_group = []
    left_group = []
    for point in group_lst:
        if point[0] > C_x:      #Anything to the right of the center point
            right_group.append(point)
        else:
            left_group.append(point)
    return(right_group, left_group)

def sort_group(sort, group):
    if sort and len(group) > 3:
        #group = large_group_sorter.sort_group(group)
        global center
        x_avg = int(sum([coord[0] for coord in group])/len(group))
        y_avg = sum([coord[1] for coord in group])/len(group)
        center = (x_avg +0.5, y_avg)       #Adjusting a tiny bit so that the arctan doesn't equal 0

        right_group, left_group = split_group(group_lst=group,
                                              C_x=center[0])
        
        right_group.sort(key=sortFn)
        left_group.sort(key=sortFn)
        group = right_group + left_group
    return(group)
