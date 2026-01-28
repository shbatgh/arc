#This uses animation_cell_matching.py to get quantitative data.

##----The functions below are applied on a cell3D object, and they find various quantitative information

import pandas as pd
import copy
import pickle


round_decimal_place = 1     #Make False for no rounding
num_interp = 20

tens = -0.65
cont = 0
bias = 0
points_per_segment = 6

pitch = 0.01


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
    if type(num) == str:
        return(num)
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
sys.path.insert(1, 'C:/Users/tajre/OneDrive/Documents/GitHub/BioVision/processing/mesh_creation')   #Used to be C:/Users/areil/Desktop/BioVision/processing/mesh_creation
#import triple_wireframe_interpolated
import cell_point_filler
import solid_mesh_from_point_cloud


def get_solid_mesh_objs(cell3D, points_per_segment=points_per_segment):        #FIX THIS UP
    mesh_objs = []
    
    for i in range(0, cell3D.starting_tp):  #Adds None where cell isnt in that tp at the start
        mesh_objs.append(None)

    for single_tp_cell in cell3D.cells_list:
        surface_points = []
        
        if len(single_tp_cell.outlines) <=1 :
            mesh_objs.append(None)
            continue
        
        """
        for idx in range(len(single_tp_cell.outlines)):     #Make 2D slice outlines 3D
            outline_2D = single_tp_cell.outlines[idx]
            skip = 1
            
            if len(outline_2D) > 300:
                print("Making outline smaller, cur length: ", len(outline_2D), " ", end = "     ")
                skip = len(outline_2D)//300
                print(skip, len(outline_2D[::skip]))
            
                
            for coord in outline_2D[::skip]:
                surface_points.append([coord[0], coord[1], (single_tp_cell.starting_slice+idx)*3/0.198 * 0.5])
        """
        splined_xz, splined_yz = cell_point_filler.point_filler(cell=single_tp_cell, tens=tens, cont=cont, bias=bias, points_per_segment=points_per_segment, top_spline = True)
        
        for outline in splined_xz+splined_yz:
            surface_points.extend(outline)
                
        """
        for outline in outlines_3D:     #Multiplies all zs by 2 because of the weird format
            for idx in range (len(outline)):
                outline[idx] = [outline[idx][0], outline[idx][1], outline[idx][2]]        #Still need to multiply by two?
        """

        num_points = len(surface_points)
        print("Created surface, num points: ", num_points)

        mesh = solid_mesh_from_point_cloud.wrap_blanket_over_point_cloud(points=surface_points)
        mesh_objs.append(mesh)
    
    while len(mesh_objs)<num_tps:
        mesh_objs.append(None)
    return(mesh_objs)





def get_volumes(meshes):
    res = []

    for mesh in meshes:
        if mesh == None:
            res.append(None)
        else:
            res.append(mesh.volume)
    return(res)


def get_SAs(meshes):
    res = []

    for mesh in meshes:
        if mesh == None:
            res.append(None)
        else:
            res.append(mesh.area)
    return(res)


#--- For exporting the data and running it

def export_csv_data(cells3D, output_path):
    data = []
    for cell3D in cells3D:
        print("\nCell ID: ", cell3D.id)
        data.append({
            "Cell ID": cell3D.id,
            })
    
    
        positions = get_positions(cell3D=cell3D)
        displacement_vecs = get_displacement_vecs(positions=positions)
        distances = get_distance_travelled(displacement_vecs)

        meshes = get_solid_mesh_objs(cell3D=cell3D)
        volumes = get_volumes(meshes=meshes)
        SAs = get_SAs(meshes=meshes)

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
    df.to_csv(output_path, index=False)

    # Excel (for biologists who like Excel)
    #df.to_excel("quant_data.xlsx", index=False)



def export_solid_meshs(cells3D, output_path, min_size = None):
    mesh_frames_dict = {}

    for cell_idx, cell3D in enumerate(cells3D):
        meshes = get_solid_mesh_objs(cell3D=copy.deepcopy(cell3D))       ##get_fast_solids or get_solid_mesh_objs

        for t, mesh in enumerate(meshes):

            if mesh is None:
                continue
            
            if min_size != None and mesh.volume < min_size:
                continue
            
            mesh_obj = {
                'vertices': mesh.vertices.tolist(),
                'faces': mesh.faces.tolist(),
                'color': cell3D.color,        # Tuple (R, G, B)
                'name': f'cell_{cell_idx}_t{t}'
            }
            
            if t not in mesh_frames_dict:
                for i in range (t):         #These three lines make sure that the dictionary keys are in order.
                    if i not in mesh_frames_dict:
                        mesh_frames_dict[i] = []
                mesh_frames_dict[t] = []

            mesh_frames_dict[t].append(mesh_obj)

    # Save to .pkl file
    
    with open(output_path, 'wb') as f:
        f.write(b"MESH\n")
        pickle.dump(mesh_frames_dict, f)


    print(f"Exported solid mesh data to {output_path}")
    return mesh_frames_dict
"""
structure for tracer data:

result = {tp1: [slice_dict], tp1: [slice_dict]}

slice_dict = {color: all_tracers}

all_tracers = [trac1, trac2, ....]

tracer = [[x1, y1], [x2, y2], ...]
"""
def export_tracers(cells3D, output_path):
    tracers = {}

    for cell_obj in cells3D:
        c_color = cell_obj.color
        #Altering the color of the tracer:
        R = c_color[0]
        G = c_color[1]
        B = c_color[2]
        """
        if (R<G and R<B):
            R = (R+64)%256
        elif (G<B):
            G = (G+64)%256
        else:
            B = (B+64)%256
        """
        
        col = (R,G,B)

        positions = copy.deepcopy(get_positions(cell_obj))

        positions = [i for i in positions if i != None]

        if col in tracers.keys():
            tracers[col].append(positions)
        else:
            tracers[col] = [positions]
    
    """
    res = {}
    for tp in range (num_tps):
        res[tp] = [slice_dict]
    """
    
    with open(output_path, 'wb') as f:
        f.write(b"TRACER\n")
        pickle.dump(tracers, f)
    
    return(tracers)



if __name__ == '__main__':
    if input("Match cells? (y/n)").strip().lower() == "y":
        import get_matched_cells
        get_matched_cells.get_cells3D(path = "C:/Users/tajre/OneDrive/Desktop/Amy's Animations/v2 Anisha combined.pkl",
                                    colors = [(255,0,0), (0,255,0), (0,255,255), (255,0,255),
                                              (60, 115, 0), (230, 180, 0), (255, 150, 150),
                                              (180, 180, 180), (100, 50, 255), (0, 0, 175),
                                              (0, 100, 200), (200, 100, 200), (150, 200, 255),
                                              (30, 70, 0), (255, 0, 100), (150, 70, 50),
                                              (200, 150, 100), (255, 50, 0), (0, 85, 0),
                                              (250, 150, 100)],
                                    output_path = "C:/Users/tajre/OneDrive/Desktop/Amy Unprocessed/working_matched_cells.pkl",
                                    tp_path = "C:/Users/tajre/OneDrive/Desktop/Amy Unprocessed/working_matched_cells_tp_num.pkl")


    with open("C:/Users/tajre/OneDrive/Desktop/Amy Unprocessed/working_matched_cells.pkl", "rb") as f:
        cells3D = pickle.load(f)

    with open("C:/Users/tajre/OneDrive/Desktop/Amy Unprocessed/working_matched_cells_tp_num.pkl", "rb") as f:
        num_tps = pickle.load(f)

    ##-----------------------------------------------------------
    print("Tracers")
    export_tracers(cells3D=cells3D, output_path="C:/Users/tajre/OneDrive/Desktop/Amy's Animations/v2 Anisha_tracers.pkl")
    print("CSV data")
    export_csv_data(cells3D=cells3D, output_path = "v2 Anisha quant data.csv")
    print("Meshes")
    export_solid_meshs(cells3D=cells3D, output_path="C:/Users/tajre/OneDrive/Desktop/Amy's Animations/v3 Anisha_solids.pkl")