bl_info = {
    "name": "Plasticity",
    "description": "A bridge to Plasticity",
    "author": "Nick Kallen, User129863",
    "version": (2, 0, 6),
    "blender": (4, 1, 0),
    "location": "View3D > Sidebar > Plasticity",
    "category": "Object",
}

import bpy
import json
import os
import bpy.app.handlers

from bpy.app.handlers import persistent
from . import operators, ui
from .client import PlasticityClient
from .handler import SceneHandler

handler = SceneHandler()
plasticity_client = PlasticityClient(handler)

addon_name = bl_info["name"].replace(" ", "_")  

base_path = bpy.utils.script_path_user()
presets_folder = os.path.join(base_path, 'presets', addon_name)

if not os.path.exists(presets_folder):
    os.makedirs(presets_folder)

PRESET_FILE_PATH = os.path.join(presets_folder, 'refacet_presets.json')

# Save Refacet presets
def save_presets():
    presets = []
    for preset in bpy.context.scene.refacet_presets:        
        preset_dict = preset.to_dict()        
        presets.append(preset_dict)
            
    with open(PRESET_FILE_PATH, 'w') as f:
        json.dump(presets, f)           

# Load refacet presets
@persistent
def load_presets(dummy):
    scene = bpy.context.scene

    # Clear existing presets
    scene.refacet_presets.clear()
    
    if scene is None or not os.path.exists(PRESET_FILE_PATH):        
        return
    with open(PRESET_FILE_PATH, 'r') as f:
        presets = json.load(f)    
    
    for preset_dict in presets:
        preset = scene.refacet_presets.add()
        preset.from_dict(preset_dict)            

    # Ensure checker library defaults are initialized after loading
    if getattr(scene, "prop_plasticity_checker_source", None) is None:
        scene.prop_plasticity_checker_source = "LIBRARY"
    if getattr(scene, "prop_plasticity_checker_source", None) == "LIBRARY":
        default_enum = operators.get_checker_default_enum()
        if default_enum:
            scene.prop_plasticity_checker_image = default_enum

def update_and_save_preset(self, context):
    save_presets()
    
def update_name(self, context):
    print("Name updated.")
    save_presets()    

def _density_to_plane_tolerance(density):
    return max(0.0001, 0.01 * (1.0 - density))

def _density_to_angle_tolerance(density):
    return max(0.10, 0.45 - 0.35 * density)

def _set_attr_if_changed(obj, attr, value, eps=1e-9):
    current = getattr(obj, attr, None)
    if current is None:
        setattr(obj, attr, value)
        return True
    if isinstance(current, float) and abs(current - value) <= eps:
        return False
    if current == value:
        return False
    setattr(obj, attr, value)
    return True

def update_density_preset(self, context):
    density = max(0.01, min(1.0, float(self.density)))
    plane_tol = _density_to_plane_tolerance(density)
    angle_tol = _density_to_angle_tolerance(density)
    _set_attr_if_changed(self, "tolerance", plane_tol)
    _set_attr_if_changed(self, "angle", angle_tol)
    _set_attr_if_changed(self, "Edge_chord_tolerance", plane_tol)
    _set_attr_if_changed(self, "Face_plane_tolerance", plane_tol)
    _set_attr_if_changed(self, "Edge_Angle_tolerance", angle_tol)
    _set_attr_if_changed(self, "Face_Angle_tolerance", angle_tol)
    save_presets()

def update_density_scene(self, context):
    density = max(0.01, min(1.0, float(self.prop_plasticity_facet_density)))
    plane_tol = _density_to_plane_tolerance(density)
    angle_tol = _density_to_angle_tolerance(density)
    _set_attr_if_changed(self, "prop_plasticity_facet_tolerance", plane_tol)
    _set_attr_if_changed(self, "prop_plasticity_facet_angle", angle_tol)
    _set_attr_if_changed(self, "prop_plasticity_curve_chord_tolerance", plane_tol)
    _set_attr_if_changed(self, "prop_plasticity_surface_plane_tolerance", plane_tol)
    _set_attr_if_changed(self, "prop_plasticity_curve_angle_tolerance", angle_tol)
    _set_attr_if_changed(self, "prop_plasticity_surface_angle_tolerance", angle_tol)


LIVE_EXPAND_CIRCLE_RADIUS = 5
_LAST_CONTEXT_MODE = None


def update_live_expand(self, context):
    if context.scene.prop_plasticity_live_expand:
        operators.ensure_live_expand_timer()
        if getattr(context.scene, "prop_plasticity_live_expand_edge_highlight", False):
            operators.ensure_live_expand_overlay()
        operators.set_live_expand_active_view(context)
        if getattr(context.scene, "prop_plasticity_live_expand_auto_circle", False):
            _set_view3d_tool("builtin.select_circle", circle_radius=LIVE_EXPAND_CIRCLE_RADIUS)
    else:
        if getattr(context.scene, "prop_plasticity_live_expand_auto_circle", False):
            _set_view3d_tool("builtin.select_box")
        operators.stop_live_expand_timer()
        if not getattr(context.scene, "prop_plasticity_live_expand_edge_highlight", False):
            operators.stop_live_expand_overlay()

def update_live_expand_auto_circle(self, context):
    if self.prop_plasticity_live_expand_auto_circle and self.prop_plasticity_live_expand:
        _set_view3d_tool("builtin.select_circle", circle_radius=LIVE_EXPAND_CIRCLE_RADIUS)
    elif not self.prop_plasticity_live_expand_auto_circle:
        _set_view3d_tool("builtin.select_box")


def update_live_expand_edge_highlight(self, context):
    if self.prop_plasticity_live_expand_edge_highlight:
        operators.ensure_live_expand_overlay()
        operators.set_live_expand_active_view(context)
    else:
        operators.stop_live_expand_overlay()


def _on_mode_change(scene, depsgraph):
    global _LAST_CONTEXT_MODE
    context = bpy.context
    mode = getattr(context, "mode", None)
    if mode == _LAST_CONTEXT_MODE:
        return
    _LAST_CONTEXT_MODE = mode
    if mode != 'OBJECT':
        return
    scene = context.scene
    if scene is None:
        return
    if getattr(scene, "prop_plasticity_live_expand_auto_circle", False):
        _set_view3d_tool("builtin.select_box")

def update_live_refacet(self, context):
    if not self.prop_plasticity_live_refacet:
        operators.stop_live_refacet_timer()
        return
    if context is None or context.mode != 'OBJECT':
        self.prop_plasticity_live_refacet = False
        operators.stop_live_refacet_timer()
        return
    operators.ensure_live_refacet_timer()

def update_checker_custom_path(self, context):
    if context.scene.prop_plasticity_checker_custom_path:
        context.scene.prop_plasticity_checker_source = "FILE"

def update_checker_source(self, context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    if getattr(scene, "prop_plasticity_checker_source", None) != "LIBRARY":
        return
    current = getattr(scene, "prop_plasticity_checker_image", None)
    if current and current != "NONE":
        return
    default_enum = operators.get_checker_default_enum()
    if default_enum and hasattr(scene, "prop_plasticity_checker_image"):
        scene.prop_plasticity_checker_image = default_enum

def _set_view3d_tool(tool_id, circle_radius=None):
    window_manager = bpy.context.window_manager
    if window_manager is None:
        return False
    for window in window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue
            try:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.wm.tool_set_by_id(name=tool_id)
                    if circle_radius is not None and tool_id == "builtin.select_circle":
                        _set_circle_radius(circle_radius)
                return True
            except Exception:
                continue
    return False


def _set_circle_radius(radius):
    try:
        workspace = bpy.context.workspace
        if workspace is None:
            return False
        tool = workspace.tools.from_space_view3d_mode(bpy.context.mode, create=False)
        if tool is None:
            return False
        props = tool.operator_properties("view3d.select_circle")
        if props is None:
            return False
        props.radius = int(radius)
        return True
    except Exception:
        return False

# Custom UIList to catch the event of renaming a member of the list. Looks like it's not natively supported by the API (necessary in order to save the Refacet presets whenever an entry is renamed by double clicking on an entry and renaming it).
class OBJECT_UL_RefacetPresetsList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.prop(item, "name", text="", emboss=False, icon_value=icon)
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)    

# Refacet Preset Class    
class RefacetPreset(bpy.types.PropertyGroup):              
    name: bpy.props.StringProperty(name="Name", default="New Preset", update=update_name)
    
    # Basic settings
    density: bpy.props.FloatProperty(
        name="Density",
        default=0.01,
        min=0.01,
        max=1.0,
        step=0.01,
        precision=2,
        subtype='FACTOR',
        update=update_density_preset,
    )
    tolerance: bpy.props.FloatProperty(name="Tolerance", default=0.01, min=0.0001, max=0.1, step=0.001, precision=6, update=update_and_save_preset)
    angle: bpy.props.FloatProperty(name="Angle", default=0.45, min=0.1, max=1.0, update=update_and_save_preset)
    facet_tri_or_ngon: bpy.props.EnumProperty(
        items=[
            ('TRI', "Tri", "Triangles only"),
            ('QUAD', "Quad", "Limit to 4 sides; may still output triangles"),
            ('NGON', "Ngon", "Ngons allowed"),
        ],
        name="Facet Type",
        default='TRI',
        update=update_and_save_preset,
    )
    
    # Advanced settings
    min_width: bpy.props.FloatProperty(name="Min Width", default=0.01, min=0, max=10, unit="LENGTH", update=update_and_save_preset)    
    min_width_enabled: bpy.props.BoolProperty(
        name="Min Width",
        default=False,
        update=update_and_save_preset,
    )
    max_width: bpy.props.FloatProperty(name="Max Width", default=1.0, min=0.0001, max=1000.0, step=0.01, soft_min=0.02, precision=6, unit="LENGTH", update=update_and_save_preset)
    max_width_enabled: bpy.props.BoolProperty(
        name="Max Width",
        default=False,
        update=update_and_save_preset,
    )
    Edge_chord_tolerance: bpy.props.FloatProperty(name="Edge chord tolerance", default=0.01, min=0.0001, step=0.01, max=1.0, precision=6, update=update_and_save_preset)
    Edge_Angle_tolerance: bpy.props.FloatProperty(name="Edge Angle tolerance", default=0.45, min=0.1, max=1.0, update=update_and_save_preset)
    Face_plane_tolerance: bpy.props.FloatProperty(name="Face plane tolerance", default=0.01, min=0.0001, step=0.01, max=1.0, precision=6, update=update_and_save_preset)
    Face_Angle_tolerance: bpy.props.FloatProperty(name="Face Angle tolerance", default=0.45, min=0.1, max=1.0, update=update_and_save_preset)     
    plane_angle: bpy.props.FloatProperty(
        name="Plane Angle",
        default=0.1,
        min=0.0,
        max=3.14159,
        step=0.01,
        precision=4,
        update=update_and_save_preset,
    )
    convex_ngons_only: bpy.props.BoolProperty(
        name="Convex Ngons Only",
        default=False,
        update=update_and_save_preset,
    )
    curve_max_length_enabled: bpy.props.BoolProperty(
        name="Curve Max Length",
        default=False,
        update=update_and_save_preset,
    )
    curve_max_length: bpy.props.FloatProperty(
        name="Curve Max Length",
        default=0.0,
        min=0.0,
        max=1000.0,
        step=0.01,
        precision=6,
        unit="LENGTH",
        update=update_and_save_preset,
    )
    relative_to_bbox: bpy.props.BoolProperty(
        name="Relative to BBox",
        default=True,
        update=update_and_save_preset,
    )
    match_topology: bpy.props.BoolProperty(
        name="Match Topology",
        default=True,
        update=update_and_save_preset,
    )

    def to_dict(self):
        return {attr: getattr(self, attr) for attr in dir(self) 
                if not callable(getattr(self, attr)) 
                and not attr.startswith("__") 
                and isinstance(getattr(self, attr), (int, float, str))}

    def from_dict(self, preset_dict):
        for attr, value in preset_dict.items():
            setattr(self, attr, value)                 

class AddRefacetPresetOperator(bpy.types.Operator):
    bl_idname = "refacet_preset.add"
    bl_label = "Add Refacet Preset"
    bl_description = "Create a new refacet preset and save it to disk"
    
    def execute(self, context):
        preset = context.scene.refacet_presets.add()
        preset.name = "New Preset"
        save_presets()
        return {'FINISHED'}

class RemoveRefacetPresetOperator(bpy.types.Operator):
    bl_idname = "refacet_preset.remove"
    bl_label = "Remove Refacet Preset"
    bl_description = "Delete the active refacet preset and save changes (destructive)"
    
    def execute(self, context):
        index = context.scene.active_refacet_preset_index
        context.scene.refacet_presets.remove(index)
        save_presets()

        if len(context.scene.refacet_presets) > 0:
            context.scene.active_refacet_preset_index = min(max(0, index - 1), len(context.scene.refacet_presets) - 1)
        else:
            context.scene.active_refacet_preset_index = -1

        return {'FINISHED'}

def select_similar(self, context):
    self.layout.operator(operators.SelectByFaceIDOperator.bl_idname)   

def register():
    print("Registering Plasticity client")

    bpy.utils.register_class(ui.ConnectButton)
    bpy.utils.register_class(ui.DisconnectButton)
    bpy.utils.register_class(ui.ListButton)
    bpy.utils.register_class(ui.SubscribeAllButton)
    bpy.utils.register_class(ui.UnsubscribeAllButton)
    bpy.utils.register_class(ui.RefacetButton)

    bpy.utils.register_class(RefacetPreset)
    bpy.types.Scene.refacet_presets = bpy.props.CollectionProperty(type=RefacetPreset)
    bpy.types.Scene.active_refacet_preset_index = bpy.props.IntProperty(name="Active Preset", default=0)
    bpy.utils.register_class(AddRefacetPresetOperator)
    bpy.utils.register_class(RemoveRefacetPresetOperator) 
   
    bpy.utils.register_class(ui.PlasticityPanel)
    bpy.utils.register_class(operators.SelectByFaceIDOperator)
    bpy.utils.register_class(operators.SelectByFaceIDEdgeOperator)
    bpy.utils.register_class(operators.AutoMarkEdgesOperator)
    bpy.utils.register_class(operators.MergeUVSeams)
    bpy.utils.register_class(operators.RelaxUVsPlasticityOperator)
    bpy.utils.register_class(operators.AutoUnwrapPlasticityOperator)
    bpy.utils.register_class(operators.PaintPlasticityFacesOperator)
    bpy.utils.register_class(operators.SimilarGeometrySelector)
    bpy.utils.register_class(operators.SelectedJoiner)
    bpy.utils.register_class(operators.SelectedUnjoiner)    
    bpy.utils.register_class(operators.NonOverlappingMeshesMerger)   
    bpy.utils.register_class(operators.OpenUVEditorOperator) 
    bpy.utils.register_class(operators.CloseUVEditorOperator)
    bpy.utils.register_class(operators.MaterialRemover)
    bpy.utils.register_class(operators.AssignUVCheckerTextureOperator)
    bpy.utils.register_class(operators.SelectCheckerImageOperator)
    bpy.utils.register_class(operators.RemoveUVCheckerNodesOperator)
    bpy.utils.register_class(operators.TextureReloader)
    bpy.utils.register_class(operators.ImportFBXOperator)
    bpy.utils.register_class(operators.ExportFBXOperator)
    bpy.utils.register_class(operators.ImportOBJOperator)
    bpy.utils.register_class(operators.ExportOBJOperator)
    bpy.utils.register_class(operators.MirrorOperator)
    bpy.utils.register_class(operators.RemoveModifiers)
    bpy.utils.register_class(operators.ApplyModifiers)
    bpy.utils.register_class(operators.RemoveVertexGroups)
    bpy.utils.register_class(operators.SnapToCursorOperator)
    bpy.utils.register_class(operators.SelectMeshesWithNgons)
    bpy.utils.register_class(operators.SelectObjectsWithoutUVs)
    bpy.utils.register_class(operators.RemoveUVsFromSelectedObjects)

    bpy.types.VIEW3D_MT_edit_mesh_select_similar.append(select_similar)

    bpy.types.Scene.prop_plasticity_server = bpy.props.StringProperty(name="Server", default="localhost:8980")
    bpy.types.Scene.prop_plasticity_facet_tolerance = bpy.props.FloatProperty(name="Tolerance", default=0.01, min=0.0001, max=0.1, step=0.001, precision=6)
    bpy.types.Scene.prop_plasticity_facet_angle = bpy.props.FloatProperty(name="Angle", default=0.45, min=0.1, max=1.0)
    bpy.types.Scene.prop_plasticity_facet_density = bpy.props.FloatProperty(
        name="Density",
        default=0.01,
        min=0.01,
        max=1.0,
        step=0.01,
        precision=2,
        subtype='FACTOR',
        update=update_density_scene,
    )
    bpy.types.Scene.prop_plasticity_list_only_visible = bpy.props.BoolProperty(name="List only visible", default=False)
    bpy.types.Scene.prop_plasticity_list_only_selected = bpy.props.BoolProperty(name="List only selected", default=False)
    bpy.types.Scene.prop_plasticity_facet_tri_or_ngon = bpy.props.EnumProperty(
        items=[
            ("TRI", "Tri", "Triangles only"),
            ("QUAD", "Quad", "Limit to 4 sides; may still output triangles"),
            ("NGON", "Ngon", "Ngons allowed"),
        ],
        name="Facet Type",
        default="TRI",
    )
    bpy.types.Scene.prop_plasticity_select_adjacent_fillets = bpy.props.BoolProperty(
        name="Select Adjacent Fillets",
        description="Also select adjacent Plasticity groups that look like fillets",
        default=False,
    )
    bpy.types.Scene.prop_plasticity_select_fillet_min_curvature_angle = bpy.props.FloatProperty(
        name="Min Curvature Angle",
        description="Minimum normal deviation (degrees) to treat a group as curved",
        default=5.0,
        min=0.0,
        max=90.0,
    )
    bpy.types.Scene.prop_plasticity_select_fillet_max_area_ratio = bpy.props.FloatProperty(
        name="Max Area Ratio",
        description="Maximum fillet area relative to its largest adjacent group",
        default=0.06,
        min=0.0,
        max=1.0,
        soft_max=1.0,
        step=0.001,
        precision=4,
        subtype='FACTOR',
    )
    bpy.types.Scene.prop_plasticity_select_fillet_min_adjacent_groups = bpy.props.IntProperty(
        name="Min Adjacent Groups",
        description="Minimum adjacent group count for a fillet candidate",
        default=2,
        min=1,
        max=8,
    )
    bpy.types.Scene.prop_plasticity_select_include_vertex_adjacency = bpy.props.BoolProperty(
        name="Include Vertex Adjacent",
        description="Also consider Plasticity groups that only touch at a vertex",
        default=False,
    )
    bpy.types.Scene.prop_plasticity_select_vertex_adjacent_max_length_ratio = bpy.props.FloatProperty(
        name="Max Vertex Adjacent Length Ratio",
        description="Limit vertex-adjacent fillet selection by relative size (1.0 disables)",
        default=0.5,
        min=0.0,
        max=10.0,
        step=0.01,
        precision=2,
    )
    bpy.types.Scene.prop_plasticity_live_expand = bpy.props.BoolProperty(
        name="Live Expand",
        description="Automatically expand selected triangles to Plasticity faces",
        default=False,
        update=update_live_expand,
    )
    bpy.types.Scene.prop_plasticity_live_expand_auto_circle = bpy.props.BoolProperty(
        name="Auto Circle Select Mode",
        description="Switch to Circle Select when Live Expand is enabled",
        default=False,
        update=update_live_expand_auto_circle,
    )
    bpy.types.Scene.prop_plasticity_live_expand_edge_highlight = bpy.props.BoolProperty(
        name="Plasticity Edge Highlight",
        description="Draw Plasticity edge highlights using the overlay color",
        default=False,
        update=update_live_expand_edge_highlight,
    )
    bpy.types.Scene.prop_plasticity_live_expand_active_view_only = bpy.props.BoolProperty(
        name="Active View Only",
        description="Draw Plasticity edge highlights only in the active 3D view",
        default=False,
    )
    bpy.types.Scene.prop_plasticity_live_expand_interval = bpy.props.FloatProperty(
        name="Live Expand Interval",
        description="Seconds between Live Expand updates",
        default=0.1,
        min=0.01,
        max=10.0,
        step=0.01,
        precision=2,
        subtype='TIME',
    )
    bpy.types.Scene.prop_plasticity_live_expand_auto_merge_seams = bpy.props.BoolProperty(
        name="Auto Merge Seams on Selection",
        description="Automatically merge seams inside the Live Expand selection",
        default=False,
    )
    bpy.types.Scene.prop_plasticity_auto_cylinder_seam = bpy.props.BoolProperty(
        name="Auto Cylinder Seam",
        description="Insert a seam on cylindrical selections to prevent UV overlap",
        default=False,
    )
    bpy.types.Scene.prop_plasticity_auto_cylinder_seam_mode = bpy.props.EnumProperty(
        name="Cylinder Seam Mode",
        description="When to insert a cylinder seam",
        items=[
            ('FULL', "Full Only", "Only insert a seam on fully wrapped cylinders"),
            ('PARTIAL', "Partial + Full", "Also insert seams on large partial wraps"),
        ],
        default='FULL',
    )
    bpy.types.Scene.prop_plasticity_auto_cylinder_partial_angle = bpy.props.FloatProperty(
        name="Partial Wrap Angle",
        description="Minimum wrap angle (degrees) to insert a seam on partial cylinders",
        default=200.0,
        min=90.0,
        max=360.0,
        step=1.0,
        precision=1,
    )
    bpy.types.Scene.prop_plasticity_auto_cylinder_seam_occluded_only = bpy.props.BoolProperty(
        name="Occluded Only (View)",
        description="Only place auto cylinder seams on edges occluded from the active 3D view",
        default=False,
    )
    bpy.types.Scene.prop_plasticity_live_expand_respect_seams = bpy.props.BoolProperty(
        name="Respect Existing Seams",
        description="Keep existing seams when auto-merging",
        default=False,
    )
    bpy.types.Scene.prop_plasticity_live_expand_edge_thickness = bpy.props.FloatProperty(
        name="Plasticity Edge Highlight Thickness",
        description="Thickness of Plasticity boundary edges overlay",
        default=3.0,
        min=1.0,
        max=10.0,
        step=0.1,
        precision=1,
    )
    bpy.types.Scene.prop_plasticity_live_expand_edge_occlude = bpy.props.BoolProperty(
        name="Occlude Hidden Edges",
        description="Hide Plasticity edge highlights when occluded by geometry",
        default=True,
    )
    bpy.types.Scene.prop_plasticity_live_expand_overlay_color = bpy.props.FloatVectorProperty(
        name="Plasticity Edge Highlight Color",
        description="Color used for the Plasticity edge highlight overlay",
        default=(0.0, 1.0, 0.0, 1.0),
        size=4,
        min=0.0,
        max=1.0,
        subtype='COLOR',
    )
    bpy.types.Scene.prop_plasticity_ui_show_advanced_facet = bpy.props.BoolProperty(name="Advanced", default=False)
    bpy.types.Scene.prop_plasticity_ui_show_refacet = bpy.props.BoolProperty(name="Refacet", default=True)
    bpy.types.Scene.prop_plasticity_live_refacet = bpy.props.BoolProperty(
        name="Live Refacet Mode",
        description="Automatically refacet selected objects when settings change",
        default=False,
        update=update_live_refacet,
    )
    bpy.types.Scene.prop_plasticity_live_refacet_interval = bpy.props.FloatProperty(
        name="Live Refacet Interval",
        description="Seconds between live refacet checks",
        default=0.2,
        min=0.0,
        max=10.0,
        step=0.1,
        precision=2,
        subtype='TIME',
    )
    bpy.types.Scene.prop_plasticity_ui_show_utilities = bpy.props.BoolProperty(name="Utilities", default=True)
    bpy.types.Scene.prop_plasticity_ui_show_uv_tools = bpy.props.BoolProperty(name="UV Tools", default=True)
    bpy.types.Scene.prop_plasticity_ui_show_mesh_tools = bpy.props.BoolProperty(name="Mesh Tools", default=True)
    bpy.types.Scene.prop_plasticity_checker_source = bpy.props.EnumProperty(
        items=[
            ("LIBRARY", "Checker Textures Library", "Use bundled checker textures"),
            ("FILE", "Custom Checker Texture", "Use a custom checker image"),
        ],
        name="Checker Source",
        default="LIBRARY",
        update=update_checker_source,
    )
    bpy.types.Scene.prop_plasticity_checker_image = bpy.props.EnumProperty(
        items=operators.get_checker_image_items,
        name="Checker Texture",
        # Blender 4.5 requires an integer index default when items is a callback.
        default=0,
    )
    bpy.types.Scene.prop_plasticity_checker_custom_path = bpy.props.StringProperty(
        name="Checker Image",
        subtype="FILE_PATH",
        default="",
        update=update_checker_custom_path,
    )
    bpy.types.Scene.prop_plasticity_facet_min_width = bpy.props.FloatProperty(name="Min Width", default=0.01, min=0, max=10, unit="LENGTH")
    bpy.types.Scene.prop_plasticity_facet_min_width_enabled = bpy.props.BoolProperty(
        name="Min Width",
        default=False,
    )
    bpy.types.Scene.prop_plasticity_facet_max_width = bpy.props.FloatProperty(name="Max Width", default=1.0, min=0.0001, max=1000.0, step=0.01, soft_min=0.02, precision=6, unit="LENGTH")
    bpy.types.Scene.prop_plasticity_facet_max_width_enabled = bpy.props.BoolProperty(
        name="Max Width",
        default=False,
    )
    bpy.types.Scene.prop_plasticity_unit_scale = bpy.props.FloatProperty(name="Unit Scale", default=1.0, min=0.0001, max=1000.0)
    bpy.types.Scene.prop_plasticity_curve_chord_tolerance = bpy.props.FloatProperty(name="Edge chord tolerance", default=0.01, min=0.0001, step=0.01, max=1.0, precision=6)
    bpy.types.Scene.prop_plasticity_curve_angle_tolerance = bpy.props.FloatProperty(name="Edge Angle tolerance", default=0.45, min=0.1, max=1.0)
    bpy.types.Scene.prop_plasticity_surface_plane_tolerance = bpy.props.FloatProperty(name="Face plane tolerance", default=0.01, min=0.0001, step=0.01, max=1.0, precision=6)
    bpy.types.Scene.prop_plasticity_surface_angle_tolerance = bpy.props.FloatProperty(name="Face Angle tolerance", default=0.45, min=0.1, max=1.0)
    bpy.types.Scene.prop_plasticity_plane_angle = bpy.props.FloatProperty(
        name="Plane Angle",
        default=0.1,
        min=0.0,
        max=3.14159,
        step=0.01,
        precision=4,
    )
    bpy.types.Scene.prop_plasticity_convex_ngons_only = bpy.props.BoolProperty(
        name="Convex Ngons Only",
        default=False,
    )
    bpy.types.Scene.prop_plasticity_curve_max_length_enabled = bpy.props.BoolProperty(
        name="Curve Max Length",
        default=False,
    )
    bpy.types.Scene.prop_plasticity_curve_max_length = bpy.props.FloatProperty(
        name="Curve Max Length",
        default=0.0,
        min=0.0,
        max=1000.0,
        step=0.01,
        precision=6,
        unit="LENGTH",
    )
    bpy.types.Scene.prop_plasticity_relative_to_bbox = bpy.props.BoolProperty(
        name="Relative to BBox",
        default=True,
    )
    bpy.types.Scene.prop_plasticity_match_topology = bpy.props.BoolProperty(
        name="Match Topology",
        default=True,
    )
    bpy.types.Scene.mark_seam = bpy.props.BoolProperty(name="Mark Seam")
    bpy.types.Scene.mark_sharp = bpy.props.BoolProperty(name="Mark Sharp") 
    bpy.types.WindowManager.plasticity_busy = bpy.props.BoolProperty(name="Plasticity busy", default=False, options={'HIDDEN'}
)
    bpy.types.Scene.overlap_threshold = bpy.props.FloatProperty(
        name="Overlap Threshold",
        description="The threshold below which two meshes are considered to be overlapping",
        default=0.01,
        min=0.0,
        max=1.0,
    )
    bpy.types.Scene.mirror_axis = bpy.props.EnumProperty(
        items=[
            ('X', "X", "Mirror along the X axis"),
            ('Y', "Y", "Mirror along the Y axis"),
            ('Z', "Z", "Mirror along the Z axis")
        ],
        name="Mirror Axis",
        description="The axis along which to mirror the objects",
        default='X'
    )
    bpy.types.Scene.mirror_center_object = bpy.props.PointerProperty(
        name="Mirror Center Object",
        description="The object to use as the center for the mirror operation",
        type=bpy.types.Object
    )
        
    bpy.utils.register_class(OBJECT_UL_RefacetPresetsList)  

    bpy.app.handlers.load_post.append(load_presets)    
    if _on_mode_change not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_mode_change)

    print("Plasticity client registered")

def unregister():
    print("Unregistering Plasticity client")
    operators.stop_live_expand_timer()
    operators.stop_live_refacet_timer()
    operators.stop_live_expand_overlay()

    bpy.utils.unregister_class(ui.PlasticityPanel)
    bpy.utils.unregister_class(ui.DisconnectButton)
    bpy.utils.unregister_class(ui.ConnectButton)
    bpy.utils.unregister_class(ui.ListButton)
    bpy.utils.unregister_class(ui.SubscribeAllButton)
    bpy.utils.unregister_class(ui.UnsubscribeAllButton)
    bpy.utils.unregister_class(ui.RefacetButton)
    
    bpy.utils.unregister_class(RefacetPreset)
    bpy.utils.unregister_class(AddRefacetPresetOperator)
    bpy.utils.unregister_class(RemoveRefacetPresetOperator)
    del bpy.types.Scene.refacet_presets
    del bpy.types.Scene.active_refacet_preset_index 
          
    bpy.utils.unregister_class(operators.SelectByFaceIDOperator)
    bpy.utils.unregister_class(operators.SelectByFaceIDEdgeOperator)
    bpy.utils.unregister_class(operators.AutoMarkEdgesOperator)
    bpy.utils.unregister_class(operators.MergeUVSeams)
    bpy.utils.unregister_class(operators.RelaxUVsPlasticityOperator)
    bpy.utils.unregister_class(operators.AutoUnwrapPlasticityOperator)
    bpy.utils.unregister_class(operators.PaintPlasticityFacesOperator)
    bpy.utils.unregister_class(operators.SimilarGeometrySelector)
    bpy.utils.unregister_class(operators.SelectedJoiner) 
    bpy.utils.unregister_class(operators.SelectedUnjoiner)     
    bpy.utils.unregister_class(operators.NonOverlappingMeshesMerger)
    bpy.utils.unregister_class(operators.OpenUVEditorOperator)  
    bpy.utils.unregister_class(operators.CloseUVEditorOperator)
    bpy.utils.unregister_class(operators.MaterialRemover)
    bpy.utils.unregister_class(operators.AssignUVCheckerTextureOperator)
    bpy.utils.unregister_class(operators.SelectCheckerImageOperator)
    bpy.utils.unregister_class(operators.RemoveUVCheckerNodesOperator)
    bpy.utils.unregister_class(operators.TextureReloader)
    bpy.utils.unregister_class(operators.ImportFBXOperator)
    bpy.utils.unregister_class(operators.ExportFBXOperator)
    bpy.utils.unregister_class(operators.ImportOBJOperator)
    bpy.utils.unregister_class(operators.ExportOBJOperator)
    bpy.utils.unregister_class(operators.MirrorOperator)
    bpy.utils.unregister_class(operators.RemoveModifiers)
    bpy.utils.unregister_class(operators.ApplyModifiers)
    bpy.utils.unregister_class(operators.RemoveVertexGroups)
    bpy.utils.unregister_class(operators.SnapToCursorOperator)
    bpy.utils.unregister_class(operators.SelectMeshesWithNgons)
    bpy.utils.unregister_class(operators.SelectObjectsWithoutUVs)
    bpy.utils.unregister_class(operators.RemoveUVsFromSelectedObjects)
    operators.clear_checker_previews()

    bpy.types.VIEW3D_MT_edit_mesh_select_similar.remove(select_similar)
    
    bpy.utils.unregister_class(OBJECT_UL_RefacetPresetsList)    
    
    bpy.app.handlers.load_post.remove(load_presets)
    if _on_mode_change in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_mode_change)

    del bpy.types.Scene.prop_plasticity_server
    del bpy.types.Scene.prop_plasticity_facet_tolerance
    del bpy.types.Scene.prop_plasticity_facet_angle
    del bpy.types.Scene.prop_plasticity_facet_density
    del bpy.types.Scene.prop_plasticity_facet_tri_or_ngon
    del bpy.types.Scene.prop_plasticity_select_adjacent_fillets
    del bpy.types.Scene.prop_plasticity_select_fillet_min_curvature_angle
    del bpy.types.Scene.prop_plasticity_select_fillet_max_area_ratio
    del bpy.types.Scene.prop_plasticity_select_fillet_min_adjacent_groups
    del bpy.types.Scene.prop_plasticity_select_include_vertex_adjacency
    del bpy.types.Scene.prop_plasticity_select_vertex_adjacent_max_length_ratio
    del bpy.types.Scene.prop_plasticity_live_expand
    del bpy.types.Scene.prop_plasticity_live_expand_auto_circle
    del bpy.types.Scene.prop_plasticity_live_expand_edge_highlight
    del bpy.types.Scene.prop_plasticity_live_expand_active_view_only
    del bpy.types.Scene.prop_plasticity_live_expand_interval
    del bpy.types.Scene.prop_plasticity_live_expand_auto_merge_seams
    del bpy.types.Scene.prop_plasticity_auto_cylinder_seam
    del bpy.types.Scene.prop_plasticity_auto_cylinder_seam_mode
    del bpy.types.Scene.prop_plasticity_auto_cylinder_partial_angle
    del bpy.types.Scene.prop_plasticity_auto_cylinder_seam_occluded_only
    del bpy.types.Scene.prop_plasticity_live_expand_respect_seams
    del bpy.types.Scene.prop_plasticity_live_expand_edge_thickness
    del bpy.types.Scene.prop_plasticity_live_expand_edge_occlude
    del bpy.types.Scene.prop_plasticity_live_expand_overlay_color
    del bpy.types.Scene.prop_plasticity_list_only_visible
    del bpy.types.Scene.prop_plasticity_list_only_selected
    del bpy.types.Scene.prop_plasticity_ui_show_advanced_facet
    del bpy.types.Scene.prop_plasticity_ui_show_refacet
    del bpy.types.Scene.prop_plasticity_live_refacet
    del bpy.types.Scene.prop_plasticity_live_refacet_interval
    del bpy.types.Scene.prop_plasticity_ui_show_utilities
    del bpy.types.Scene.prop_plasticity_ui_show_uv_tools
    del bpy.types.Scene.prop_plasticity_ui_show_mesh_tools
    del bpy.types.Scene.prop_plasticity_checker_source
    del bpy.types.Scene.prop_plasticity_checker_image
    del bpy.types.Scene.prop_plasticity_checker_custom_path
    del bpy.types.Scene.prop_plasticity_facet_min_width
    del bpy.types.Scene.prop_plasticity_facet_max_width
    del bpy.types.Scene.prop_plasticity_facet_min_width_enabled
    del bpy.types.Scene.prop_plasticity_facet_max_width_enabled
    del bpy.types.Scene.prop_plasticity_unit_scale
    del bpy.types.Scene.prop_plasticity_surface_angle_tolerance
    del bpy.types.Scene.mark_seam
    del bpy.types.Scene.mark_sharp
    del bpy.types.WindowManager.plasticity_busy
    del bpy.types.Scene.prop_plasticity_curve_chord_tolerance
    del bpy.types.Scene.prop_plasticity_curve_angle_tolerance
    del bpy.types.Scene.prop_plasticity_surface_plane_tolerance
    del bpy.types.Scene.prop_plasticity_plane_angle
    del bpy.types.Scene.prop_plasticity_convex_ngons_only
    del bpy.types.Scene.prop_plasticity_curve_max_length_enabled
    del bpy.types.Scene.prop_plasticity_curve_max_length
    del bpy.types.Scene.prop_plasticity_relative_to_bbox
    del bpy.types.Scene.prop_plasticity_match_topology
    del bpy.types.Scene.overlap_threshold
    del bpy.types.Scene.mirror_axis
    del bpy.types.Scene.mirror_center_object



if __name__ == "__main__":
    register()
