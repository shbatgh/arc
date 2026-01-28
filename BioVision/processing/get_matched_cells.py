import pickled_animation_cell_matching
import copy
import pickle


#Filtering Cell3D objects, in case a spec or accidental line was picked up
def cell_filter(cell3D):
    max_outlines = []
    for single_tp_cell in cell3D.cells_list:
        max_outlines.append(max([len(outline) for outline in single_tp_cell.outlines]))
    return(max(max_outlines)>10)  #Numer chosen arbitrarily


def get_cells3D(path, colors, output_path, tp_path):
    print("Matching stacks")
    all_raw_cells = []
    for col in colors:
        print(col, end = " ")
        cur_cells = pickled_animation_cell_matching.get_raw_cell_data(path = path, color = col)
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
        print(col, end = " ")
        cells3D += pickled_animation_cell_matching.compute_animation(copy.deepcopy(all_raw_cells), col)

    print("\nNumber of cells before filter: ", len(cells3D))
    scrap_cells = [cell for cell in cells3D if not cell_filter(cell)]
    cells3D = [cell for cell in cells3D if cell_filter(cell)]
    print("After filter: ", len(cells3D))
    for scrap in scrap_cells:
        print("Scrap cell, ", scrap.color, end = " ")


    with open(output_path, 'wb') as f:
        pickle.dump(cells3D, f)
    with open(tp_path, 'wb') as f:
        pickle.dump(num_tps, f)