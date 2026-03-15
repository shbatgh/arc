#This uses animation_cell_matching.py to get quantitative data.

##----The functions below are applied on a cell3D object, and they find various quantitative information

import pandas as pd
import copy


round_decimal_place = 1     #Make False for no rounding
num_interp = 20

tens = -0.75
cont = 0
bias = 0
points_per_segment = 5



def get_positions(cell3D):
    res = []
    for i in range(0, cell3D.starting_tp):  #Adds None where cell isnt in that tp at the start
        res.append(None)

    res += cell3D.centers3D     #Adds centers

    while len(res)<num_tps:
        res.append(None)
    return(res)


def get_displacement_vecs(positions):
    res = [None]

    for i in range(1, len(positions)):
        if positions[i-1] == None or positions[i] == None:
            res.append(None)
        else:
            x = positions[i][0] - positions[i-1][0]
            y = positions[i][1] - positions[i-1][1]
            z = positions[i][2] - positions[i-1][2]
            res.append((x,y,z))
    return(res)


def get_distance_travelled(displacements):
    res = []
    for displ in displacements:
        if displ == None:
            res.append(None)
        else:
            res.append(sum([coord**2 for coord in displ])**0.5)
    return(res)


def round_tuple(tup, place):
    if tup == None:
        return(None)
    working_tup = copy.deepcopy(tup)
    res = []
    for elem in working_tup:
        res.append(round(elem, place))
    return(tuple(res))


def round_num(num, place):
    if num == None:
        return(None)
    return(round(num, place))



#Filtering Cell3D objects, in case a spec or accidental line was picked up
def cell_filter(cell3D):
    max_outlines = []
    for single_tp_cell in cell3D.cells_list:
        max_outlines.append(max([len(outline) for outline in single_tp_cell.outlines]))
    return(max(max_outlines)>10)  #Numer chosen arbitrarily





#--------------------SOLID MESH CREATION-------------------------------
import sys
sys.path.insert(1, 'C:/Users/areil/Desktop/BioVision/processing/mesh_creation')
#import triple_wireframe_interpolated
import cell_point_filler
import solid_mesh_from_3D_outlines


def get_solid_mesh_objs(cell3D, points_per_segment):        #FIX THIS UP
    mesh_objs = []
    
    for i in range(0, cell3D.starting_tp):  #Adds None where cell isnt in that tp at the start
        mesh_objs.append(None)

    for single_tp_cell in cell3D.cells_list:
        outlines_3D = []

        for idx in range(len(single_tp_cell.outlines)):     #Make 2D slice outlines 3D
            outline_2D = single_tp_cell.outlines[idx]
            fin_outline = []
            for coord in outline_2D:
                fin_outline.append([coord[0], coord[1], (single_tp_cell.starting_slice+idx)*3/0.198])
            
            outlines_3D.append(fin_outline)

        splined_xz, splined_yz = cell_point_filler.point_filler(cell=single_tp_cell, tens=tens, cont=cont, bias=bias, points_per_segment=points_per_segment)
        outlines_3D += splined_xz + splined_yz

        for outline in outlines_3D:     #Multiplies all zs by 2 because of the weird format
            for idx in range (len(outline)):
                outline[idx] = [outline[idx][0], outline[idx][1], outline[idx][2]]        #Still need to multiply by two?


        outlines_3D = [outline for outline in outlines_3D if len(outline) >16]  #Numer chosen arbitrarily
        num_points = min([len(outline) for outline in outlines_3D])
        print("Num points: ", num_points)

        mesh = solid_mesh_from_3D_outlines.build_mesh(outlines_3D = outlines_3D,
                                                    num_points = num_points,
                                                    visualize_true = False)
        mesh_objs.append(mesh)
    
    while len(mesh_objs)<num_tps:
        mesh_objs.append(None)
    return(mesh_objs)

#---------------------------------------------------------------------
##SOLID MESHES without intermedite wireframe meshes:

import fast_solid_creater
def get_fast_solids(cell3D):
    mesh_objs = []
    for i in range(0, cell3D.starting_tp):  #Adds None where cell isnt in that tp at the start
        mesh_objs.append(None)


    for single_tp_cell in cell3D.cells_list:
        cur_outlines = single_tp_cell.outlines

        if len(cur_outlines) ==1:
            mesh_objs.append(None)
            continue

        #Now I need to convert the 2D outlines to 3D outlines
        """
        for idx in range(len(cur_outlines)):
            cur_z = (single_tp_cell.starting_slice+idx)*3/0.198
            for point in cur_outlines[idx]:
                point.append(cur_z)
        """

        mesh = fast_solid_creater.build_concave_mesh_from_outlines(outlines=cur_outlines,
                                                                   z_spacing=3/0.198,
                                                                   num_interp=10,
                                                                   num_points=100,
                                                                   slice_start=single_tp_cell.starting_slice)
        mesh_objs.append(mesh)

    while len(mesh_objs)<num_tps:
        mesh_objs.append(None)
    return(mesh_objs)

##---------------





def get_volumes(cell3D):
    meshes = get_solid_mesh_objs(cell3D=cell3D, points_per_segment=points_per_segment)
    res = []

    for mesh in meshes:
        if mesh == None:
            res.append(None)
        else:
            res.append(mesh.volume)
    return(res)


def get_SAs(cell3D):
    meshes = get_solid_mesh_objs(cell3D=cell3D, points_per_segment=points_per_segment)
    res = []

    for mesh in meshes:
        if mesh == None:
            res.append(None)
        else:
            res.append(mesh.area)
    return(res)


#--- For exporting the data and running it

def export_csv_data(cells3D):
    data = []
    for cell3D in cells3D:
        data.append({
            "Cell ID": cell3D.id,
            })
    
        positions = get_positions(cell3D=cell3D)
        displacement_vecs = get_displacement_vecs(positions=positions)
        distances = get_distance_travelled(displacement_vecs)

        volumes = get_volumes(cell3D=cell3D)
        SAs = get_SAs(cell3D=cell3D)

        for timepoint in range(num_tps):
            # Assume cell_data = {"x": ..., "y": ..., "z": ...}

            pos = round_tuple(tup = positions[timepoint], place = round_decimal_place)
            displ_vec = round_tuple(tup = displacement_vecs[timepoint], place = round_decimal_place)
            dist = round_num(num = distances[timepoint], place = round_decimal_place)
            
            vol = round_num(num = volumes[timepoint], place = round_decimal_place)
            area = round_num(num = SAs[timepoint], place = round_decimal_place)

            data.append({
                "": None,
                "Timepoint": timepoint,
                " ": None,
                "Position": pos,
                "  ": None,
                "Displacement Vector": displ_vec,
                "   ": None,
                "Distance Traveled": dist,
                "    ": None,
                "Volume": vol,
                "     ": None,
                "Surface Area": area,
                "      ": None
                })


    df = pd.DataFrame(data)

    # CSV (universal, simple)
    df.to_csv("quant_data.csv", index=False)

    # Excel (for biologists who like Excel)
    #df.to_excel("quant_data.xlsx", index=False)



def export_solid_meshs(cells3D, points_per_segment, output_path):
    mesh_frames_dict = {}

    for cell_idx, cell3D in enumerate(cells3D):
        meshes = get_solid_mesh_objs(cell3D=copy.deepcopy(cell3D), points_per_segment=points_per_segment)       ##get_fast_solids or get_solid_mesh_objs

        for t, mesh in enumerate(meshes):
            if mesh is None:
                continue

            mesh_obj = {
                'vertices': mesh.vertices.tolist(),
                'faces': mesh.faces.tolist(),
                'color': cell3D.color,        # Tuple (R, G, B)
                'name': f'cell_{cell_idx}_t{t}'
            }

            if t not in mesh_frames_dict:
                mesh_frames_dict[t] = []

            mesh_frames_dict[t].append(mesh_obj)

    # Save to .txt file
    with open(output_path, 'w') as f:
        f.write("MESH\n")
        f.write(str(mesh_frames_dict))

    print(f"Exported solid mesh data to {output_path}")
    return mesh_frames_dict
"""
structure for tracer data:

result = {tp1: [slice_dict], tp1: [slice_dict]}

slice_dict = {color: all_tracers}

all_tracers = [trac1, trac2, ....]

tracer = [[x1, y1], [x2, y2], ...]
"""
def export_tracers(cells3D):
    slice_dict = {}

    for cell_obj in cells3D:
        c_color = cell_obj.color
        #Altering the color of the tracer:
        R = c_color[0]
        G = c_color[1]
        B = c_color[2]
        if (R<G and R<B):
            R = (R+128)%256
        elif (G<B):
            G = (G+128)%256
        else:
            B = (B+128)%256
        
        col = (R,G,B)

        positions = copy.deepcopy(get_positions(cell_obj))

        positions = [i for i in positions if i != None]

        if col in slice_dict.keys():
            slice_dict[col].append(positions)
        else:
            slice_dict[col] = [positions]
    
    res = {}
    for tp in range (num_tps):
        res[tp] = [slice_dict]
    
    with open("tracers.txt", 'w') as f:
        f.write(str(res))
    
    return(res)




##-----Getting cell-tracking data from animation_cell_matching
import animation_cell_matching

colors= [(255,0,255)]      #(255,0,0), (0,0,255), (0,255,255), (255,0,255), (200,200,0), (200,0,100), (0,100,0), (150,50,50), (255,200,100)
#WHY (0,100,0) not picked up???


print("Matching stacks")
all_raw_cells = []
for col in colors:
    print(col)
    cur_cells = animation_cell_matching.get_raw_cell_data(path = "C:/Users/areil/Desktop/Terra/Programs/Program Outputs/ForTaraPos10_fixed.txt",
                                                          color = col)
    if len(all_raw_cells) == 0:
        all_raw_cells += cur_cells
    else:
        for idx in range (len(all_raw_cells)):
            all_raw_cells[idx] += cur_cells[idx]
    

num_tps = len(all_raw_cells)
print("Number of Timepoints: ", num_tps)


print("Matching animation")
cells3D = []
for col in colors:
    print(col)
    cells3D += animation_cell_matching.compute_animation(copy.deepcopy(all_raw_cells), col)

print("Number of cells before filter: ", len(cells3D))
scrap_cells = [cell for cell in cells3D if not cell_filter(cell)]
cells3D = [cell for cell in cells3D if cell_filter(cell)]
print("After filter: ", len(cells3D))
for scrap in scrap_cells:
    print("Scrap cell, ", scrap.color)

##-----------------------------------------------------------



#export_tracers(cells3D=cells3D)
#export_csv_data(cells3D=cells3D)
print("Exporting Meshes")

export_solid_meshs(cells3D=cells3D, points_per_segment=points_per_segment, output_path='C:/Users/areil/Desktop/Terra/Programs/Program Outputs/solid_meshes_quick ForTaraPos10')