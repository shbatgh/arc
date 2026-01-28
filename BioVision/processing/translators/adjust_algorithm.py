#Adjusts outlines and rotates them
import math
def adjust_group(group, reference_point, rotation_point, should_rotate):
    ox, oy = reference_point[0], reference_point[1]

    if not should_rotate:
        return([[coord[0]-ox, coord[1]-oy] for coord in group])
    
    result = []
    angle = -math.atan((rotation_point[1]-oy)/(rotation_point[0]-ox))

    for coord in group:
        px, py = coord[0], coord[1]
        adj_px, adj_py = px-ox, py-oy
        qx = math.cos(angle) * (adj_px) - math.sin(angle) * (adj_py)
        qy = math.sin(angle) * (adj_px) + math.cos(angle) * (adj_py)
        
        if ox-rotation_point[0]<0:
            qx, qy = -qx, -qy
        result.append([qx,qy])

    result.append(result[0])        #To complete the loop
    result.append(result[1])
    #result.append(result[1])
    return(result)