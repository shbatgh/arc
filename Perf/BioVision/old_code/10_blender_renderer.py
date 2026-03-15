"""Notes

NEW NEW Blender renderer


"""


#Making it an Add-on
bl_info = {
    "name": "3D Visualization",
    "author": "Taj Chhabra and Samuel Boccara",
    "version": (0,0,2),
    "blender": (2,80,0),
    "description": "Choose a file and render it",
    "category": "Development",
}
#    "location": "3D Viewport > Sidebar > Render File",
#-----------------------------

import bpy
import ast
import time

time_start = time.time()

#print("imports done", time.time()-time_start)
frames_per_time_point = 10




data_file_path = ""
color_dict = {}
cur_render_number = 0


#----------------------------------------------RENDERING FUNCTIONS
rendering_groups = []       #list of Rendering_Group objects. To reference different renderings
class Rendering_Group:
    def __init__(self, num):
        self.timepoint_list = []
        self.name = "rendering_group_"+str(num)
        rendering_groups.append(self)
    
    def add_timepoint(self, tp):
        self.timepoint_list.append(tp)



def add_to_color_dict(color):
    converted_rgb = (color[0]/255, color[1]/255, color[2]/255, 1)
    cur_var = bpy.data.materials.new(str(color))
    cur_var.use_nodes = True
    principled = cur_var.node_tree.nodes['Principled BSDF']
    principled.inputs['Base Color'].default_value = converted_rgb
    color_dict[color] = cur_var
    return(color_dict)

def add_curve(frames_dict, color_dict, coords, name, slice, frame, color):
    mesh_marker = False
    
    global cur_frame_col
    curveData = bpy.data.curves.new('my_curve', type='CURVE')
    curveData.dimensions = '3D'
    curveData.resolution_u = 8     # Preview U
    curveData.fill_mode = 'FULL' # Fill Mode ==> Full
    curveData.bevel_depth      = .3   # Bevel Depth
    curveData.bevel_resolution = 1      # Bevel Resolution

    polyline = curveData.splines.new('NURBS')
    polyline.points.add(len(coords)-1)
    for i, coord in enumerate(coords):
        x,y = coord[0], coord[1]
        ##--Adding this
        if len(coord) >2:
            z = coord[2]
            mesh_marker = True
            """
            verticies=[(x-0.3,y-0.3,z-0.3), (x-0.3,y+0.3,z-0.3), (x+0.3,y+0.3,z-0.3), (x+0.3,y-0.3,z-0.3), (x-0.3,y-0.3,z+0.3), (x-0.3,y+0.3,z+0.3), (x+0.3,y+0.3,z+0.3), (x+0.3,y-0.3,z+0.3)]
            edges =[]
            faces = [(0,1,2,3), (4,5,6,7), (0,4,7,3), (0,1,5,4), (1,2,6,5), (7,6,2,3)]
            new_mesh = bpy.data.meshes.new("new_mesh")
            new_mesh.from_pydata(verticies, edges, faces)
            new_mesh.update()
            new_object = bpy.data.objects.new("new_object", new_mesh)
            cur_frame_col.objects.link(new_object)
            """
        else:
            z = frames_dict[frame].index(slice)*(3/0.198)/2    #Multiply by 3/0.198????
            

        polyline.points[i].co = (x, y, z, 1)
    
    if mesh_marker:
        curveData.bevel_depth = 0.3
    curveOB = bpy.data.objects.new(name, curveData)         # create Object
    curveOB.data.materials.append(color_dict[color])        #add texture (color)
    if mesh_marker:
        curveOB.data.splines[0].order_u=3
    cur_frame_col.objects.link(curveOB)                     #add to collection
    
    #Animation keyframes

def get_data(data_file_path):
    with open(data_file_path, 'r') as f:   #blender_format_adjusted or blender_format
        data = f.read()

    frames_dict = ast.literal_eval(data)
    return(frames_dict)

def render():
    global cur_frame_col, color_dict, cur_render_number

                #Collections will be added to this to easily delete, animate tps, and so on 
    cur_render_number +=1
    cur_rendering_group = Rendering_Group(num=cur_render_number)

    cur_render_col = bpy.data.collections.new('Rendering'+str(cur_render_number))                 #Collection for each time a file is rendered. All tps are added to it
    scene_col = bpy.context.scene.collection
    scene_col.children.link(cur_render_col)
    

    #print("color dict done", time.time()-time_start)

    frames_dict = get_data(data_file_path)
    #print("Fetched data", time.time()-time_start)

    for frame_num in frames_dict.keys():
        cur_frame_col = bpy.data.collections.new('timepoint'+str(frame_num+1))
        cur_render_col.children.link(cur_frame_col)
        cur_frame_col.hide_viewport = True
        cur_rendering_group.add_timepoint(cur_frame_col)


        for slice in frames_dict[frame_num]:
            for color in slice.keys():
                if color not in color_dict.keys():
                    color_dict = add_to_color_dict(color)
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





#----------------------------------------------------UI FUNCTIONS

#---------------------------Hide/Show color
def hide_color(hide):
    R = bpy.context.scene.R_val
    G = bpy.context.scene.G_val
    B = bpy.context.scene.B_val
    color = (R, G, B)
    for ob in bpy.data.objects:
        if str(color) in ob.name:
            ob.hide_set(hide)

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
    

class VIEW3D_PT_ColorPanel(bpy.types.Panel):
    bl_label = "Show/Hide Color"
    bl_category = "Show/Hide Color"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    def draw(self, context):
        row = self.layout.row()
        row.operator("MESH_OT_a_hide_color", text ="Hide Color")   #Function is the first argument
        row.operator("MESH_OT_a_show_color", text ="Show Color")
       
        layout = self.layout
        layout.separator()
        scn = context.scene
        layout.prop(scn, 'R_val')
        layout.prop(scn, 'G_val')
        layout.prop(scn, 'B_val')




#-----------------------------Rendering Process

#handler_initiated_marker = False
tp_frames = {}          #frame: collection at timepoint
num_frames = 0
handler_activated = False

#Change later to by name
def my_handler(scene):
    new_frame = scene.frame_current
    new_frame = int(new_frame*0.1)
    #print("frame:", new_frame)
    if tp_frames[new_frame][0].hide_viewport == True:
        for cur_frame in tp_frames.values():
            for col in cur_frame:
                col.hide_viewport = True
        for col in tp_frames[new_frame]:
            col.hide_viewport = False


class MESH_OT_a_choose_path(bpy.types.Operator):
    """Changes data_file_path for rendering"""
    bl_idname = "mesh.a_choose_path"
    bl_label = "Choose path"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        global data_file_path
        data_file_path = self.filepath

        message = "Chosen path: " + str(data_file_path)
        self.report({'INFO'}, message)

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class MESH_OT_a_render(bpy.types.Operator):   
    bl_idname = "mesh.a_render"
    bl_label = "Render Animation"
    
    def execute(self, context):
        render()        #Renders, then puts into timepoints

        
        global tp_frames, num_frames, handler_activated
        #col_timepoints = 
        col_timepoints = rendering_groups[cur_render_number-1].timepoint_list           #temporary list
        num_frames = len(col_timepoints)

        for col_num in range(num_frames):            #-1 to fix indexing
            if col_num in tp_frames.keys():
                tp_frames[col_num].append(col_timepoints[col_num])
            else:
                tp_frames[col_num] = [col_timepoints[col_num]]
        print(num_frames, tp_frames)

        if not handler_activated:
            handler_activated = True
            bpy.app.handlers.frame_change_pre.append(my_handler)

        #------Render first frame, Zoom out, set last frame
        first_frame = context.scene.frame_current
        first_frame = int(first_frame*0.1)
        for col in tp_frames[first_frame]:
            col.hide_viewport = False

        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        override = {'area': area, 'region': region, 'edit_object': bpy.context.edit_object}
                        bpy.ops.view3d.view_all(override)
                        
        bpy.context.scene.frame_end = len(tp_frames.keys())*frames_per_time_point

        return{"FINISHED"}


class VIEW3D_PT_RenderPanel(bpy.types.Panel):
    bl_label = "Render File"
    bl_category = "Render File"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    def draw(self, context):
        layout = self.layout
        layout.operator("MESH_OT_a_choose_path", text ="Choose Path")
        layout.separator()
        layout.operator("MESH_OT_a_render", text ="Render")           #Note they are switched, because from the POV of the user, it gets rendered after tps are animated
        #layout.operator("MESH_OT_a_animate", text ="Render")













classes = [VIEW3D_PT_ColorPanel, MESH_OT_a_hide_color, MESH_OT_a_show_color, VIEW3D_PT_RenderPanel, MESH_OT_a_render, MESH_OT_a_choose_path]
def register():
    bpy.types.Scene.R_val = bpy.props.IntProperty(name = "R", description = "Enter a float", min = 0, max = 255)
    bpy.types.Scene.G_val = bpy.props.IntProperty(name = "G", description = "Enter a float", min = 0, max = 255)
    bpy.types.Scene.B_val = bpy.props.IntProperty(name = "B", description = "Enter a float", min = 0, max = 255)

    
    
    for cur_class in classes:
        bpy.utils.register_class(cur_class)


def unregister():
    for cur_class in classes:
        bpy.utils.unregister_class(cur_class)

if __name__ == "__main__":
    register()

#-----Shades to Material Preview
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas: # iterate through areas in current screen
        if area.type == 'VIEW_3D':
            for space in area.spaces: # iterate through spaces in current VIEW_3D area
                if space.type == 'VIEW_3D': # check if space is a 3D view
                    space.shading.type = 'MATERIAL'
                    space.clip_end = 8000



