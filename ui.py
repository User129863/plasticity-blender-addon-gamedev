import bpy
import math

from .__init__ import plasticity_client
from .__init__ import load_presets
from .client import FacetShapeType


def _pin_icon(scene, prop_name):
    return "PINNED" if getattr(scene, prop_name) else "UNPINNED"


class ConnectButton(bpy.types.Operator):
    bl_idname = "wm.connect_button"
    bl_label = "Connect"
    bl_description = "Connect to the Plasticity server at the configured address"

    @classmethod
    def poll(cls, context):
        return not plasticity_client.connected

    def execute(self, context):
        server = context.scene.prop_plasticity_server
        plasticity_client.connect(server)
        
        # Load the refacet presets after connecting (not ideal, but works for now).
        load_presets(context.scene)
        
        return {'FINISHED'}


class DisconnectButton(bpy.types.Operator):
    bl_idname = "wm.disconnect_button"
    bl_label = "Disconnect"
    bl_description = "Disconnect from the Plasticity server"

    @classmethod
    def poll(cls, context):
        return plasticity_client.connected

    def execute(self, context):
        context.window_manager.plasticity_busy = False
        plasticity_client.disconnect()
        return {'FINISHED'}


class ListButton(bpy.types.Operator):
    bl_idname = "wm.list"
    bl_label = "Refresh"
    bl_description = "Refresh the Plasticity object list (respects Only visible)"

    @classmethod
    def poll(cls, context):
        if context.window_manager.plasticity_busy:
            return False
        return plasticity_client.connected

    def execute(self, context):
        only_visible = context.scene.prop_plasticity_list_only_visible
        if context.scene.prop_plasticity_list_only_selected:
            selected_ids = [
                obj["plasticity_id"]
                for obj in context.selected_objects
                if obj.type == 'MESH' and "plasticity_id" in obj.keys()
            ]
            if selected_ids:
                plasticity_client.handler.list_filter_ids = set(selected_ids)
            else:
                plasticity_client.handler.list_filter_ids = set()
        else:
            plasticity_client.handler.list_filter_ids = None
        if only_visible:
            plasticity_client.list_visible()
        else:
            plasticity_client.list_all()
        return {'FINISHED'}


class SubscribeAllButton(bpy.types.Operator):
    bl_idname = "wm.subscribe_all"
    bl_label = "Subscribe All"
    bl_description = "Subscribe to all available meshes for live updates"

    @classmethod
    def poll(cls, context):
        return plasticity_client.connected and not plasticity_client.subscribed

    def execute(self, context):
        plasticity_client.subscribe_all()
        return {'FINISHED'}


class UnsubscribeAllButton(bpy.types.Operator):
    bl_idname = "wm.unsubscribe_all"
    bl_label = "Unsubscribe All"
    bl_description = "Stop live updates from Plasticity"

    @classmethod
    def poll(cls, context):
        return plasticity_client.connected and plasticity_client.subscribed

    def execute(self, context):
        plasticity_client.unsubscribe_all()
        return {'FINISHED'}

class RefacetButton(bpy.types.Operator):
    bl_idname = "wm.refacet"
    bl_label = "Refacet"
    bl_description = "Refacet selected Plasticity objects using current settings"

    @classmethod
    def poll(cls, context):
        if not plasticity_client.connected:
            return False
        if context.window_manager.plasticity_busy:
            return False

        return any("plasticity_id" in obj.keys() for obj in context.selected_objects)

    def execute(self, context):

        context.window_manager.plasticity_busy = True

        if len(context.scene.refacet_presets) > 0:
            preset = context.scene.refacet_presets[context.scene.active_refacet_preset_index]

            curve_chord_tolerance = preset.tolerance
            surface_plane_tolerance = preset.tolerance
            curve_chord_angle = preset.angle
            surface_plane_angle = preset.angle
            facet_tri_or_ngon = preset.facet_tri_or_ngon
        else:
            curve_chord_tolerance = context.scene.prop_plasticity_facet_tolerance
            surface_plane_tolerance = context.scene.prop_plasticity_facet_tolerance
            curve_chord_angle = context.scene.prop_plasticity_facet_angle
            surface_plane_angle = context.scene.prop_plasticity_facet_angle
            facet_tri_or_ngon = context.scene.prop_plasticity_facet_tri_or_ngon

        if facet_tri_or_ngon == "TRI":
            max_sides = 3
        elif facet_tri_or_ngon == "QUAD":
            max_sides = 4
        else:
            max_sides = 128
        plane_angle = math.pi / 4.0 if (max_sides > 4) else 0
        shape = FacetShapeType.CUT
        convex_ngons_only = False
        curve_max_length_enabled = False
        curve_max_length = 0.0
        relative_to_bbox = True
        match_topology = True

        min_width = 0
        max_width = 0
        curve_chord_max = 0

        if context.scene.prop_plasticity_ui_show_advanced_facet:            
            if len(context.scene.refacet_presets) > 0: 
                surface_plane_tolerance = preset.Face_plane_tolerance
                surface_plane_angle = preset.Face_Angle_tolerance
                curve_chord_tolerance = preset.Edge_chord_tolerance
                curve_chord_angle = preset.Edge_Angle_tolerance
                min_width = preset.min_width if preset.min_width_enabled else 0
                max_width = preset.max_width if preset.max_width_enabled else 0
                plane_angle = preset.plane_angle
                convex_ngons_only = preset.convex_ngons_only
                curve_max_length_enabled = preset.curve_max_length_enabled
                curve_max_length = preset.curve_max_length
                relative_to_bbox = preset.relative_to_bbox
                match_topology = preset.match_topology
            else:
                surface_plane_tolerance = context.scene.prop_plasticity_surface_plane_tolerance
                surface_plane_angle = context.scene.prop_plasticity_surface_angle_tolerance
                curve_chord_tolerance = context.scene.prop_plasticity_curve_chord_tolerance            
                curve_chord_angle = context.scene.prop_plasticity_curve_angle_tolerance                
                min_width = (
                    context.scene.prop_plasticity_facet_min_width
                    if context.scene.prop_plasticity_facet_min_width_enabled
                    else 0
                )
                max_width = (
                    context.scene.prop_plasticity_facet_max_width
                    if context.scene.prop_plasticity_facet_max_width_enabled
                    else 0
                )
                plane_angle = context.scene.prop_plasticity_plane_angle
                convex_ngons_only = context.scene.prop_plasticity_convex_ngons_only
                curve_max_length_enabled = context.scene.prop_plasticity_curve_max_length_enabled
                curve_max_length = context.scene.prop_plasticity_curve_max_length
                relative_to_bbox = context.scene.prop_plasticity_relative_to_bbox
                match_topology = context.scene.prop_plasticity_match_topology
            if max_width > 0 and min_width > 0 and max_width < min_width:
                max_width = min_width

            if max_width > 0:
                curve_chord_max = max_width * math.sqrt(0.5)
            if curve_max_length_enabled:
                curve_chord_max = curve_max_length
            if convex_ngons_only and max_sides > 4:
                shape = FacetShapeType.CONVEX

        plasticity_ids_by_filename = {}
        
        for obj in context.selected_objects:
            if "plasticity_filename" in obj.keys():
                if obj["plasticity_filename"] not in plasticity_ids_by_filename.keys():
                    plasticity_ids_by_filename[obj["plasticity_filename"]] = []
                plasticity_ids_by_filename[obj["plasticity_filename"]].append(
                    obj["plasticity_id"])

        for filename, plasticity_ids in plasticity_ids_by_filename.items():
            plasticity_client.refacet_some(filename,
                                           plasticity_ids,
                                           relative_to_bbox=relative_to_bbox,
                                           curve_chord_tolerance=curve_chord_tolerance,
                                           curve_chord_angle=curve_chord_angle,
                                           surface_plane_tolerance=surface_plane_tolerance,
                                           surface_plane_angle=surface_plane_angle,
                                           match_topology=match_topology,
                                           max_sides=max_sides,
                                           plane_angle=plane_angle,
                                           min_width=min_width,
                                           max_width=max_width,
                                           curve_chord_max=curve_chord_max,
                                           shape=shape)

        return {'FINISHED'}

class PlasticityPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_plasticity_panel"
    bl_label = "Plasticity"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Plasticity'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        if plasticity_client.connected:
            disconnect_button = layout.operator(
                "wm.disconnect_button", text="Disconnect")
            layout.label(text="Connected to " + plasticity_client.server)
        else:
            box = layout.box()
            connect_button = box.operator(
                "wm.connect_button", text="Connect")
            box.prop(scene, "prop_plasticity_server", text="Server")

        if plasticity_client.connected:
            if plasticity_client.filename:
                layout.label(text="Filename: " + plasticity_client.filename)

            layout.separator()

            tabs_row = layout.row()
            split = tabs_row.split(factor=0.1)
            tabs_col = split.column(align=True)
            layout = split.column()

            tabs_col.prop_enum(scene, "prop_plasticity_ui_tab", "PINNED", text="", icon="PINNED")
            tabs_col.prop_enum(scene, "prop_plasticity_ui_tab", "MAIN", text="", icon="LINKED")
            tabs_col.prop_enum(scene, "prop_plasticity_ui_tab", "REFACET", text="", icon="MOD_REMESH")
            tabs_col.prop_enum(scene, "prop_plasticity_ui_tab", "UTILITIES", text="", icon="TOOL_SETTINGS")
            tabs_col.prop_enum(scene, "prop_plasticity_ui_tab", "UV_TOOLS", text="", icon="UV")
            tabs_col.prop_enum(scene, "prop_plasticity_ui_tab", "MESH_TOOLS", text="", icon="MESH_CUBE")
            tabs_col.prop_enum(scene, "prop_plasticity_ui_tab", "PREFERENCES", text="", icon="PREFERENCES")

            active_tab = scene.prop_plasticity_ui_tab
            tab_labels = {
                "PINNED": "Pinned",
                "MAIN": "Main",
                "REFACET": "Refacet",
                "UTILITIES": "Utilities",
                "UV_TOOLS": "UV / Material / Texture Tools",
                "MESH_TOOLS": "Mesh Tools",
                "PREFERENCES": "Preferences",
            }
            layout.label(text=tab_labels.get(active_tab, active_tab))

            pin_props = (
                "prop_plasticity_pin_live_link",
                "prop_plasticity_pin_refresh",
                "prop_plasticity_pin_only_visible",
                "prop_plasticity_pin_only_selected",
                "prop_plasticity_pin_scale",
                "prop_plasticity_pin_refacet",
                "prop_plasticity_pin_auto_mark_edges",
                "prop_plasticity_pin_merge_uv_seams",
                "prop_plasticity_pin_select_faces",
                "prop_plasticity_pin_select_edges",
                "prop_plasticity_pin_paint_faces",
                "prop_plasticity_pin_live_expand",
                "prop_plasticity_pin_live_expand_auto_circle",
                "prop_plasticity_pin_live_expand_interval",
                "prop_plasticity_pin_live_expand_auto_merge_seams",
                "prop_plasticity_pin_auto_seam_mode",
                "prop_plasticity_pin_auto_cylinder_seam_mode",
                "prop_plasticity_pin_auto_cylinder_partial_angle",
                "prop_plasticity_pin_auto_cylinder_seam_occluded_only",
                "prop_plasticity_pin_relax_uvs",
                "prop_plasticity_pin_select_adjacent_fillets",
                "prop_plasticity_pin_select_fillet_min_curvature_angle",
                "prop_plasticity_pin_select_fillet_max_area_ratio",
                "prop_plasticity_pin_select_fillet_min_adjacent_groups",
                "prop_plasticity_pin_select_include_vertex_adjacency",
                "prop_plasticity_pin_select_vertex_adjacent_max_length_ratio",
                "prop_plasticity_pin_live_expand_edge_highlight",
                "prop_plasticity_pin_live_expand_active_view_only",
                "prop_plasticity_pin_live_expand_edge_occlude",
                "prop_plasticity_pin_live_expand_edge_thickness",
                "prop_plasticity_pin_live_expand_overlay_color",
                "prop_plasticity_pin_uv_unwrap",
                "prop_plasticity_pin_uv_pack_islands",
                "prop_plasticity_pin_uv_open_editor",
                "prop_plasticity_pin_uv_close_editor",
                "prop_plasticity_pin_uv_select_without_uvs",
                "prop_plasticity_pin_uv_remove_uvs",
                "prop_plasticity_pin_uv_remove_materials",
                "prop_plasticity_pin_uv_reload_textures",
                "prop_plasticity_pin_uv_assign_checker",
                "prop_plasticity_pin_uv_remove_checker",
                "prop_plasticity_pin_mesh_select_similar",
                "prop_plasticity_pin_mesh_join",
                "prop_plasticity_pin_mesh_unjoin",
                "prop_plasticity_pin_mesh_merge_nonoverlapping",
                "prop_plasticity_pin_mesh_overlap_threshold",
                "prop_plasticity_pin_mesh_select_ngons",
                "prop_plasticity_pin_mesh_mirror",
                "prop_plasticity_pin_mesh_mirror_axis",
                "prop_plasticity_pin_mesh_mirror_center",
                "prop_plasticity_pin_mesh_remove_modifiers",
                "prop_plasticity_pin_mesh_apply_modifiers",
                "prop_plasticity_pin_mesh_remove_vertex_groups",
                "prop_plasticity_pin_mesh_snap_cursor",
                "prop_plasticity_pin_mesh_import_fbx",
                "prop_plasticity_pin_mesh_export_fbx",
                "prop_plasticity_pin_mesh_import_obj",
                "prop_plasticity_pin_mesh_export_obj",
            )
            show_pins = any(getattr(scene, prop) for prop in pin_props)
            if active_tab == "PINNED":
                pin_box = layout.box()
                pin_col = pin_box.column(align=True)
                if not show_pins:
                    pin_col.label(text="No pinned items yet.")
            if active_tab == "PINNED" and show_pins:
                if scene.prop_plasticity_pin_live_link:
                    row = pin_col.row(align=True)
                    if not plasticity_client.subscribed:
                        row.operator("wm.subscribe_all", text="Live link")
                    else:
                        row.operator("wm.unsubscribe_all", text="Disable live link")
                    row.prop(scene, "prop_plasticity_pin_live_link",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_link"), emboss=False)
                if scene.prop_plasticity_pin_refresh:
                    row = pin_col.row(align=True)
                    row.operator("wm.list", text="Refresh")
                    row.prop(scene, "prop_plasticity_pin_refresh",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_refresh"), emboss=False)
                if scene.prop_plasticity_pin_only_visible:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_list_only_visible",
                             text="Only visible in Plasticity")
                    row.prop(scene, "prop_plasticity_pin_only_visible",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_only_visible"), emboss=False)
                if scene.prop_plasticity_pin_only_selected:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_list_only_selected",
                             text="Only selected objects in Blender")
                    row.prop(scene, "prop_plasticity_pin_only_selected",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_only_selected"), emboss=False)
                if scene.prop_plasticity_pin_scale:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_unit_scale",
                             text="Scale", slider=True)
                    row.prop(scene, "prop_plasticity_pin_scale",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_scale"), emboss=False)
                if scene.prop_plasticity_pin_refacet:
                    row = pin_col.row(align=True)
                    row.operator("wm.refacet", text="Refacet")
                    row.prop(scene, "prop_plasticity_pin_refacet",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_refacet"), emboss=False)
                if scene.prop_plasticity_pin_auto_mark_edges:
                    row = pin_col.row(align=True)
                    row.operator("mesh.auto_mark_edges", text="Auto Mark Edges")
                    row.prop(scene, "prop_plasticity_pin_auto_mark_edges",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_auto_mark_edges"), emboss=False)
                if scene.prop_plasticity_pin_merge_uv_seams:
                    row = pin_col.row(align=True)
                    row.operator("mesh.merge_uv_seams", text="Merge UV Seams")
                    row.prop(scene, "prop_plasticity_pin_merge_uv_seams",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_merge_uv_seams"), emboss=False)
                if scene.prop_plasticity_pin_select_faces:
                    row = pin_col.row(align=True)
                    row.operator("mesh.select_by_plasticity_face_id",
                                 text="Select Plasticity Face(s)")
                    row.prop(scene, "prop_plasticity_pin_select_faces",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_faces"), emboss=False)
                if scene.prop_plasticity_pin_select_edges:
                    row = pin_col.row(align=True)
                    row.operator("mesh.select_by_plasticity_face_id_edge",
                                 text="Select Plasticity Edges")
                    row.prop(scene, "prop_plasticity_pin_select_edges",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_edges"), emboss=False)
                if scene.prop_plasticity_pin_paint_faces:
                    row = pin_col.row(align=True)
                    row.operator("mesh.paint_plasticity_faces",
                                 text="Paint Plasticity Faces")
                    row.prop(scene, "prop_plasticity_pin_paint_faces",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_paint_faces"), emboss=False)
                if scene.prop_plasticity_pin_live_expand:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand", text="Live Expand Selection")
                    row.prop(scene, "prop_plasticity_pin_live_expand",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand"), emboss=False)
                if scene.prop_plasticity_pin_live_expand_auto_circle:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand_auto_circle", text="Auto Circle Select Mode")
                    row.prop(scene, "prop_plasticity_pin_live_expand_auto_circle",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_auto_circle"), emboss=False)
                if scene.prop_plasticity_pin_live_expand_interval:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand_interval", text="Update Interval")
                    row.prop(scene, "prop_plasticity_pin_live_expand_interval",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_interval"), emboss=False)
                if scene.prop_plasticity_pin_live_expand_auto_merge_seams:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand_auto_merge_seams", text="Auto Merge / Reset Seams on Selection")
                    row.prop(scene, "prop_plasticity_pin_live_expand_auto_merge_seams",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_auto_merge_seams"), emboss=False)
                if scene.prop_plasticity_pin_auto_seam_mode:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_auto_seam_mode", text="Auto Create Seam")
                    row.prop(scene, "prop_plasticity_pin_auto_seam_mode",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_auto_seam_mode"), emboss=False)
                if scene.prop_plasticity_pin_auto_cylinder_seam_mode:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_auto_cylinder_seam_mode", text="Cylinder Seam Mode")
                    row.prop(scene, "prop_plasticity_pin_auto_cylinder_seam_mode",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_auto_cylinder_seam_mode"), emboss=False)
                if scene.prop_plasticity_pin_auto_cylinder_partial_angle:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_auto_cylinder_partial_angle", text="Partial Wrap Angle")
                    row.prop(scene, "prop_plasticity_pin_auto_cylinder_partial_angle",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_auto_cylinder_partial_angle"), emboss=False)
                if scene.prop_plasticity_pin_auto_cylinder_seam_occluded_only:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_auto_cylinder_seam_occluded_only", text="Occluded Only (View)")
                    row.prop(scene, "prop_plasticity_pin_auto_cylinder_seam_occluded_only",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_auto_cylinder_seam_occluded_only"), emboss=False)
                if scene.prop_plasticity_pin_select_adjacent_fillets:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_select_adjacent_fillets", text="Select Adjacent Fillets")
                    row.prop(scene, "prop_plasticity_pin_select_adjacent_fillets",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_adjacent_fillets"), emboss=False)
                if scene.prop_plasticity_pin_select_fillet_min_curvature_angle:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_select_fillet_min_curvature_angle", text="Min Curvature Angle")
                    row.prop(scene, "prop_plasticity_pin_select_fillet_min_curvature_angle",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_fillet_min_curvature_angle"), emboss=False)
                if scene.prop_plasticity_pin_select_fillet_max_area_ratio:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_select_fillet_max_area_ratio", text="Max Area Ratio")
                    row.prop(scene, "prop_plasticity_pin_select_fillet_max_area_ratio",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_fillet_max_area_ratio"), emboss=False)
                if scene.prop_plasticity_pin_select_fillet_min_adjacent_groups:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_select_fillet_min_adjacent_groups", text="Min Adjacent Groups")
                    row.prop(scene, "prop_plasticity_pin_select_fillet_min_adjacent_groups",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_fillet_min_adjacent_groups"), emboss=False)
                if scene.prop_plasticity_pin_select_include_vertex_adjacency:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_select_include_vertex_adjacency", text="Include Vertex Adjacent")
                    row.prop(scene, "prop_plasticity_pin_select_include_vertex_adjacency",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_include_vertex_adjacency"), emboss=False)
                if scene.prop_plasticity_pin_select_vertex_adjacent_max_length_ratio:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_select_vertex_adjacent_max_length_ratio", text="Max Vertex Adjacent Length Ratio")
                    row.prop(scene, "prop_plasticity_pin_select_vertex_adjacent_max_length_ratio",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_vertex_adjacent_max_length_ratio"), emboss=False)
                if scene.prop_plasticity_pin_live_expand_edge_highlight:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand_edge_highlight", text="Plasticity Edge Highlight")
                    row.prop(scene, "prop_plasticity_pin_live_expand_edge_highlight",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_edge_highlight"), emboss=False)
                if scene.prop_plasticity_pin_live_expand_active_view_only:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand_active_view_only", text="Active View Only")
                    row.prop(scene, "prop_plasticity_pin_live_expand_active_view_only",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_active_view_only"), emboss=False)
                if scene.prop_plasticity_pin_live_expand_edge_occlude:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand_edge_occlude", text="Occlude Hidden Edges")
                    row.prop(scene, "prop_plasticity_pin_live_expand_edge_occlude",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_edge_occlude"), emboss=False)
                if scene.prop_plasticity_pin_live_expand_edge_thickness:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand_edge_thickness", text="Plasticity Edge Highlight Thickness")
                    row.prop(scene, "prop_plasticity_pin_live_expand_edge_thickness",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_edge_thickness"), emboss=False)
                if scene.prop_plasticity_pin_live_expand_overlay_color:
                    row = pin_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand_overlay_color", text="Plasticity Edge Highlight Color")
                    row.prop(scene, "prop_plasticity_pin_live_expand_overlay_color",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_overlay_color"), emboss=False)
                if scene.prop_plasticity_pin_uv_unwrap:
                    row = pin_col.row(align=True)
                    row.operator("mesh.auto_unwrap_plasticity", text="Unwrap")
                    row.prop(scene, "prop_plasticity_pin_uv_unwrap",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_unwrap"), emboss=False)
                if scene.prop_plasticity_pin_uv_pack_islands:
                    row = pin_col.row(align=True)
                    row.operator("mesh.pack_uv_islands_plasticity", text="Pack UV Islands")
                    row.prop(scene, "prop_plasticity_pin_uv_pack_islands",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_pack_islands"), emboss=False)
                if scene.prop_plasticity_pin_relax_uvs:
                    row = pin_col.row(align=True)
                    op_row = row.row(align=True)
                    op_row.enabled = context.mode == 'EDIT_MESH'
                    op_row.operator("mesh.relax_uvs_plasticity", text="Relax UVs")
                    row.prop(scene, "prop_plasticity_pin_relax_uvs",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_relax_uvs"), emboss=False)
                if scene.prop_plasticity_pin_uv_open_editor:
                    row = pin_col.row(align=True)
                    row.operator("object.open_uv_editor", text="Open Selected Inside UV Editor")
                    row.prop(scene, "prop_plasticity_pin_uv_open_editor",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_open_editor"), emboss=False)
                if scene.prop_plasticity_pin_uv_close_editor:
                    row = pin_col.row(align=True)
                    row.operator("object.close_uv_editor", text="Close UV Editor")
                    row.prop(scene, "prop_plasticity_pin_uv_close_editor",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_close_editor"), emboss=False)
                if scene.prop_plasticity_pin_uv_select_without_uvs:
                    row = pin_col.row(align=True)
                    row.operator("object.select_without_uvs", text="Select Objects Without UVs")
                    row.prop(scene, "prop_plasticity_pin_uv_select_without_uvs",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_select_without_uvs"), emboss=False)
                if scene.prop_plasticity_pin_uv_remove_uvs:
                    row = pin_col.row(align=True)
                    row.operator("object.remove_uvs_from_selected", text="Remove UVs from Selected Objects")
                    row.prop(scene, "prop_plasticity_pin_uv_remove_uvs",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_remove_uvs"), emboss=False)
                if scene.prop_plasticity_pin_uv_remove_materials:
                    row = pin_col.row(align=True)
                    row.operator("object.remove_materials", text="Remove Materials")
                    row.prop(scene, "prop_plasticity_pin_uv_remove_materials",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_remove_materials"), emboss=False)
                if scene.prop_plasticity_pin_uv_reload_textures:
                    row = pin_col.row(align=True)
                    row.operator("object.reload_textures", text="Reload Textures")
                    row.prop(scene, "prop_plasticity_pin_uv_reload_textures",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_reload_textures"), emboss=False)
                if scene.prop_plasticity_pin_uv_assign_checker:
                    row = pin_col.row(align=True)
                    row.operator("object.assign_uv_checker_texture", text="Assign Checker Texture")
                    row.prop(scene, "prop_plasticity_pin_uv_assign_checker",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_assign_checker"), emboss=False)
                if scene.prop_plasticity_pin_uv_remove_checker:
                    row = pin_col.row(align=True)
                    row.operator("object.remove_uv_checker_nodes", text="Remove Checker Nodes")
                    row.prop(scene, "prop_plasticity_pin_uv_remove_checker",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_remove_checker"), emboss=False)
                if scene.prop_plasticity_pin_mesh_select_similar:
                    row = pin_col.row(align=True)
                    row.operator("object.select_similar_geometry", text="Select Similar Geometry")
                    row.prop(scene, "prop_plasticity_pin_mesh_select_similar",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_select_similar"), emboss=False)
                if scene.prop_plasticity_pin_mesh_join:
                    row = pin_col.row(align=True)
                    row.operator("object.join_selected", text="Join Selected")
                    row.prop(scene, "prop_plasticity_pin_mesh_join",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_join"), emboss=False)
                if scene.prop_plasticity_pin_mesh_unjoin:
                    row = pin_col.row(align=True)
                    row.operator("object.unjoin_selected", text="Unjoin Selected")
                    row.prop(scene, "prop_plasticity_pin_mesh_unjoin",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_unjoin"), emboss=False)
                if scene.prop_plasticity_pin_mesh_merge_nonoverlapping:
                    row = pin_col.row(align=True)
                    op = row.operator("object.merge_nonoverlapping_meshes", text="Merge Non-overlapping Meshes")
                    op.overlap_threshold = scene.overlap_threshold
                    row.prop(scene, "prop_plasticity_pin_mesh_merge_nonoverlapping",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_merge_nonoverlapping"), emboss=False)
                if scene.prop_plasticity_pin_mesh_overlap_threshold:
                    row = pin_col.row(align=True)
                    row.prop(scene, "overlap_threshold", text="Overlap Threshold")
                    row.prop(scene, "prop_plasticity_pin_mesh_overlap_threshold",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_overlap_threshold"), emboss=False)
                if scene.prop_plasticity_pin_mesh_select_ngons:
                    row = pin_col.row(align=True)
                    row.operator("object.select_meshes_with_ngons", text="Select Meshes with Ngons")
                    row.prop(scene, "prop_plasticity_pin_mesh_select_ngons",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_select_ngons"), emboss=False)
                if scene.prop_plasticity_pin_mesh_mirror:
                    row = pin_col.row(align=True)
                    row.operator("object.mirror", text="Mirror Selected")
                    row.prop(scene, "prop_plasticity_pin_mesh_mirror",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_mirror"), emboss=False)
                if scene.prop_plasticity_pin_mesh_mirror_axis:
                    row = pin_col.row(align=True)
                    row.prop(scene, "mirror_axis", text="Mirror Axis")
                    row.prop(scene, "prop_plasticity_pin_mesh_mirror_axis",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_mirror_axis"), emboss=False)
                if scene.prop_plasticity_pin_mesh_mirror_center:
                    row = pin_col.row(align=True)
                    row.prop(scene, "mirror_center_object", text="Mirror Center")
                    row.prop(scene, "prop_plasticity_pin_mesh_mirror_center",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_mirror_center"), emboss=False)
                if scene.prop_plasticity_pin_mesh_remove_modifiers:
                    row = pin_col.row(align=True)
                    row.operator("object.remove_modifiers", text="Remove Modifiers")
                    row.prop(scene, "prop_plasticity_pin_mesh_remove_modifiers",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_remove_modifiers"), emboss=False)
                if scene.prop_plasticity_pin_mesh_apply_modifiers:
                    row = pin_col.row(align=True)
                    row.operator("object.apply_modifiers", text="Apply Modifiers")
                    row.prop(scene, "prop_plasticity_pin_mesh_apply_modifiers",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_apply_modifiers"), emboss=False)
                if scene.prop_plasticity_pin_mesh_remove_vertex_groups:
                    row = pin_col.row(align=True)
                    row.operator("object.remove_vertex_groups", text="Remove Vertex Groups")
                    row.prop(scene, "prop_plasticity_pin_mesh_remove_vertex_groups",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_remove_vertex_groups"), emboss=False)
                if scene.prop_plasticity_pin_mesh_snap_cursor:
                    row = pin_col.row(align=True)
                    row.operator("object.snap_to_cursor", text="Snap to 3D Cursor")
                    row.prop(scene, "prop_plasticity_pin_mesh_snap_cursor",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_snap_cursor"), emboss=False)
                if scene.prop_plasticity_pin_mesh_import_fbx:
                    row = pin_col.row(align=True)
                    row.operator("object.import_fbx", text="Import FBX")
                    row.prop(scene, "prop_plasticity_pin_mesh_import_fbx",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_import_fbx"), emboss=False)
                if scene.prop_plasticity_pin_mesh_export_fbx:
                    row = pin_col.row(align=True)
                    row.operator("object.export_fbx", text="Export FBX")
                    row.prop(scene, "prop_plasticity_pin_mesh_export_fbx",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_export_fbx"), emboss=False)
                if scene.prop_plasticity_pin_mesh_import_obj:
                    row = pin_col.row(align=True)
                    row.operator("object.import_obj", text="Import OBJ")
                    row.prop(scene, "prop_plasticity_pin_mesh_import_obj",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_import_obj"), emboss=False)
                if scene.prop_plasticity_pin_mesh_export_obj:
                    row = pin_col.row(align=True)
                    row.operator("object.export_obj", text="Export OBJ")
                    row.prop(scene, "prop_plasticity_pin_mesh_export_obj",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_export_obj"), emboss=False)

            if active_tab == "PINNED":
                pass
            elif active_tab == "MAIN":
                row = layout.row(align=True)
                if not plasticity_client.subscribed:
                    row.operator("wm.subscribe_all", text="Live link")
                else:
                    row.operator("wm.unsubscribe_all", text="Disable live link")
                row.prop(scene, "prop_plasticity_pin_live_link",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_link"), emboss=False)

                box = layout.box()
                row = box.row(align=True)
                row.operator("wm.list", text="Refresh")
                row.prop(scene, "prop_plasticity_pin_refresh",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_refresh"), emboss=False)
                row = box.row(align=True)
                row.prop(scene, "prop_plasticity_list_only_visible",
                         text="Only visible in Plasticity")
                row.prop(scene, "prop_plasticity_pin_only_visible",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_only_visible"), emboss=False)
                row = box.row(align=True)
                row.prop(scene, "prop_plasticity_list_only_selected",
                         text="Only selected objects in Blender")
                row.prop(scene, "prop_plasticity_pin_only_selected",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_only_selected"), emboss=False)
                row = box.row(align=True)
                row.prop(scene, "prop_plasticity_unit_scale",
                         text="Scale", slider=True)
                row.prop(scene, "prop_plasticity_pin_scale",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_scale"), emboss=False)

            elif active_tab == "REFACET":
                box = layout.box()
                col = box.column(align=True)
                row = col.row(align=True)
                row.operator("wm.refacet", text="Refacet")
                row.prop(scene, "prop_plasticity_pin_refacet",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_refacet"), emboss=False)
                if context.mode == 'OBJECT':
                    row = col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_refacet_only_selected", text="Only Selected")
                    row = col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_refacet", text="Live Refacet Mode")
                    if scene.prop_plasticity_live_refacet:
                        live_col = col.column(align=True)
                        live_col.prop(scene, "prop_plasticity_live_refacet_interval", text="Update Interval")
                col.label(text="Refacet Presets")

                row = col.row()
                row.template_list("OBJECT_UL_RefacetPresetsList", "refacet_presets", context.scene, "refacet_presets", context.scene, "active_refacet_preset_index")

                preset_col = row.column(align=True)
                preset_col.operator("refacet_preset.add", icon='ADD', text="")
                preset_col.operator("refacet_preset.remove", icon='REMOVE', text="")

                if len(scene.refacet_presets) > 0:
                    preset = context.scene.refacet_presets[context.scene.active_refacet_preset_index]
                    col.prop(preset, 'facet_tri_or_ngon', text="Facet Type", expand=True)
                else:
                    col.prop(scene, "prop_plasticity_facet_tri_or_ngon", text="Facet Type", expand=True)

                if len(scene.refacet_presets) > 0:
                    col.prop(preset, 'density', text="Density", slider=True)
                    col.prop(preset, 'tolerance', text="Tolerance")
                    col.prop(preset, 'angle', text="Angle")
                else:
                    col.prop(scene, "prop_plasticity_facet_density", text="Density", slider=True)
                    col.prop(scene, "prop_plasticity_facet_tolerance", text="Tolerance")
                    col.prop(scene, "prop_plasticity_facet_angle", text="Angle")

                col.prop(
                    context.scene,
                    "prop_plasticity_ui_show_advanced_facet",
                    icon="TRIA_DOWN" if context.scene.prop_plasticity_ui_show_advanced_facet else "TRIA_RIGHT",
                    toggle=True,
                    text="Advanced Settings",
                )

                if len(context.scene.refacet_presets) > 0:
                    preset = context.scene.refacet_presets[context.scene.active_refacet_preset_index]

                if context.scene.prop_plasticity_ui_show_advanced_facet:
                    adv_box = col.box()
                    adv_col = adv_box.column(align=True)
                    if len(scene.refacet_presets) > 0:
                        min_row = adv_col.row(align=True)
                        min_row.prop(preset, 'min_width_enabled', text="Min Width")
                        min_val = min_row.row(align=True)
                        min_val.enabled = preset.min_width_enabled
                        min_val.prop(preset, 'min_width', text="")
                        max_row = adv_col.row(align=True)
                        max_row.prop(preset, 'max_width_enabled', text="Max Width")
                        max_val = max_row.row(align=True)
                        max_val.enabled = preset.max_width_enabled
                        max_val.prop(preset, 'max_width', text="")
                        adv_col.prop(preset, 'Edge_chord_tolerance', text="Edge Chord Tolerance")
                        adv_col.prop(preset, 'Edge_Angle_tolerance', text="Edge Angle Tolerance")
                        adv_col.prop(preset, 'Face_plane_tolerance', text="Face Plane Tolerance")
                        adv_col.prop(preset, 'Face_Angle_tolerance', text="Face Angle Tolerance")
                        adv_col.prop(preset, 'plane_angle', text="Plane Angle")
                        adv_col.prop(preset, 'relative_to_bbox', text="Relative to BBox")
                        adv_col.prop(preset, 'match_topology', text="Match Topology")
                        adv_col.prop(preset, 'convex_ngons_only', text="Convex Ngons Only")
                        curve_box = adv_col.box()
                        curve_box.prop(preset, 'curve_max_length_enabled', text="Curve Max Length")
                        curve_value = curve_box.column()
                        curve_value.enabled = preset.curve_max_length_enabled
                        curve_value.prop(preset, 'curve_max_length', text="")
                    else:
                        min_row = adv_col.row(align=True)
                        min_row.prop(scene, "prop_plasticity_facet_min_width_enabled", text="Min Width")
                        min_val = min_row.row(align=True)
                        min_val.enabled = scene.prop_plasticity_facet_min_width_enabled
                        min_val.prop(scene, "prop_plasticity_facet_min_width", text="")
                        max_row = adv_col.row(align=True)
                        max_row.prop(scene, "prop_plasticity_facet_max_width_enabled", text="Max Width")
                        max_val = max_row.row(align=True)
                        max_val.enabled = scene.prop_plasticity_facet_max_width_enabled
                        max_val.prop(scene, "prop_plasticity_facet_max_width", text="")
                        adv_col.prop(scene, "prop_plasticity_curve_chord_tolerance", text="Edge Chord Tolerance")
                        adv_col.prop(scene, "prop_plasticity_curve_angle_tolerance", text="Edge Angle Tolerance")
                        adv_col.prop(scene, "prop_plasticity_surface_plane_tolerance", text="Face Plane Tolerance")
                        adv_col.prop(scene, "prop_plasticity_surface_angle_tolerance", text="Face Angle Tolerance")
                        adv_col.prop(scene, "prop_plasticity_plane_angle", text="Plane Angle")
                        adv_col.prop(scene, "prop_plasticity_relative_to_bbox", text="Relative to BBox")
                        adv_col.prop(scene, "prop_plasticity_match_topology", text="Match Topology")
                        adv_col.prop(scene, "prop_plasticity_convex_ngons_only", text="Convex Ngons Only")
                        curve_box = adv_col.box()
                        curve_box.prop(scene, "prop_plasticity_curve_max_length_enabled", text="Curve Max Length")
                        curve_value = curve_box.column()
                        curve_value.enabled = scene.prop_plasticity_curve_max_length_enabled
                        curve_value.prop(scene, "prop_plasticity_curve_max_length", text="")
    
            elif active_tab == "UTILITIES":
                box = layout.box()
                col = box.column(align=True)

                auto_box = col.box()
                auto_box.prop(
                    scene,
                    "prop_plasticity_ui_util_auto_mark_edges",
                    text="Auto Mark Edges",
                    icon="TRIA_DOWN" if scene.prop_plasticity_ui_util_auto_mark_edges else "TRIA_RIGHT",
                    emboss=False,
                )
                if scene.prop_plasticity_ui_util_auto_mark_edges:
                    auto_col = auto_box.column(align=True)
                    row = auto_col.row(align=True)
                    row.operator("mesh.auto_mark_edges", text="Auto Mark Edges")
                    row.prop(scene, "prop_plasticity_pin_auto_mark_edges",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_auto_mark_edges"), emboss=False)

                merge_box = col.box()
                merge_box.prop(
                    scene,
                    "prop_plasticity_ui_util_merge_uv_seams",
                    text="Merge UV Seams",
                    icon="TRIA_DOWN" if scene.prop_plasticity_ui_util_merge_uv_seams else "TRIA_RIGHT",
                    emboss=False,
                )
                if scene.prop_plasticity_ui_util_merge_uv_seams:
                    merge_col = merge_box.column(align=True)
                    row = merge_col.row(align=True)
                    row.operator("mesh.merge_uv_seams", text="Merge UV Seams")
                    row.prop(scene, "prop_plasticity_pin_merge_uv_seams",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_merge_uv_seams"), emboss=False)
                    row = merge_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand_auto_merge_seams",
                             text="Auto Merge / Reset Seams on Selection")
                    row.prop(scene, "prop_plasticity_pin_live_expand_auto_merge_seams",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_auto_merge_seams"), emboss=False)
                    row = merge_col.row(align=True)
                    row.prop(scene, "prop_plasticity_auto_seam_mode",
                             text="Auto Create Seam")
                    row.prop(scene, "prop_plasticity_pin_auto_seam_mode",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_auto_seam_mode"), emboss=False)
                    cylinder_col = merge_col.column(align=True)
                    cylinder_col.enabled = scene.prop_plasticity_auto_seam_mode == 'CYLINDER'
                    row = cylinder_col.row(align=True)
                    row.prop(scene, "prop_plasticity_auto_cylinder_seam_mode",
                             text="Cylinder Seam Mode")
                    row.prop(scene, "prop_plasticity_pin_auto_cylinder_seam_mode",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_auto_cylinder_seam_mode"), emboss=False)
                    row = cylinder_col.row(align=True)
                    row.prop(scene, "prop_plasticity_auto_cylinder_partial_angle",
                             text="Partial Wrap Angle")
                    row.prop(scene, "prop_plasticity_pin_auto_cylinder_partial_angle",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_auto_cylinder_partial_angle"), emboss=False)
                    row = cylinder_col.row(align=True)
                    row.prop(scene, "prop_plasticity_auto_cylinder_seam_occluded_only",
                             text="Occluded Only (View)")
                    row.prop(scene, "prop_plasticity_pin_auto_cylinder_seam_occluded_only",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_auto_cylinder_seam_occluded_only"), emboss=False)

                faces_box = col.box()
                faces_box.prop(
                    scene,
                    "prop_plasticity_ui_util_select_faces",
                    text="Select Plasticity Face(s)",
                    icon="TRIA_DOWN" if scene.prop_plasticity_ui_util_select_faces else "TRIA_RIGHT",
                    emboss=False,
                )
                if scene.prop_plasticity_ui_util_select_faces:
                    faces_col = faces_box.column(align=True)
                    row = faces_col.row(align=True)
                    row.operator("mesh.select_by_plasticity_face_id",
                                 text="Select Plasticity Face(s)")
                    row.prop(scene, "prop_plasticity_pin_select_faces",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_faces"), emboss=False)
                    row = faces_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand",
                             text="Live Expand Selection")
                    row.prop(scene, "prop_plasticity_pin_live_expand",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand"), emboss=False)
                    if scene.prop_plasticity_live_expand:
                        expand_box = faces_col.box()
                        expand_col = expand_box.column(align=True)
                        row = expand_col.row(align=True)
                        row.prop(scene, "prop_plasticity_live_expand_auto_circle",
                                 text="Auto Circle Select Mode")
                        row.prop(scene, "prop_plasticity_pin_live_expand_auto_circle",
                                 text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_auto_circle"), emboss=False)
                        row = expand_col.row(align=True)
                        row.prop(scene, "prop_plasticity_live_expand_interval",
                                 text="Update Interval")
                        row.prop(scene, "prop_plasticity_pin_live_expand_interval",
                                 text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_interval"), emboss=False)
                        expand_col.label(text="Live Expand Selection Settings")
                        row = expand_col.row(align=True)
                        row.prop(scene, "prop_plasticity_select_adjacent_fillets",
                                 text="Select Adjacent Fillets")
                        row.prop(scene, "prop_plasticity_pin_select_adjacent_fillets",
                                 text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_adjacent_fillets"), emboss=False)
                        row = expand_col.row(align=True)
                        row.prop(scene, "prop_plasticity_select_fillet_min_curvature_angle",
                                 text="Min Curvature Angle")
                        row.prop(scene, "prop_plasticity_pin_select_fillet_min_curvature_angle",
                                 text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_fillet_min_curvature_angle"), emboss=False)
                        row = expand_col.row(align=True)
                        row.prop(scene, "prop_plasticity_select_fillet_max_area_ratio",
                                 text="Max Area Ratio")
                        row.prop(scene, "prop_plasticity_pin_select_fillet_max_area_ratio",
                                 text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_fillet_max_area_ratio"), emboss=False)
                        row = expand_col.row(align=True)
                        row.prop(scene, "prop_plasticity_select_fillet_min_adjacent_groups",
                                 text="Min Adjacent Groups")
                        row.prop(scene, "prop_plasticity_pin_select_fillet_min_adjacent_groups",
                                 text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_fillet_min_adjacent_groups"), emboss=False)
                        row = expand_col.row(align=True)
                        row.prop(scene, "prop_plasticity_select_include_vertex_adjacency",
                                 text="Include Vertex Adjacent")
                        row.prop(scene, "prop_plasticity_pin_select_include_vertex_adjacency",
                                 text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_include_vertex_adjacency"), emboss=False)
                        ratio_col = expand_col.column(align=True)
                        ratio_col.enabled = scene.prop_plasticity_select_include_vertex_adjacency
                        row = ratio_col.row(align=True)
                        row.prop(scene, "prop_plasticity_select_vertex_adjacent_max_length_ratio",
                                 text="Max Vertex Adjacent Length Ratio")
                        row.prop(scene, "prop_plasticity_pin_select_vertex_adjacent_max_length_ratio",
                                 text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_vertex_adjacent_max_length_ratio"), emboss=False)

                edges_box = col.box()
                edges_box.prop(
                    scene,
                    "prop_plasticity_ui_util_select_edges",
                    text="Select Plasticity Edges",
                    icon="TRIA_DOWN" if scene.prop_plasticity_ui_util_select_edges else "TRIA_RIGHT",
                    emboss=False,
                )
                if scene.prop_plasticity_ui_util_select_edges:
                    edges_col = edges_box.column(align=True)
                    row = edges_col.row(align=True)
                    row.operator("mesh.select_by_plasticity_face_id_edge",
                                 text="Select Plasticity Edges")
                    row.prop(scene, "prop_plasticity_pin_select_edges",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_select_edges"), emboss=False)

                paint_box = col.box()
                paint_box.prop(
                    scene,
                    "prop_plasticity_ui_util_paint_faces",
                    text="Paint Plasticity Faces",
                    icon="TRIA_DOWN" if scene.prop_plasticity_ui_util_paint_faces else "TRIA_RIGHT",
                    emboss=False,
                )
                if scene.prop_plasticity_ui_util_paint_faces:
                    paint_col = paint_box.column(align=True)
                    row = paint_col.row(align=True)
                    row.operator("mesh.paint_plasticity_faces",
                                 text="Paint Plasticity Faces")
                    row.prop(scene, "prop_plasticity_pin_paint_faces",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_paint_faces"), emboss=False)

                highlight_box = col.box()
                highlight_box.prop(
                    scene,
                    "prop_plasticity_ui_util_highlight",
                    text="Plasticity Edge Highlight",
                    icon="TRIA_DOWN" if scene.prop_plasticity_ui_util_highlight else "TRIA_RIGHT",
                    emboss=False,
                )
                if scene.prop_plasticity_ui_util_highlight:
                    highlight_col = highlight_box.column(align=True)
                    row = highlight_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand_edge_highlight",
                             text="Plasticity Edge Highlight")
                    row.prop(scene, "prop_plasticity_pin_live_expand_edge_highlight",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_edge_highlight"), emboss=False)
                    row = highlight_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand_active_view_only",
                             text="Active View Only")
                    row.prop(scene, "prop_plasticity_pin_live_expand_active_view_only",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_active_view_only"), emboss=False)
                    row = highlight_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand_edge_occlude",
                             text="Occlude Hidden Edges")
                    row.prop(scene, "prop_plasticity_pin_live_expand_edge_occlude",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_edge_occlude"), emboss=False)
                    row = highlight_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand_edge_thickness",
                             text="Plasticity Edge Highlight Thickness")
                    row.prop(scene, "prop_plasticity_pin_live_expand_edge_thickness",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_edge_thickness"), emboss=False)
                    row = highlight_col.row(align=True)
                    row.prop(scene, "prop_plasticity_live_expand_overlay_color",
                             text="Plasticity Edge Highlight Color")
                    row.prop(scene, "prop_plasticity_pin_live_expand_overlay_color",
                             text="", icon=_pin_icon(scene, "prop_plasticity_pin_live_expand_overlay_color"), emboss=False)
    
            elif active_tab == "UV_TOOLS":
                box = layout.box()
                col = box.column(align=True)
                row = col.row(align=True)
                row.operator("mesh.auto_unwrap_plasticity", text="Unwrap")
                row.prop(scene, "prop_plasticity_pin_uv_unwrap",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_unwrap"), emboss=False)
                row = col.row(align=True)
                row.operator("mesh.pack_uv_islands_plasticity", text="Pack UV Islands")
                row.prop(scene, "prop_plasticity_pin_uv_pack_islands",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_pack_islands"), emboss=False)
                row = col.row(align=True)
                op_row = row.row(align=True)
                op_row.enabled = context.mode == 'EDIT_MESH'
                op_row.operator("mesh.relax_uvs_plasticity", text="Relax UVs")
                row.prop(scene, "prop_plasticity_pin_relax_uvs",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_relax_uvs"), emboss=False)
                row = col.row(align=True)
                row.operator("object.open_uv_editor", text="Open Selected Inside UV Editor")
                row.prop(scene, "prop_plasticity_pin_uv_open_editor",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_open_editor"), emboss=False)
                row = col.row(align=True)
                row.operator("object.close_uv_editor", text="Close UV Editor")
                row.prop(scene, "prop_plasticity_pin_uv_close_editor",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_close_editor"), emboss=False)
                row = col.row(align=True)
                row.operator("object.select_without_uvs", text="Select Objects Without UVs")
                row.prop(scene, "prop_plasticity_pin_uv_select_without_uvs",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_select_without_uvs"), emboss=False)
                row = col.row(align=True)
                row.operator("object.remove_uvs_from_selected", text="Remove UVs from Selected Objects")
                row.prop(scene, "prop_plasticity_pin_uv_remove_uvs",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_remove_uvs"), emboss=False)
                row = col.row(align=True)
                row.operator("object.remove_materials", text="Remove Materials")
                row.prop(scene, "prop_plasticity_pin_uv_remove_materials",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_remove_materials"), emboss=False)
                row = col.row(align=True)
                row.operator("object.reload_textures", text="Reload Textures")
                row.prop(scene, "prop_plasticity_pin_uv_reload_textures",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_reload_textures"), emboss=False)
                row = col.row(align=True)
                row.operator("object.assign_uv_checker_texture", text="Assign Checker Texture")
                row.prop(scene, "prop_plasticity_pin_uv_assign_checker",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_assign_checker"), emboss=False)
                row = col.row(align=True)
                row.operator("object.remove_uv_checker_nodes", text="Remove Checker Nodes")
                row.prop(scene, "prop_plasticity_pin_uv_remove_checker",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_uv_remove_checker"), emboss=False)
                checker_col = col.column(align=True)
                checker_col.prop(scene, "prop_plasticity_checker_source", text="")
                checker_source = scene.prop_plasticity_checker_source
                if checker_source == "LIBRARY":
                    preview_col = checker_col.column(align=True)
                    preview_col.scale_y = 0.6
                    preview_col.template_icon_view(
                        scene, "prop_plasticity_checker_image", show_labels=False
                    )
                else:
                    row = checker_col.row(align=True)
                    path_label = scene.prop_plasticity_checker_custom_path or "No file selected"
                    row.label(text=path_label)
                    row.operator("object.select_checker_image", text="", icon="FILE_FOLDER")
    
            elif active_tab == "MESH_TOOLS":
                box = layout.box()
                col = box.column(align=True)
                row = col.row(align=True)
                row.operator("object.select_similar_geometry", text="Select Similar Geometry")
                row.prop(scene, "prop_plasticity_pin_mesh_select_similar",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_select_similar"), emboss=False)
                row = col.row(align=True)
                row.operator("object.join_selected", text="Join Selected")
                row.prop(scene, "prop_plasticity_pin_mesh_join",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_join"), emboss=False)
                row = col.row(align=True)
                row.operator("object.unjoin_selected", text="Unjoin Selected")
                row.prop(scene, "prop_plasticity_pin_mesh_unjoin",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_unjoin"), emboss=False)
                row = col.row(align=True)
                op = row.operator("object.merge_nonoverlapping_meshes", text="Merge Non-overlapping Meshes")
                op.overlap_threshold = scene.overlap_threshold
                row.prop(scene, "prop_plasticity_pin_mesh_merge_nonoverlapping",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_merge_nonoverlapping"), emboss=False)
                row = col.row(align=True)
                row.separator()
                row.prop(scene, "overlap_threshold", text="Overlap Threshold")
                row.prop(scene, "prop_plasticity_pin_mesh_overlap_threshold",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_overlap_threshold"), emboss=False)
                row = col.row(align=True)
                row.operator("object.select_meshes_with_ngons", text="Select Meshes with Ngons")
                row.prop(scene, "prop_plasticity_pin_mesh_select_ngons",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_select_ngons"), emboss=False)
                row = col.row(align=True)
                row.operator("object.mirror", text="Mirror Selected")
                row.prop(scene, "prop_plasticity_pin_mesh_mirror",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_mirror"), emboss=False)
                row = col.row(align=True)
                row.prop(scene, "mirror_axis", text="Mirror Axis")
                row.prop(scene, "prop_plasticity_pin_mesh_mirror_axis",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_mirror_axis"), emboss=False)
                row = col.row(align=True)
                row.prop(scene, "mirror_center_object", text="Mirror Center")
                row.prop(scene, "prop_plasticity_pin_mesh_mirror_center",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_mirror_center"), emboss=False)
                row = col.row(align=True)
                row.operator("object.remove_modifiers", text="Remove Modifiers")
                row.prop(scene, "prop_plasticity_pin_mesh_remove_modifiers",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_remove_modifiers"), emboss=False)
                row = col.row(align=True)
                row.operator("object.apply_modifiers", text="Apply Modifiers")
                row.prop(scene, "prop_plasticity_pin_mesh_apply_modifiers",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_apply_modifiers"), emboss=False)
                row = col.row(align=True)
                row.operator("object.remove_vertex_groups", text="Remove Vertex Groups")
                row.prop(scene, "prop_plasticity_pin_mesh_remove_vertex_groups",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_remove_vertex_groups"), emboss=False)
                row = col.row(align=True)
                row.operator("object.snap_to_cursor", text="Snap to 3D Cursor")
                row.prop(scene, "prop_plasticity_pin_mesh_snap_cursor",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_snap_cursor"), emboss=False)
                row = col.row(align=True)
                row.operator("object.import_fbx", text="Import FBX")
                row.prop(scene, "prop_plasticity_pin_mesh_import_fbx",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_import_fbx"), emboss=False)
                row = col.row(align=True)
                row.operator("object.export_fbx", text="Export FBX")
                row.prop(scene, "prop_plasticity_pin_mesh_export_fbx",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_export_fbx"), emboss=False)
                row = col.row(align=True)
                row.operator("object.import_obj", text="Import OBJ")
                row.prop(scene, "prop_plasticity_pin_mesh_import_obj",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_import_obj"), emboss=False)
                row = col.row(align=True)
                row.operator("object.export_obj", text="Export OBJ")
                row.prop(scene, "prop_plasticity_pin_mesh_export_obj",
                         text="", icon=_pin_icon(scene, "prop_plasticity_pin_mesh_export_obj"), emboss=False)

            elif active_tab == "PREFERENCES":
                box = layout.box()
                col = box.column(align=True)

                category_box = col.box()
                category_col = category_box.column(align=True)
                category_col.label(text="UV / Material / Texture Tools")
                category_col.prop(
                    scene,
                    "prop_plasticity_pref_auto_assign_checker_on_select",
                    text="Auto Assign Checker on Selection",
                )
