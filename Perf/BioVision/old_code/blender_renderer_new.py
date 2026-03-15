"""Notes

Open as a text file in blender, and run. <-- Maybe .py file
Renders the outlines in blender


Common paths for convenience

"C:/Users/areil/Desktop/Terra/Programs/Program Outputs/test2-A1 AI formatted data.txt"              <Change test number
"C:/Users/areil/Desktop/Terra/Programs/Program Outputs/test2-A1 manual formatted data.txt"          ^^^

C:/Users/areil/Desktop/Terra/Visualization_Step/blender_animation1.txt
"""

import bpy
import ast
import time

time_start = time.time()

#print("imports done", time.time()-time_start)

#Change variables below
data_file_path = ""     #Remember to use backslashes instead of forward slashes
color_list = [(255,0,0), (0,255,0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255), (255, 100, 0)]
frames_per_time_point = 10
start_end_timepoints = [1, 10]
#---------------------



def create_color_dict(color_list):
    color_dict = {}
    for color in color_list:
        converted_rgb = (color[0]/255, color[1]/255, color[2]/255, 1)
        cur_var = bpy.data.materials.new(str(color))
        cur_var.use_nodes = True
        principled = cur_var.node_tree.nodes['Principled BSDF']
        principled.inputs['Base Color'].default_value = converted_rgb
        color_dict[color] = cur_var
    return(color_dict)




def add_curve(frames_dict, color_dict, coords, name, slice, frame, color):
    global cur_frame_col
    curveData = bpy.data.curves.new('my_curve', type='CURVE')
    curveData.dimensions = '3D'
    curveData.resolution_u = 1     # Preview U
    curveData.fill_mode = 'FULL' # Fill Mode ==> Full
    curveData.bevel_depth      = 0.5   # Bevel Depth
    curveData.bevel_resolution = 1      # Bevel Resolution

    polyline = curveData.splines.new('NURBS')
    polyline.points.add(len(coords))
    for i, coord in enumerate(coords):
        x,y = coord
        z = frames_dict[frame].index(slice)*(3/0.198)/2    #Multiply by 3/0.198????
        polyline.points[i].co = (x, y, z, 1)
    
    curveOB = bpy.data.objects.new(name, curveData)         # create Object
    curveOB.data.materials.append(color_dict[color])        #add texture (color)
    cur_frame_col.objects.link(curveOB)                     #add to collection
    


    #Animation keyframes

def get_data(data_file_path):
    with open(data_file_path, 'r') as f:   #blender_format_adjusted or blender_format
        data = f.read()

    frames_dict = ast.literal_eval(data)
    return(frames_dict)


def render():
    global cur_frame_col
    valid_frames = [t for t in range(start_end_timepoints[0]-1, start_end_timepoints[1])]

    color_dict = create_color_dict(color_list)
    #print("color dict done", time.time()-time_start)

    frames_dict = get_data(data_file_path)
    #print("Fetched data", time.time()-time_start)

    for frame_num in frames_dict.keys():
        if int(frame_num) not in valid_frames:
            continue
        cur_frame_col = bpy.data.collections.new('timepoint'+str(frame_num+1))
        scene_col = bpy.context.scene.collection
        scene_col.children.link(cur_frame_col)
        cur_frame_col.hide_viewport = True

        for slice in frames_dict[frame_num]:
            for color in slice.keys():
                if color not in color_list:
                    continue
                for group in slice[color]:
                    name = 't'+str(frame_num+1)+'_s'+str(frames_dict[frame_num].index(slice)+1)+'_c'+str(color)+'_g'+str(slice[color].index(group))        #frame, slice, color, group
                    add_curve(frames_dict=frames_dict,
                              color_dict= color_dict,
                              coords=group,
                              name=name,
                              slice=slice,
                              frame=frame_num,
                              color=color)
    print("Rendered Curves", time.time()-time_start)



def hide_color(hide):
    R = bpy.context.scene.R_val
    G = bpy.context.scene.G_val
    B = bpy.context.scene.B_val
    color = (R, G, B)
    for ob in bpy.data.objects:
        if str(color) in ob.name:
            ob.hide_set(hide)
#hide_color(color=(255,0,0), hide=True)




handler_initiated_marker = False
col_timepoints = []
num_frames = 0


def my_handler(scene):
    new_frame = scene.frame_current
    new_frame = int(new_frame*0.1)
    print("frame:", new_frame)
    if col_timepoints[new_frame].hide_viewport == True:
        for cur_frame in col_timepoints:
            cur_frame.hide_viewport = True
        col_timepoints[new_frame].hide_viewport = False


class MESH_OT_a_hide_color(bpy.types.Operator):
    bl_idname = "mesh.a_hide_color"
    bl_label = "Hide Color"
    
    def execute(self, context):
        hide_color(True)
        return{"FINISHED"}


class MESH_OT_a_show_color(bpy.types.Operator):
    bl_idname = "mesh.a_show_color"
    bl_label = "Show Color"
    
    def execute(self, context):
        hide_color(False)
        return{"FINISHED"}
    









class MESH_OT_a_change_path(bpy.types.Operator):
    """Changes data_file_path for rendering"""
    bl_idname = "mesh.a_change_path"
    bl_label = "Change Path"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    """@classmethod
    def poll(cls, context):
        return context.object is not None"""

    def execute(self, context):
        global data_file_path
        data_file_path = self.filepath
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class MESH_OT_a_render(bpy.types.Operator):     #
    bl_idname = "mesh.a_render"
    bl_label = "Render Animation"
    
    def execute(self, context):
        render()
        return{"FINISHED"}


class MESH_OT_a_animate(bpy.types.Operator):     #Does not work for multiple renderings stacked ontop of eachother. Make delete function too
    bl_idname = "mesh.a_animate"
    bl_label = "Animate Timepoints"
    
    def execute(self, context):
        global handler_initiated_marker
        if handler_initiated_marker:
            return{"FINISHED"}
        
        global col_timepoints, num_frames
        col_timepoints = [bpy.data.collections['timepoint'+str(t)] for t in range(start_end_timepoints[0], start_end_timepoints[1]+1)]
        num_frames = len(col_timepoints)
        if num_frames>0:
            handler_initiated_marker = True
        print(num_frames, col_timepoints)

        bpy.app.handlers.frame_change_pre.append(my_handler)
        return{"FINISHED"}






class VIEW3D_PT_ColorPanel(bpy.types.Panel):
    bl_label = "Show/Hide Color"
    bl_category = "Show/Hide Color"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    def draw(self, context):
        row = self.layout.row()
        row.operator("MESH_OT_a_hide_color", text ="Hide Color")   #Function is the first argument
        row.operator("MESH_OT_a_show_color", text ="Show Color")
        row.operator("MESH_OT_a_animate", text ="Animate Timpoints")
        row.operator("MESH_OT_a_render", text ="Render")
        row.operator("MESH_OT_a_change_path", text ="Change Path")
        
        
        layout = self.layout
        layout.separator()
        scn = context.scene
        layout.prop(scn, 'R_val')
        layout.prop(scn, 'G_val')
        layout.prop(scn, 'B_val')
        



classes = [VIEW3D_PT_ColorPanel, MESH_OT_a_hide_color, MESH_OT_a_show_color, MESH_OT_a_animate, MESH_OT_a_render, MESH_OT_a_change_path]
def register():
    bpy.types.Scene.R_val = bpy.props.IntProperty(name = "R", description = "Enter a float", min = 0, max = 255)
    bpy.types.Scene.G_val = bpy.props.IntProperty(name = "G", description = "Enter a float", min = 0, max = 255)
    bpy.types.Scene.B_val = bpy.props.IntProperty(name = "B", description = "Enter a float", min = 0, max = 255)

    
    
    for cur_class in classes:
        bpy.utils.register_class(cur_class)


def unregister():
    for cur_class in classes:
        bpy.utils.unregister_class(cur_class)
    
register()








"""
col_timepoints = [bpy.data.collections['timepoint'+str(t)] for t in range(start_end_timepoints[0], start_end_timepoints[1]+1)]
print(col_timepoints)
num_frames = len(col_timepoints)

def my_handler(scene):
    new_frame = scene.frame_current
    new_frame = int(new_frame*0.1)
    print("frame:", new_frame)
    if col_timepoints[new_frame].hide_viewport == True:
        for cur_frame in col_timepoints:
            cur_frame.hide_viewport = True
        col_timepoints[new_frame].hide_viewport = False



bpy.app.handlers.frame_change_pre.append(my_handler)
"""

