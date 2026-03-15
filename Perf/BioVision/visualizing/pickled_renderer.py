"""
BioVision Blender Add-on

Renders WIREFRAME, MESH, TRACER, and ANIMATION .pkl files as animated 3D
scenes in Blender.  Install via Edit > Preferences > Add-ons > Install, then enable
"BioVision".

UI panels appear in the 3D Viewport sidebar (press N):
  - "Render File" tab: load a .pkl file and render it.
  - "Show/Hide Color" tab: filter objects by RGB color.

Animation uses Blender's timeline. Each biological timepoint maps to
FRAMES_PER_TIME_POINT Blender frames. A frame-change handler shows/hides
the appropriate timepoint collections automatically.

See README.md for the full pipeline overview.
"""

bl_info = {
    "name": "BioVision",
    "author": "Taj Chhabra and Samuel Boccara",
    "version": (0, 0, 5),
    "blender": (2, 80, 0),
    "description": "Load and render BioVision .pkl files as 3D animations",
    "category": "Development",
}

import bpy
import time
import pickle

# ============================================================================
#  USER CONFIGURATION
# ============================================================================

# Number of Blender frames per biological timepoint.
FRAMES_PER_TIME_POINT = 10

# Bevel depth for NURBS curves (wireframes and tracers).
# Larger values produce thicker tubes.
CURVE_DEPTH = 0.4

# Factor to scale all coordinates by (1 = no zoom).
ZOOM_IN_FACTOR = 1

# Default Z-axis scale. Biological specimens are often very thin, so
# values < 1 compress Z while values > 1 exaggerate it.
Z_SCALE_DEFAULT = 0.7

# ============================================================================
#  INTERNAL STATE
# ============================================================================

_time_start = time.time()
_data_file_path = ""
_color_dict = {}
_cur_render_number = 0
_depth = CURVE_DEPTH / ZOOM_IN_FACTOR
_scale_empty_name = "BioVision_Scale_Empty"
_rendering_groups = []
_tp_frames = {}
_num_frames = 0
_handler_activated = False
_last_tp_index = -1


# ============================================================================
#  SCALE CONTROL
# ============================================================================

def _get_or_create_scale_empty():
    """Get or create the master Empty used for Z-scale control.

    All rendered objects are parented to this Empty so that adjusting its
    Z scale uniformly scales everything.
    """
    if _scale_empty_name in bpy.data.objects:
        return bpy.data.objects[_scale_empty_name]
    empty = bpy.data.objects.new(_scale_empty_name, None)
    empty.empty_display_type = "PLAIN_AXES"
    bpy.context.scene.collection.objects.link(empty)
    empty.scale.z = bpy.context.scene.z_scale
    return empty


def _update_z_scale(self, context):
    """Callback when the Z-scale slider changes in the UI."""
    if _scale_empty_name in bpy.data.objects:
        bpy.data.objects[_scale_empty_name].scale.z = self.z_scale


# ============================================================================
#  RENDERING GROUP (tracks collections per rendering session)
# ============================================================================

class _RenderingGroup:
    """Groups Blender collections by timepoint for a single render session."""
    def __init__(self, num):
        self.timepoint_list = []
        self.name = "rendering_group_" + str(num)
        _rendering_groups.append(self)

    def add_timepoint(self, tp_collection):
        self.timepoint_list.append(tp_collection)


# ============================================================================
#  MATERIAL HELPERS
# ============================================================================

def _add_to_color_dict(color):
    """Create a Blender material for an RGB tuple and register it."""
    global _color_dict
    converted_rgb = (color[0] / 255, color[1] / 255, color[2] / 255, 1)
    mat = bpy.data.materials.new(str(color))
    mat.use_nodes = True
    principled = mat.node_tree.nodes["Principled BSDF"]
    principled.inputs["Base Color"].default_value = converted_rgb
    _color_dict[color] = mat
    return _color_dict


# ============================================================================
#  GEOMETRY CREATION
# ============================================================================

def _add_curve(frames_dict, coords, name, slice_dict, frame, color):
    """Create a NURBS curve object from 2D or 3D coordinates."""
    global _cur_frame_col
    has_z = False

    curve_data = bpy.data.curves.new("my_curve", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 1
    curve_data.fill_mode = "FULL"
    curve_data.bevel_depth = _depth
    curve_data.bevel_resolution = 1

    polyline = curve_data.splines.new("NURBS")
    polyline.points.add(len(coords) - 1)

    for i, coord in enumerate(coords):
        x, y = coord[0], coord[1]
        if len(coord) > 2:
            z = coord[2]
            has_z = True
        else:
            # Compute Z from slice position within the timepoint
            z = frames_dict[frame].index(slice_dict) * (3 / 0.198)
        polyline.points[i].co = (
            x / ZOOM_IN_FACTOR,
            y / ZOOM_IN_FACTOR,
            z / ZOOM_IN_FACTOR,
            1,
        )

    if has_z:
        curve_data.bevel_depth = _depth
        curve_data.splines[0].order_u = 3

    curve_obj = bpy.data.objects.new(name, curve_data)
    curve_obj.data.materials.append(_color_dict[color])
    _cur_frame_col.objects.link(curve_obj)
    curve_obj.parent = _get_or_create_scale_empty()


def _add_solid_mesh(vertices, faces, name, collection):
    """Create a mesh object from vertices and faces."""
    mesh_data = bpy.data.meshes.new(name)
    mesh_obj = bpy.data.objects.new(name, mesh_data)
    collection.objects.link(mesh_obj)
    mesh_data.from_pydata(vertices, [], faces)
    mesh_data.update()
    mesh_obj.parent = _get_or_create_scale_empty()
    return mesh_obj


def _expand_mesh_geometry(mesh_obj, vertex_dtype="float32"):
    """Return vertices/faces for legacy, compact, or bytes mesh payloads.

    Supported schemas:
    - Legacy: ``vertices`` / ``faces`` as nested Python lists
    - Compact: ``vertices_flat`` / ``faces_flat`` as typed arrays + shape
    - Bytes: ``vertices`` / ``faces`` as raw bytes + shape (ANIMATION pkl)

    For ANIMATION v2 pickles, ``vertex_dtype`` should be ``"float16"``.
    """
    import struct
    import numpy as np

    # Typed-array compact format (MESH pkl).
    if "vertices_flat" in mesh_obj:
        vertices_flat = mesh_obj["vertices_flat"]
        faces_flat = mesh_obj["faces_flat"]
        vertices_shape = mesh_obj["vertices_shape"]
        faces_shape = mesh_obj["faces_shape"]

        vertices = [
            tuple(vertices_flat[idx : idx + vertices_shape[1]])
            for idx in range(0, len(vertices_flat), vertices_shape[1])
        ]
        faces = [
            tuple(faces_flat[idx : idx + faces_shape[1]])
            for idx in range(0, len(faces_flat), faces_shape[1])
        ]
        return vertices, faces

    raw_verts = mesh_obj["vertices"]
    raw_faces = mesh_obj["faces"]

    # Raw bytes format (ANIMATION pkl).
    if isinstance(raw_verts, (bytes, bytearray)):
        vs = mesh_obj["vertices_shape"]
        fs = mesh_obj["faces_shape"]

        verts_np = np.frombuffer(raw_verts, dtype=vertex_dtype).reshape(vs)
        vertices = [tuple(float(c) for c in row) for row in verts_np]

        n_idx = fs[0] * fs[1]
        face_fmt = "H" if len(raw_faces) == n_idx * 2 else "I"
        fflat = struct.unpack(f"<{n_idx}{face_fmt}", raw_faces)
        faces = [
            fflat[i : i + fs[1]] for i in range(0, n_idx, fs[1])
        ]
        return vertices, faces

    # Legacy nested-list format.
    return raw_verts, raw_faces


def _add_tracer(coords, name, collection):
    """Create a NURBS curve tracing a cell's movement trajectory."""
    curve_data = bpy.data.curves.new("my_curve", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 3
    curve_data.fill_mode = "FULL"
    curve_data.bevel_depth = _depth
    curve_data.bevel_resolution = 1

    polyline = curve_data.splines.new("NURBS")
    polyline.points.add(len(coords) - 1)
    for i, coord in enumerate(coords):
        x, y, z = coord[0], coord[1], coord[2]
        polyline.points[i].co = (
            x / ZOOM_IN_FACTOR,
            y / ZOOM_IN_FACTOR,
            z / ZOOM_IN_FACTOR,
            1,
        )

    curve_obj = bpy.data.objects.new(name, curve_data)
    collection.objects.link(curve_obj)
    curve_obj.parent = _get_or_create_scale_empty()
    return curve_obj


# ============================================================================
#  DATA LOADING
# ============================================================================

def _get_data(file_path):
    """Load a .pkl file, returning (header_string, parsed_data).

    ANIMATION pickles are zlib-compressed after the header line.
    """
    import zlib

    with open(file_path, "rb") as f:
        header = f.readline()
        raw = f.read()

    header_str = header.strip().decode("utf-8", errors="ignore")
    if header_str == "ANIMATION":
        parsed_data = pickle.loads(zlib.decompress(raw))
    else:
        parsed_data = pickle.loads(raw)

    return header, parsed_data


# ============================================================================
#  RENDER DISPATCHERS
# ============================================================================

def _render_curves(frames_dict, cur_render_col, cur_rendering_group):
    """Render WIREFRAME data as NURBS curves grouped by timepoint."""
    global _color_dict, _cur_frame_col

    for frame_num in frames_dict.keys():
        _cur_frame_col = bpy.data.collections.new("timepoint" + str(frame_num + 1))
        cur_render_col.children.link(_cur_frame_col)
        _cur_frame_col.hide_viewport = True
        cur_rendering_group.add_timepoint(_cur_frame_col)

        for slice_dict in frames_dict[frame_num]:
            for color in slice_dict.keys():
                if color not in _color_dict:
                    _color_dict = _add_to_color_dict(color)
                for group_idx, group in enumerate(slice_dict[color]):
                    slice_idx = frames_dict[frame_num].index(slice_dict) + 1
                    name = (f"t{frame_num+1}_s{slice_idx}"
                            f"_c{color}_g{group_idx}")
                    _add_curve(
                        frames_dict=frames_dict,
                        coords=group,
                        name=name,
                        slice_dict=slice_dict,
                        frame=frame_num,
                        color=color,
                    )
    print("Rendered curves", time.time() - _time_start)


def _render_meshes(mesh_frames_dict, parent_collection, rendering_group):
    """Render MESH data as solid mesh objects grouped by timepoint."""
    global _color_dict

    for frame_num, mesh_objs in mesh_frames_dict.items():
        print("frame", frame_num)
        tp_collection = bpy.data.collections.new(f"timepoint_mesh_{frame_num}")
        parent_collection.children.link(tp_collection)
        tp_collection.hide_viewport = True
        rendering_group.add_timepoint(tp_collection)

        for obj in mesh_objs:
            color = obj["color"]
            if color not in _color_dict:
                _color_dict = _add_to_color_dict(color)
            vertices, faces = _expand_mesh_geometry(obj)
            mesh = _add_solid_mesh(
                vertices=vertices,
                faces=faces,
                name=obj["name"] + str(color),
                collection=tp_collection,
            )
            mesh.data.materials.append(_color_dict[color])


def _render_tracers(tracer_data, parent_collection):
    """Render TRACER data as continuous trajectory curves."""
    global _color_dict
    t_num = -1
    for color in tracer_data.keys():
        if color not in _color_dict:
            _color_dict = _add_to_color_dict(color)
        for cur_tracer in tracer_data[color]:
            t_num += 1
            tracer_obj = _add_tracer(
                coords=cur_tracer,
                name="T" + str(t_num) + " " + str(color),
                collection=parent_collection,
            )
            tracer_obj.data.materials.append(_color_dict[color])


def _render_animation(anim_data, parent_collection, rendering_group):
    """Render ANIMATION data: meshes grouped by timepoint + tracer curves.

    The ANIMATION format is cell-centric, so we first pivot to per-timepoint
    mesh lists (like MESH) and also build tracer curves from cell centers.
    """
    global _color_dict

    cells = anim_data["cells"]
    vertex_dtype = anim_data.get("vertex_dtype", "float32")

    # Build per-timepoint mesh index from cell-centric data.
    frames: dict[int, list[tuple[dict, tuple, str]]] = {}
    for cell_id, cell in cells.items():
        color = cell["color"]
        if color not in _color_dict:
            _color_dict = _add_to_color_dict(color)
        for tp, tp_data in cell["timepoints"].items():
            if tp not in frames:
                frames[tp] = []
            name = f"cell_{cell_id}_t{tp}{color}"
            frames[tp].append((tp_data, color, name))

    # Render meshes by timepoint.
    for frame_num in sorted(frames.keys()):
        tp_collection = bpy.data.collections.new(f"timepoint_anim_{frame_num}")
        parent_collection.children.link(tp_collection)
        tp_collection.hide_viewport = True
        rendering_group.add_timepoint(tp_collection)

        for tp_data, color, name in frames[frame_num]:
            vertices, faces = _expand_mesh_geometry(tp_data, vertex_dtype=vertex_dtype)
            mesh = _add_solid_mesh(
                vertices=vertices,
                faces=faces,
                name=name,
                collection=tp_collection,
            )
            mesh.data.materials.append(_color_dict[color])

    # Render tracer curves from cell center trajectories.
    tracer_collection = bpy.data.collections.new("animation_tracers")
    parent_collection.children.link(tracer_collection)
    for cell_id, cell in cells.items():
        color = cell["color"]
        centers = [
            cell["timepoints"][tp]["center"]
            for tp in sorted(cell["timepoints"].keys())
            if cell["timepoints"][tp].get("center")
        ]
        if len(centers) < 2:
            continue
        tracer_obj = _add_tracer(
            coords=centers,
            name=f"tracer_{cell_id} {color}",
            collection=tracer_collection,
        )
        tracer_obj.data.materials.append(_color_dict[color])


def _render():
    """Main render function. Loads the selected .pkl and dispatches to the
    appropriate renderer based on the file header (WIREFRAME/MESH/TRACER/ANIMATION).
    """
    global _cur_frame_col, _color_dict, _cur_render_number
    print("Rendering")

    _cur_render_number += 1
    cur_rendering_group = _RenderingGroup(num=_cur_render_number)

    print("Getting data")
    header, parsed_data = _get_data(_data_file_path)
    header = str(header)[2:-3]

    print("Got data for " + header)
    cur_render_col = bpy.data.collections.new(
        header + " Rendering " + str(_cur_render_number)
    )
    bpy.context.scene.collection.children.link(cur_render_col)

    if header == "MESH":
        _render_meshes(parsed_data, cur_render_col, cur_rendering_group)
    elif header == "TRACER":
        _render_tracers(parsed_data, cur_render_col)
    elif header == "WIREFRAME":
        _render_curves(parsed_data, cur_render_col, cur_rendering_group)
    elif header == "ANIMATION":
        _render_animation(parsed_data, cur_render_col, cur_rendering_group)


# ============================================================================
#  COLOR FILTER UI FUNCTIONS
# ============================================================================

def _hide_color(hide):
    """Show or hide all objects whose name contains the selected RGB color."""
    color = (
        bpy.context.scene.R_val,
        bpy.context.scene.G_val,
        bpy.context.scene.B_val,
    )
    for ob in bpy.data.objects:
        if str(color) in ob.name:
            ob.hide_set(hide)


def _show_all_colors():
    """Unhide all objects."""
    for ob in bpy.data.objects:
        ob.hide_set(False)


def _show_only_color():
    """Show only objects matching the selected RGB color, hide all others."""
    color = (
        bpy.context.scene.R_val,
        bpy.context.scene.G_val,
        bpy.context.scene.B_val,
    )
    for ob in bpy.data.objects:
        ob.hide_set(str(color) not in ob.name)


# ============================================================================
#  BLENDER OPERATORS
# ============================================================================

class MESH_OT_a_hide_color(bpy.types.Operator):
    bl_idname = "mesh.a_hide_color"
    bl_label = "Hide Color"
    def execute(self, context):
        _hide_color(True)
        return {"FINISHED"}

class MESH_OT_a_show_color(bpy.types.Operator):
    bl_idname = "mesh.a_show_color"
    bl_label = "Show Color"
    def execute(self, context):
        _hide_color(False)
        return {"FINISHED"}

class MESH_OT_a_show_all(bpy.types.Operator):
    bl_idname = "mesh.a_show_all"
    bl_label = "Show All"
    def execute(self, context):
        _show_all_colors()
        return {"FINISHED"}

class MESH_OT_a_show_only(bpy.types.Operator):
    bl_idname = "mesh.a_show_only"
    bl_label = "Show Only"
    def execute(self, context):
        _show_only_color()
        return {"FINISHED"}


class MESH_OT_a_choose_path(bpy.types.Operator):
    """Open a file browser to select a .pkl file for rendering."""
    bl_idname = "mesh.a_choose_path"
    bl_label = "Choose path"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        global _data_file_path
        _data_file_path = self.filepath
        self.report({"INFO"}, "Chosen path: " + str(_data_file_path))
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class MESH_OT_a_render(bpy.types.Operator):
    """Load the selected .pkl file and render its contents."""
    bl_idname = "mesh.a_render"
    bl_label = "Render Animation"

    def execute(self, context):
        global _tp_frames, _num_frames, _handler_activated
        bpy.context.scene.render.engine = "BLENDER_EEVEE"
        _render()

        # Register timepoint collections for frame-change animation
        col_timepoints = _rendering_groups[_cur_render_number - 1].timepoint_list
        _num_frames = len(col_timepoints)
        for col_num in range(_num_frames):
            if col_num in _tp_frames:
                _tp_frames[col_num].append(col_timepoints[col_num])
            else:
                _tp_frames[col_num] = [col_timepoints[col_num]]

        # Attach the frame-change handler (once)
        if not _handler_activated:
            _handler_activated = True
            bpy.app.handlers.frame_change_pre.append(_my_handler)

        # Show the first timepoint and zoom to fit
        first_frame = int(context.scene.frame_current * 0.1)
        if first_frame in _tp_frames:
            for col in _tp_frames[first_frame]:
                col.hide_viewport = False

        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        override = {
                            "area": area,
                            "region": region,
                            "edit_object": bpy.context.edit_object,
                        }
                        bpy.ops.view3d.view_all(override)

        bpy.context.scene.frame_end = len(_tp_frames) * FRAMES_PER_TIME_POINT
        return {"FINISHED"}


# ============================================================================
#  ANIMATION HANDLER
# ============================================================================

def _my_handler(scene):
    """Frame-change handler: show/hide collections for the current timepoint."""
    global _last_tp_index
    tp_index = scene.frame_current // FRAMES_PER_TIME_POINT

    if tp_index == _last_tp_index or tp_index not in _tp_frames:
        return

    _last_tp_index = tp_index

    # Hide all timepoints, then show the current one
    for frame_collections in _tp_frames.values():
        for col in frame_collections:
            col.hide_viewport = True
    for col in _tp_frames[tp_index]:
        col.hide_viewport = False


# ============================================================================
#  UI PANELS
# ============================================================================

class VIEW3D_PT_RenderPanel(bpy.types.Panel):
    bl_label = "Render File"
    bl_category = "Render File"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    def draw(self, context):
        layout = self.layout
        layout.operator("mesh.a_choose_path", text="Choose Path")
        layout.separator()
        layout.operator("mesh.a_render", text="Render")
        layout.separator()
        layout.prop(context.scene, "z_scale", slider=True)


class VIEW3D_PT_ColorPanel(bpy.types.Panel):
    bl_label = "Show/Hide Color"
    bl_category = "Show/Hide Color"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.operator("mesh.a_hide_color", text="Hide Color")
        row.operator("mesh.a_show_color", text="Show Color")
        row = layout.row()
        row.operator("mesh.a_show_only", text="Show Only")
        row.operator("mesh.a_show_all", text="Show All")
        layout.separator()
        layout.prop(context.scene, "R_val")
        layout.prop(context.scene, "G_val")
        layout.prop(context.scene, "B_val")


# ============================================================================
#  REGISTRATION
# ============================================================================

_classes = [
    VIEW3D_PT_ColorPanel,
    MESH_OT_a_hide_color,
    MESH_OT_a_show_color,
    MESH_OT_a_show_all,
    MESH_OT_a_show_only,
    VIEW3D_PT_RenderPanel,
    MESH_OT_a_render,
    MESH_OT_a_choose_path,
]


def register():
    bpy.types.Scene.R_val = bpy.props.IntProperty(
        name="R", description="Red channel (0-255)", min=0, max=255,
    )
    bpy.types.Scene.G_val = bpy.props.IntProperty(
        name="G", description="Green channel (0-255)", min=0, max=255,
    )
    bpy.types.Scene.B_val = bpy.props.IntProperty(
        name="B", description="Blue channel (0-255)", min=0, max=255,
    )
    bpy.types.Scene.z_scale = bpy.props.FloatProperty(
        name="Z Scale",
        description="Scale all rendered objects along the Z axis",
        default=Z_SCALE_DEFAULT,
        min=0.01,
        max=5.0,
        update=_update_z_scale,
    )
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in _classes:
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()

# Switch viewport shading to Material Preview so colors are visible
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type == "VIEW_3D":
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.shading.type = "MATERIAL"
                    space.clip_end = 7000
