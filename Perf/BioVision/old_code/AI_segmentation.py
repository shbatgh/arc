import numpy as np
from cellpose import core, io, models
from cellpose.io import save_masks

import os
import lexographic_renaming   #Python file should be in the same folder

#import inspect
print("AI imports done")


def check_dir_exists(name):
   return(os.path.isdir(name))


def run_AI_segmentation_model(path_to_timepoints, model_path, channels, segmentation_parameters, output_dir):    #os.getcwd() for output_dir
   if check_dir_exists(output_dir):
      print("Output directory already exists and may not be empty. Delete it or change the output directory to run.")
      return None
   os.makedirs(output_dir)

   folders = [f.path for f in os.scandir(path_to_timepoints) if f.is_dir()]
   
   model = models.CellposeModel(gpu=True,
                                pretrained_model=model_path)       # declare model
   

   diameter, flow_threshold, cellprob_threshold = segmentation_parameters[0], segmentation_parameters[1], segmentation_parameters[2]

   diameter = model.diam_labels if diameter==0 else diameter       # use model diameter if user diameter is 0
   
   seg_channel, second_seg_channel = channels[0], channels[1]

   if seg_channel == "Grayscale":      # Here we match the channel to number
      chan = 0
   elif seg_channel == "Blue":
      chan = 3
   elif seg_channel == "Green":
      chan = 2
   elif seg_channel == "Red":
      chan = 1

   if second_seg_channel == "Blue":
      chan2 = 3
   elif second_seg_channel == "Green":
      chan2 = 2
   elif second_seg_channel == "Red":
      chan2 = 1
   elif second_seg_channel == "None":
      chan2 = 0

   use_GPU = core.use_gpu()
   yn = ['NO', 'YES']
   print(f'>>> GPU activated? {yn[use_GPU]}')


   print("\nSegmenting directory: ")
   for folder_num in range(len(folders)):
      print('\n'+str(folder_num+1), end=' ')

      cur_dir = folders[folder_num]
      print("Current directory:", cur_dir)
      files = io.get_image_files(cur_dir, '_masks')        # gets image files in cur_dir (ignoring image files ending in _masks)
      images = [io.imread(f) for f in files]
      
      masks, flows, styles = model.eval(images,
                                       channels=[chan, chan2],
                                       diameter=diameter,
                                       flow_threshold=flow_threshold,
                                       cellprob_threshold=cellprob_threshold)     # run model on test images

      io.masks_flows_to_seg(images, 
                           masks,
                           flows,
                           files,
                           channels=[chan, chan2],
                           diams=diameter*np.ones(len(masks)))
       
       #file_location = inspect.getfile(save_masks)
       #print("File Location:", file_location)

      save_dir_name = output_dir + '/seg_t' + str(folder_num+1)        #e.g. output_dir/t3
      io.save_masks(images,
                  masks,
                  flows,
                  files,
                  channels=[chan, chan2],
                  png=False, # save masks as PNGs and save example image
                  tif=False, # save masks as TIFFs
                  save_txt=True, # save txt outlines for ImageJ
                  save_flows=False, # save flows as TIFFs
                  save_outlines=True, # save outlines as TIFFs
                  save_mpl=False, # make matplotlib fig to view (WARNING: SLOW W/ LARGE IMAGES)
                  in_folders=True,
                  savedir = save_dir_name)
      
      segmented_tps_for_renaming = [ f.path for f in os.scandir(output_dir) if f.is_dir() ]        #Lexographic renaming
      for tp in segmented_tps_for_renaming:           #renaming the files
         outlines_folder = os.path.normpath(tp) + '/outlines'  
         txt_outlines_folder = os.path.normpath(tp) + '/txt_outlines'
         lexographic_renaming.rename(path = outlines_folder,
                                     file_or_folder = 'file',
                                     name_length = 'auto')
         lexographic_renaming.rename(path = txt_outlines_folder,
                                     file_or_folder = 'file',
                                     name_length = 'auto')

      lexographic_renaming.rename(path=output_dir, #Renaming the folders
                                  file_or_folder='folder',
                                  name_length='auto')



      
"""
run_AI_segmentation_model(folders=["C:/Users/areil/Desktop/Terra/Unprocessed Animations/Germarium6 raw data/t"+str(i) for i in range(1, 22)],   #path to images
                          model_path="C:/Users/areil/Desktop/Terra/human_in_the_loop/train/models/CP_tissuenet",     #path to model
                          channels=["Green", "Red"],
                          segmentation_parameters=[30, 0.3, 0],
                          output_dir="C:/Users/areil/Desktop/Terra/Programs/Program Outputs/test_Sid's Germarium AI segmentations")
"""

#model_path = "C:/Users/areil/Desktop/Terra/human_in_the_loop/train/models/CP_tissuenet"

#Path to images:
#dir = "C:/Users/areil/Desktop/Sam Segmentation/test_images"

#Channel Parameters:
#seg_channel = "Green" #["Grayscale", "Blue", "Green", "Red"]
#If you have a secondary channel that can be used, for instance nuclei, choose it here:
#second_seg_channel = "Red" #["None", "Blue", "Green", "Red"]

#Segmentation parameters:

#Diameter of cells (set to zero to use diameter from training set):
#diameter =  30
#Threshold on flow error to accept a mask (set higher to get more cells, e.g. in range from (0.1, 3.0), OR set to 0.0 to turn off so no cells discarded):
#flow_threshold = 0.4        #min:0.0, max:3.0
#@markdown threshold on cellprob output to seed cell masks (set lower to include more pixels or higher to include fewer, e.g. in range from (-6, 6)):
#cellprob_threshold=0        #min:-6, max:6