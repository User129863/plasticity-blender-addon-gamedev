import bpy
import math

from .__init__ import plasticity_client
from .__init__ import load_presets
from .client import FacetShapeType



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

            box = layout.box()
            box.operator("wm.list", text="Refresh")
            box.prop(scene, "prop_plasticity_list_only_visible",
                     text="Only visible in Plasticity")
            box.prop(scene, "prop_plasticity_list_only_selected",
                     text="Only selected objects in Blender")
            box.prop(scene, "prop_plasticity_unit_scale",
                     text="Scale", slider=True)

            layout.separator()
            
            if not plasticity_client.subscribed:
                layout.operator("wm.subscribe_all", text="Live link")
            else:
                layout.operator("wm.unsubscribe_all", text="Disable live link")
            layout.separator()

            box = layout.box()
            box.prop(
                scene,
                "prop_plasticity_ui_show_refacet",
                text="Refacet",
                icon="TRIA_DOWN" if scene.prop_plasticity_ui_show_refacet else "TRIA_RIGHT",
                emboss=False,
            )
            if scene.prop_plasticity_ui_show_refacet:
                col = box.column(align=True)
                col.operator("wm.refacet", text="Refacet")
                if context.mode == 'OBJECT':
                    col.prop(scene, "prop_plasticity_live_refacet", text="Live Refacet Mode")
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

            box = layout.box()
            box.prop(
                scene,
                "prop_plasticity_ui_show_utilities",
                text="Plasticity Utilities",
                icon="TRIA_DOWN" if scene.prop_plasticity_ui_show_utilities else "TRIA_RIGHT",
                emboss=False,
            )
            if scene.prop_plasticity_ui_show_utilities:
                col = box.column(align=True)
                col.operator("mesh.auto_mark_edges", text="Auto Mark Edges")
                col.operator("mesh.merge_uv_seams", text="Merge UV Seams")
                col.prop(scene, "prop_plasticity_auto_cylinder_seam",
                         text="Auto Cylinder Seam")
                cylinder_col = col.column(align=True)
                cylinder_col.enabled = scene.prop_plasticity_auto_cylinder_seam
                cylinder_col.prop(scene, "prop_plasticity_auto_cylinder_seam_mode",
                                  text="Cylinder Seam Mode")
                cylinder_col.prop(scene, "prop_plasticity_auto_cylinder_partial_angle",
                                  text="Partial Wrap Angle")
                cylinder_col.prop(scene, "prop_plasticity_auto_cylinder_seam_occluded_only",
                                  text="Occluded Only (View)")
                col.operator("mesh.select_by_plasticity_face_id",
                             text="Select Plasticity Face(s)")
                col.prop(scene, "prop_plasticity_live_expand",
                         text="Live Expand Selection")
                if scene.prop_plasticity_live_expand:
                    expand_box = col.box()
                    expand_col = expand_box.column(align=True)
                    expand_col.prop(scene, "prop_plasticity_live_expand_auto_circle",
                                    text="Auto Circle Select Mode")
                    expand_col.prop(scene, "prop_plasticity_live_expand_interval",
                                    text="Update Interval")
                    expand_col.prop(scene, "prop_plasticity_live_expand_auto_merge_seams",
                                    text="Auto Merge Seams on Selection")
                    merge_col = expand_col.column()
                    merge_col.enabled = scene.prop_plasticity_live_expand_auto_merge_seams
                    merge_col.prop(scene, "prop_plasticity_auto_cylinder_seam",
                                   text="Auto Cylinder Seam")
                    cylinder_merge_col = merge_col.column(align=True)
                    cylinder_merge_col.enabled = scene.prop_plasticity_auto_cylinder_seam
                    cylinder_merge_col.prop(scene, "prop_plasticity_auto_cylinder_seam_mode",
                                            text="Cylinder Seam Mode")
                    cylinder_merge_col.prop(scene, "prop_plasticity_auto_cylinder_partial_angle",
                                            text="Partial Wrap Angle")
                    cylinder_merge_col.prop(scene, "prop_plasticity_auto_cylinder_seam_occluded_only",
                                            text="Occluded Only (View)")
                    merge_col.prop(scene, "prop_plasticity_live_expand_respect_seams",
                                   text="Respect Existing Seams")
                    expand_col.operator("mesh.relax_uvs_plasticity", text="Relax UVs")
                    expand_col.label(text="Live Expand Selection Settings")
                    expand_col.prop(scene, "prop_plasticity_select_adjacent_fillets",
                                    text="Select Adjacent Fillets")
                    expand_col.prop(scene, "prop_plasticity_select_fillet_min_curvature_angle",
                                    text="Min Curvature Angle")
                    expand_col.prop(scene, "prop_plasticity_select_fillet_max_area_ratio",
                                    text="Max Area Ratio")
                    expand_col.prop(scene, "prop_plasticity_select_fillet_min_adjacent_groups",
                                    text="Min Adjacent Groups")
                    expand_col.prop(scene, "prop_plasticity_select_include_vertex_adjacency",
                                    text="Include Vertex Adjacent")
                    ratio_col = expand_col.column(align=True)
                    ratio_col.enabled = scene.prop_plasticity_select_include_vertex_adjacency
                    ratio_col.prop(scene, "prop_plasticity_select_vertex_adjacent_max_length_ratio",
                                   text="Max Vertex Adjacent Length Ratio")
                col.prop(scene, "prop_plasticity_live_expand_edge_highlight",
                         text="Plasticity Edge Highlight")
                if scene.prop_plasticity_live_expand_edge_highlight:
                    highlight_col = col.column(align=True)
                    highlight_col.prop(scene, "prop_plasticity_live_expand_active_view_only",
                                       text="Active View Only")
                    highlight_col.prop(scene, "prop_plasticity_live_expand_edge_occlude",
                                       text="Occlude Hidden Edges")
                    highlight_col.prop(scene, "prop_plasticity_live_expand_edge_thickness",
                                       text="Plasticity Edge Highlight Thickness")
                    highlight_col.prop(scene, "prop_plasticity_live_expand_overlay_color",
                                       text="Plasticity Edge Highlight Color")
                col.operator("mesh.select_by_plasticity_face_id_edge",
                             text="Select Plasticity Edges")
                col.operator("mesh.paint_plasticity_faces",
                             text="Paint Plasticity Faces")

            box = layout.box()
            box.prop(
                scene,
                "prop_plasticity_ui_show_uv_tools",
                text="UV / Material / Texture Tools",
                icon="TRIA_DOWN" if scene.prop_plasticity_ui_show_uv_tools else "TRIA_RIGHT",
                emboss=False,
            )
            if scene.prop_plasticity_ui_show_uv_tools:
                col = box.column(align=True)
                col.operator("mesh.auto_unwrap_plasticity", text="Unwrap")
                col.operator("object.open_uv_editor", text="Open Selected Inside UV Editor")
                col.operator("object.close_uv_editor", text="Close UV Editor")
                col.operator("object.select_without_uvs", text="Select Objects Without UVs")
                col.operator("object.remove_uvs_from_selected", text="Remove UVs from Selected Objects")
                col.operator("object.remove_materials", text="Remove Materials")
                col.operator("object.reload_textures", text="Reload Textures")
                col.operator("object.assign_uv_checker_texture", text="Assign Checker Texture")
                col.operator("object.remove_uv_checker_nodes", text="Remove Checker Nodes")
                checker_col = col.column(align=True)
                checker_col.prop(scene, "prop_plasticity_checker_source", text="")
                checker_source = scene.prop_plasticity_checker_source
                if checker_source == "LIBRARY":
                    preview_col = checker_col.column(align=True)
                    preview_col.scale_y = 0.6
                    preview_col.template_icon_view(
                        scene, "prop_plasticity_checker_image", show_labels=True
                    )
                else:
                    row = checker_col.row(align=True)
                    path_label = scene.prop_plasticity_checker_custom_path or "No file selected"
                    row.label(text=path_label)
                    row.operator("object.select_checker_image", text="", icon="FILE_FOLDER")

            box = layout.box()
            box.prop(
                scene,
                "prop_plasticity_ui_show_mesh_tools",
                text="Mesh Tools",
                icon="TRIA_DOWN" if scene.prop_plasticity_ui_show_mesh_tools else "TRIA_RIGHT",
                emboss=False,
            )
            if scene.prop_plasticity_ui_show_mesh_tools:
                col = box.column(align=True)
                col.operator("object.select_similar_geometry", text="Select Similar Geometry")
                col.operator("object.join_selected", text="Join Selected")
                col.operator("object.unjoin_selected", text="Unjoin Selected")
                op = col.operator("object.merge_nonoverlapping_meshes", text="Merge Non-overlapping Meshes")
                op.overlap_threshold = scene.overlap_threshold
                row = col.row(align=True)
                row.separator()
                row.prop(scene, "overlap_threshold", text="Overlap Threshold")
                col.operator("object.select_meshes_with_ngons", text="Select Meshes with Ngons")
                col.operator("object.mirror", text="Mirror Selected")
                col.prop(scene, "mirror_axis", text="Mirror Axis")
                col.prop(scene, "mirror_center_object", text="Mirror Center")
                col.operator("object.remove_modifiers", text="Remove Modifiers")
                col.operator("object.apply_modifiers", text="Apply Modifiers")
                col.operator("object.remove_vertex_groups", text="Remove Vertex Groups")
                col.operator("object.snap_to_cursor", text="Snap to 3D Cursor")
                col.operator("object.import_fbx", text="Import FBX")
                col.operator("object.export_fbx", text="Export FBX")
                col.operator("object.import_obj", text="Import OBJ")
                col.operator("object.export_obj", text="Export OBJ")
