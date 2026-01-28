print("Importing GUI essentials...")
import os
import tkinter as tk
from tkinter import filedialog, messagebox
import matplotlib.pyplot as plt

print("Importing data calculation essentials...")
import shutil
import glob
import numpy as np
import cv2

print("Importing Cellpose...")
from cellpose import models, io
from cellpose.models import CellposeModel

print("You should see a pop-up!")



#----------Working Functions

def lexo_rename(path, file_or_folder, name_length):     #DON'T WORRY ABOUT THIS FUNCTION
    if file_or_folder == "file":
        items = [f.path for f in os.scandir(path) if f.is_file()]
    elif file_or_folder == "folder":
        items = [f.path for f in os.scandir(path) if f.is_dir()]
    else:
        print("Lexographic Naming Error: file_or_folder not inputted correctly")
        return()
    
    if name_length == 'auto':
        name_length = max([len(os.path.basename(os.path.normpath(item))) for item in items])
    
    for cur_item in items:
        cur_name = str(os.path.basename(os.path.normpath(cur_item)))
        new_name = list(cur_name)
        if len(new_name) >= name_length:
            continue
        for i in range(len(new_name)):
            cur_char = new_name[i]
            if cur_char.isnumeric():
                for j in range (name_length-len(new_name)):
                    new_name.insert(i, '0')
                break
        new_name = ''.join(new_name)
        os.rename(os.path.normpath(path)+'/'+cur_name, os.path.normpath(path)+'/'+new_name)


def copy_folder(source_folder, dest_folder, lexo_naming):       #DON'T WORRY ABOUT THIS FUNCTION
    if os.path.exists(dest_folder):
        print(f"Destination folder '{dest_folder}' already exists. Overwriting...")
        shutil.rmtree(dest_folder)  # remove it first
    shutil.copytree(source_folder, dest_folder)

    if lexo_naming:
        lexo_rename(path=dest_folder,
                    file_or_folder='folder',
                    name_length='auto') 

        for cur_tp in [f.path for f in os.scandir(dest_folder) if f.is_dir()]:
            lexo_rename(path=cur_tp,
                        file_or_folder='file',
                        name_length='auto')
    print(f"Raw data copied: '{source_folder}' to '{dest_folder}'")
    return



def segmentation_step(base_folder, path_to_models, model_type, use_gpu, blur_kernel):   #SEGMENTATION

    model_path = path_to_models + '/' + model_type + '.cp'
    # Instantiate the Cellpose model
    model = CellposeModel(gpu=use_gpu, pretrained_model=model_path)

    # Get all subfolders in the base folder
    subfolders = [os.path.join(base_folder, d) for d in os.listdir(base_folder) if os.path.isdir(os.path.join(base_folder, d))]

    # Process each subfolder
    for subfolder in subfolders:
        # Get list of all TIFF images in the subfolder
        image_files = glob.glob(os.path.join(subfolder, '*.tif'))
        
        for img_file in image_files:
            # Read the image using cellpose's io.imread (supports many image formats)
            img = io.imread(img_file)

            # Convert grayscale images to RGB if needed
            if img.ndim == 2:
                img = np.stack([img] * 3, axis=-1)
            elif img.ndim == 3 and img.shape[2] == 1:
                img = np.concatenate([img] * 3, axis=2)
        
            # Apply Gaussian blurring to the image before segmentation
            # Adjust the kernel size (5,5) and sigma value (0) as needed
            img_blurred = cv2.GaussianBlur(img, blur_kernel, 0)
        
            # For RGB images, using channels=[0,0] tells Cellpose to use the entire image
            channels = [0, 0]
        
            # Run the segmentation using Cellpose on the blurred image
            masks, flows, styles= model.eval(img_blurred, channels=channels)
        
            # Save the segmentation results in a dictionary (the 'masks' key is used by the filtering cell)
            seg_data = {'masks': masks, 'flows': flows, 'styles': styles}
        
            # Construct the segmentation file name (e.g., 'image_seg.npy')
            base_name = os.path.splitext(os.path.basename(img_file))[0]
            seg_file = os.path.join(subfolder, base_name + '_seg.npy')
        
            np.save(seg_file, seg_data)
            print(f"Segmented {base_name} in folder {os.path.basename(subfolder)} and saved to {seg_file}.")




def cell_iso_step(base_input_folder, output_folder_images, output_folder_outlines, lower_thresh, upper_thresh, color_pixel_ratio_threshold):    #CELL ISOLATION
    os.makedirs(output_folder_images, exist_ok=True)
    os.makedirs(output_folder_outlines, exist_ok=True)
    segmentation_files = glob.glob(os.path.join(base_input_folder, '**', '*_seg.npy'), recursive=True)

    # -------------------------------
    # Process each file pair in the folder tree
    # -------------------------------
    for seg_file in segmentation_files:
        # Determine the base name (e.g., "image_seg.npy" -> "image")
        base_name = os.path.basename(seg_file).replace('_seg.npy', '')
        
        # The corresponding image is assumed to be in the same folder with a .tif extension
        img_file = os.path.join(os.path.dirname(seg_file), base_name + '.tif')
        
        # Check if the corresponding image file exists
        if not os.path.exists(img_file):
            print(f"Image file {img_file} not found for segmentation file {seg_file}. Skipping. THIS SHOULD NOT HAPPEN.")
            continue

        # Determine subfolder relative to the base_input_folder for output organization
        subfolder = os.path.relpath(os.path.dirname(seg_file), base_input_folder)
        out_img_folder = os.path.join(output_folder_images, subfolder)
        out_outline_folder = os.path.join(output_folder_outlines, subfolder)
        os.makedirs(out_img_folder, exist_ok=True)
        os.makedirs(out_outline_folder, exist_ok=True)
        
        print(f"Processing {base_name} in folder {subfolder}...")

        # -------------------------------
        # Part 1: Load data and build the mask dictionary
        # -------------------------------
        dat = np.load(seg_file, allow_pickle=True).item()
        img = io.imread(img_file)

        # Ensure the image is in RGB (if grayscale, convert it)
        if img.ndim == 2 or (img.ndim == 3 and img.shape[2] == 1):
            img = np.stack([img.squeeze()] * 3, axis=-1)

        masks = dat['masks']

        # Create a dictionary: key -> tuple of (y,x) coordinates for the mask pixels,
        # value -> average RGB value (for visualization if desired)
        mask_dict = {}
        labels = np.unique(masks)
        for label in labels:
            if label == 0:  # Skip background
                continue
            cell_mask = masks == label
            coords = np.argwhere(cell_mask)
            coords_tuple = tuple(map(tuple, coords))
            avg_rgb = np.mean(img[cell_mask], axis=0)
            mask_dict[coords_tuple] = avg_rgb

        # -------------------------------
        # Part 2: Filter cells using HSV thresholds
        # -------------------------------
        # Convert the image from RGB to HSV
        hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
        # Create a binary mask for colored regions
        hsv_color_mask = cv2.inRange(hsv, lower_thresh, upper_thresh)

        filtered_dict = {}
        for coords, avg_rgb in mask_dict.items():
            coords_array = np.array(coords)  # shape (N, 2)
            # Extract the colored mask values for the cell's pixels
            col_vals = hsv_color_mask[coords_array[:, 0], coords_array[:, 1]]
            ratio_col = np.sum(col_vals == 255) / len(col_vals)
            if ratio_col >= color_pixel_ratio_threshold:
                filtered_dict[coords] = avg_rgb

        # -------------------------------
        # Part 3: Create a black background with just the green cells and save the image
        # -------------------------------
        # Create a black background image (all zeros)
        iso_cells_image = np.zeros(img.shape, dtype=np.uint8)
        
        # Set the green cells to green color (0, 255, 0) on the black background
        for coords in filtered_dict.keys():
            coords_array = np.array(coords)
            # Use a pure green color for all cells
            iso_cells_image[coords_array[:, 0], coords_array[:, 1]] = [255, 255, 255]  # RGB for green

        # Save the green cells image to the output folder (preserving subfolder structure)
        output_iso_cells_file = os.path.join(out_img_folder, base_name + '_iso_cells.png')
        
        # Setup the figure with tight layout and no edge padding
        plt.figure(figsize=(10, 10))
        plt.subplots_adjust(left=0, right=1, top=1, bottom=0)  # Remove internal padding
        plt.imshow(iso_cells_image)
        plt.axis('off')  # Turn off axis
        
        # Save with tight bounding box, no padding, and black background
        plt.savefig(output_iso_cells_file, 
                    bbox_inches='tight',  # Remove any extra whitespace
                    pad_inches=0,         # Remove all padding
                    facecolor='black',    # Make figure background black
                    dpi=300)              # Higher DPI for better quality
        plt.close()

        # -------------------------------
        # Part 4: Extract cell outlines and write to file
        # -------------------------------
        outline_file = os.path.join(out_outline_folder, base_name + '_outlines.txt')
        with open(outline_file, "w") as f:
            for coords in filtered_dict.keys():
                # Create a binary image for this cell mask
                cell_mask_img = np.zeros(masks.shape, dtype=np.uint8)
                coords_np = np.array(coords)
                cell_mask_img[coords_np[:, 0], coords_np[:, 1]] = 255

                # Find contours; using RETR_EXTERNAL to get only the outer boundary
                contours, _ = cv2.findContours(cell_mask_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if len(contours) == 0:
                    continue

                # Choose the largest contour (in case there are multiple)
                largest_contour = max(contours, key=cv2.contourArea)
                largest_contour = largest_contour.squeeze()
                # Ensure the contour is 2D (in case it's only a single point)
                if largest_contour.ndim == 1:
                    largest_contour = np.expand_dims(largest_contour, axis=0)

                # Format the contour as "x,y,x,y,..." (note: OpenCV contours are in (x,y) order)
                coord_pairs = [f"{pt[0]},{pt[1]}" for pt in largest_contour]
                outline_str = ",".join(coord_pairs)
                f.write(outline_str + "\n")

        print(f"Finished processing {base_name} in folder {subfolder}.")
        print(f" - Isolated cells image saved to: {output_iso_cells_file}")
        print(f" - Outlines saved to: {outline_file}")





# GUI starts here

def run():
    input_folder = input_var.get()
    seg_out = seg_out_var.get()
    iso_masks_out = iso_masks_out_var.get()
    iso_outlines_out = iso_outlines_out_var.get()

    model_type = model_type_var.get()
    path_to_models = path_to_models_var.get()
    use_gpu = gpu_var.get()
    lexo_naming = lexo_rename_var.get()
    blur_kernel = blur_kernel_var.get()
    color_ratio_threshold = threshold_var.get()

    if not input_folder:
        messagebox.showerror("Error", "Please select an input folder.")
        return

    try:
        blur_kernel_tuple = tuple(map(int, blur_kernel.strip('()').split(',')))
        if len(blur_kernel_tuple) != 2:
            raise ValueError
        
    except:
        messagebox.showerror("Error", "Blur kernel must be like (5,5).")
        return

    hsv_lower_tup = (0, 0, 0)
    hsv_upper_tup = (255, 255, 255)
    if iso_enabled_var.get():
        try:
            hsv_lower_tup = tuple(map(int, hsv_lower_var.get().strip('()').split(',')))
            hsv_upper_tup = tuple(map(int, hsv_upper_var.get().strip('()').split(',')))
            if len(hsv_lower_tup) != 3 or len(hsv_upper_tup) != 3:
                raise ValueError
        except:
            messagebox.showerror("Error", "HSV bounds must be (H,S,V) like (0,0,0).")
            return
        
    
    #THIS IS WHERE THE METHODS ARE CALLED
    copy_folder(input_folder, seg_out, lexo_naming) #Creates a copy of the raw data so that we don't mess with the original
    
    segmentation_step(seg_out, path_to_models, model_type, use_gpu, blur_kernel_tuple) #Does all the segmentations

    if iso_enabled_var.get(): #Cell isolation if cell isolation is enabled
        cell_iso_step(base_input_folder = seg_out,
                      output_folder_images = iso_masks_out,
                      output_folder_outlines = iso_outlines_out,
                      lower_thresh = hsv_lower_tup,
                      upper_thresh = hsv_upper_tup,
                      color_pixel_ratio_threshold = color_ratio_threshold)
    else:
        cell_iso_step(base_input_folder = seg_out,
                      output_folder_images = iso_masks_out,
                      output_folder_outlines = iso_outlines_out,
                      lower_thresh = (0,0,0),
                      upper_thresh = (255,255,255),
                      color_pixel_ratio_threshold = color_ratio_threshold)








def browse_folder(var):
    folder = filedialog.askdirectory()
    if folder:
        var.set(folder)

def toggle_advanced():
    if advanced_frame.winfo_viewable():
        advanced_frame.grid_remove()
        toggle_btn.config(text="Show Advanced Options")
    else:
        advanced_frame.grid()
        toggle_btn.config(text="Hide Advanced Options")

def toggle_hsv():
    if iso_enabled_var.get():
        hsv_frame.grid()
        hsv_info_frame.grid()
    else:
        hsv_frame.grid_remove()
        hsv_info_frame.grid_remove()

# GUI Layout
root = tk.Tk()
root.title("Cell Segmentation GUI")

input_var = tk.StringVar()
seg_out_var = tk.StringVar(value="segmentation_data")

lexo_rename_var = tk.BooleanVar(value=True)
gpu_var = tk.BooleanVar(value=True)
model_type_var = tk.StringVar(value="cyto3")
path_to_models_var = tk.StringVar(value=os.path.expanduser("~/.cellpose/models"))
blur_kernel_var = tk.StringVar(value="(5,5)")

iso_enabled_var = tk.BooleanVar(value=False)
hsv_lower_var = tk.StringVar(value="(40, 45, 45)")
hsv_upper_var = tk.StringVar(value="(80,255,255)")
threshold_var = tk.DoubleVar(value=0.5)

iso_masks_out_var = tk.StringVar(value="isolated_masks")
iso_outlines_out_var = tk.StringVar(value="isolated_outlines")






def add_row(parent, label, var, row, browse=False):
    tk.Label(parent, text=label).grid(row=row, column=0, sticky='w')
    tk.Entry(parent, textvariable=var, width=40).grid(row=row, column=1)
    if browse:
        tk.Button(parent, text="Browse", command=lambda: browse_folder(var)).grid(row=row, column=2)

add_row(root, "Input Folder", input_var, 0, browse=True)
tk.Label(root, text="Model Type").grid(row=1, column=0, sticky='w')
tk.OptionMenu(root, model_type_var, "cyto3", "cyto", "nuclei").grid(row=1, column=1, sticky='w')
tk.Checkbutton(root, text="Use GPU", variable=gpu_var).grid(row=2, column=1, sticky='w')




# HSV toggle
tk.Checkbutton(root, text="Enable Cell Isolation (HSV Bounds)", variable=iso_enabled_var, command=toggle_hsv).grid(row=3, column=1, sticky='w')
hsv_frame = tk.Frame(root)
hsv_frame.grid(row=4, column=0, columnspan=3, sticky='w')
hsv_frame.grid_remove()
add_row(hsv_frame, "HSV Lower Bound (H,S,V)", hsv_lower_var, 0)
add_row(hsv_frame, "HSV Upper Bound (H,S,V)", hsv_upper_var, 1)

threshold_label = tk.Label(hsv_frame, text="Color Pixel Ratio Threshold")   # Threshold slider
threshold_slider = tk.Scale(hsv_frame, variable=threshold_var, from_=0.00, to=1.00, resolution=0.01, orient='horizontal', length=200)
threshold_label.grid(row=2, column=0, sticky='w')
threshold_slider.grid(row=2, column=1)


# HSV info frame
hsv_info_frame = tk.Frame(root)
hsv_info_frame.grid(row=5, column=0, columnspan=3, sticky='w')
hsv_info_frame.grid_remove()
tk.Label(hsv_info_frame, text="\nCommon HSV Thresholds:").grid(row=0, column=0, sticky='w')
tk.Label(hsv_info_frame, text="Green: (40, 45, 45) to (80, 255, 255)").grid(row=1, column=0, sticky='w')
tk.Label(hsv_info_frame, text="Red: (0, 150, 50) to (12, 255, 255)").grid(row=2, column=0, sticky='w')



# Advanced options
toggle_btn = tk.Button(root, text="Show Advanced Options", command=toggle_advanced)
toggle_btn.grid(row=6, column=1, sticky='w')

advanced_frame = tk.Frame(root)
advanced_frame.grid(row=7, column=0, columnspan=3, sticky='w', pady=(5, 10))
advanced_frame.grid_remove()

add_row(advanced_frame, "Segmentation Output Folder", seg_out_var, 0)
add_row(advanced_frame, "Isolated Masks Output Folder", iso_masks_out_var, 1)
add_row(advanced_frame, "Isolation Outlines Output Folder", iso_outlines_out_var, 2)
add_row(advanced_frame, "Blur Kernel Size (tuple)", blur_kernel_var, 3)
add_row(advanced_frame, "Model Path", path_to_models_var, 4, browse=True)

tk.Checkbutton(advanced_frame, text="Lexographically Rename", variable=lexo_rename_var).grid(row=7, column=1, sticky='w')


tk.Button(root, text="Run", command=run).grid(row=8, column=1, pady=10)

root.mainloop()


"""
pyinstaller Cell_Iso_GUI.py --onefile --noconfirm ^
--collect-all imagecodecs ^
--add-data "%USERPROFILE%\.cellpose\models;cellpose\models"
"""