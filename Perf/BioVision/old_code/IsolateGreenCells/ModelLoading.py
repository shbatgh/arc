import numpy as np
from cellpose import models, plot
import imageio
import matplotlib.pyplot as plt

print(models.MODEL_DIR)

# Replace "your_model_name" with the name of your model file (no file extension)
model_path = 'cyto3'  # This should match the filename in ~/.cellpose/models/

model = models.CellposeModel(pretrained_model=model_path)

image_path = '7.tif'
image = imageio.imread(image_path)

masks, flows, styles = model.eval(
    image, 
    diameter=None,
    channels=[0, 0]
)

print("Number of detected masks:", np.unique(masks).shape[0] - 1)

fig = plt.figure(figsize=(5,5))
plot.show_segmentation(fig, image, masks, flows[0], channels=[0,0])
plt.show()