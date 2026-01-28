"""
This program combines two .pkl animations into one.
"""
import pickle

def get_data(file_path):
    with open(file_path, "rb") as f:
        # skip header line
        header = f.readline()
        parsed_data = pickle.load(f)

    return header, parsed_data

def combine_anims(first_path, second_path):
    header1, first_dict = get_data(first_path)
    header2, second_dict = get_data(second_path)
    print(header1, header2)
    if ("WIREFRAME" not in str(header1)) or ("WIREFRAME" not in str(header2)):
        print("Incorrect .pkl file entered. Must be wireframe anims")
    
    result = {}
    cur_tp = 0
    for stack_list in first_dict.values():
        result[cur_tp] = stack_list
        cur_tp += 1
    for stack_list in second_dict.values():
        result[cur_tp] = stack_list
        cur_tp += 1
    
    print("Created combined animation with " + str(len(result.keys())) + " tps.")
    print("Final tp: ", cur_tp)
    return(result)
    


def export_result(result, output_path):
    with open(output_path, 'wb') as f:
        f.write(b"WIREFRAME\n")
        pickle.dump(result, f)


if __name__ == '__main__':
    result = combine_anims(first_path = "C:/Users/tajre/OneDrive/Desktop/Amy's Animations/v2 Anisha PNG.pkl",
                           second_path = "C:/Users/tajre/OneDrive/Desktop/Amy's Animations/v2 Anisha SVG.pkl")
    export_result(result, "C:/Users/tajre/OneDrive/Desktop/Amy's Animations/v2 Anisha combined.pkl")