import math
import mathutils
import os
import random
import re
import time
import zlib

import bmesh
import bpy
import bpy.utils.previews
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader


_CHECKER_PREVIEWS = None
_CHECKER_ENUM_MAP = {}
_CHECKER_ENUM_ID_MAX = 63


def _checker_images_dir():
    return os.path.join(os.path.dirname(__file__), "images")


def _list_checker_images():
    images_dir = _checker_images_dir()
    if not os.path.isdir(images_dir):
        return []
    exts = {".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".bmp", ".exr"}
    files = []
    for name in os.listdir(images_dir):
        ext = os.path.splitext(name)[1].lower()
        if ext in exts:
            files.append(name)
    files.sort()
    return files


def _ensure_checker_previews():
    global _CHECKER_PREVIEWS
    if _CHECKER_PREVIEWS is None:
        _CHECKER_PREVIEWS = bpy.utils.previews.new()
    return _CHECKER_PREVIEWS


def _checker_enum_id(filename):
    base = os.path.splitext(filename)[0]
    safe = re.sub(r'[^A-Za-z0-9_]', '_', base.upper())
    if not safe or safe[0].isdigit():
        safe = f"IMG_{safe}"
    checksum = zlib.crc32(filename.encode("utf-8")) & 0xFFFFFFFF
    suffix = f"_{checksum:08X}"
    max_safe_len = _CHECKER_ENUM_ID_MAX - len("CHK_") - len(suffix)
    if max_safe_len <= 0:
        safe = "IMG"
    elif len(safe) > max_safe_len:
        safe = safe[:max_safe_len]
    return f"CHK_{safe}{suffix}"


def get_checker_filename(enum_id):
    filename = _CHECKER_ENUM_MAP.get(enum_id)
    if filename:
        return filename
    if enum_id in _list_checker_images():
        return enum_id
    return None


def get_checker_default_enum():
    files = _list_checker_images()
    if not files:
        return "NONE"
    preferred = "UVChecker-color-1024x1024.png"
    if preferred in files:
        return _checker_enum_id(preferred)
    return _checker_enum_id(files[0])


def get_checker_image_items(self, context):
    global _CHECKER_ENUM_MAP
    _CHECKER_ENUM_MAP = {"NONE": None}
    items = [("NONE", "None", "No checker image selected", 0, 0)]
    try:
        images_dir = _checker_images_dir()
        files = _list_checker_images()
    except Exception:
        return items

    pcoll = None
    try:
        use_previews = not getattr(bpy.app, "background", False)
        if use_previews and getattr(bpy.context, "window_manager", None) is None:
            use_previews = False
    except Exception:
        use_previews = False

    if use_previews:
        try:
            pcoll = _ensure_checker_previews()
        except Exception:
            pcoll = None

    for idx, filename in enumerate(files, start=1):
        try:
            enum_id = _checker_enum_id(filename)
            _CHECKER_ENUM_MAP[enum_id] = filename
            filepath = os.path.join(images_dir, filename)
            icon_id = 0
            if pcoll is not None:
                try:
                    if filename not in pcoll:
                        pcoll.load(filename, filepath, 'IMAGE')
                    icon_id = pcoll[filename].icon_id
                except Exception:
                    icon_id = 0
            items.append((enum_id, filename, filepath, icon_id, idx))
        except Exception as exc:
            print(f"Plasticity: skipping checker image '{filename}': {exc}")
    return items


def clear_checker_previews():
    global _CHECKER_PREVIEWS
    if _CHECKER_PREVIEWS is not None:
        bpy.utils.previews.remove(_CHECKER_PREVIEWS)
        _CHECKER_PREVIEWS = None

class SelectByFaceIDOperator(bpy.types.Operator):
    bl_idname = "mesh.select_by_plasticity_face_id"
    bl_label = "Select by Plasticity Face ID"
    bl_description = (
        "Edit Mode: select all faces for the same Plasticity surface as your selection. "
        "Optional fillet expansion uses curvature/area thresholds"
    )
    bl_options = {'REGISTER', 'UNDO'}

    select_adjacent_fillets: bpy.props.BoolProperty(
        name="Select Adjacent Fillets",
        description="Also select adjacent Plasticity groups that look like fillets",
        default=False,
    )
    fillet_min_curvature_angle: bpy.props.FloatProperty(
        name="Min Curvature Angle",
        description="Minimum normal deviation (degrees) to treat a group as curved",
        default=5.0,
        min=0.0,
        max=90.0,
    )
    fillet_max_area_ratio: bpy.props.FloatProperty(
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
    fillet_min_adjacent_groups: bpy.props.IntProperty(
        name="Min Adjacent Groups",
        description="Minimum adjacent group count for a fillet candidate",
        default=2,
        min=1,
        max=8,
    )
    include_vertex_adjacency: bpy.props.BoolProperty(
        name="Include Vertex Adjacent",
        description="Also consider Plasticity groups that only touch at a vertex",
        default=False,
    )
    vertex_adjacent_max_length_ratio: bpy.props.FloatProperty(
        name="Max Vertex Adjacent Length Ratio",
        description="Limit vertex-adjacent fillet selection by relative size (1.0 disables)",
        default=0.5,
        min=0.0,
        max=10.0,
        step=0.01,
        precision=2,
    )

    @classmethod
    def poll(cls, context):
        if context.mode != 'EDIT_MESH':
            return False
        obj = context.active_object
        if not obj or obj.type != 'MESH' or "plasticity_id" not in obj.keys():
            return False
        return True

    def execute(self, context):
        obj = context.object
        bpy.ops.object.mode_set(mode='EDIT')

        scene = context.scene
        scene.prop_plasticity_select_adjacent_fillets = self.select_adjacent_fillets
        scene.prop_plasticity_select_fillet_min_curvature_angle = self.fillet_min_curvature_angle
        scene.prop_plasticity_select_fillet_max_area_ratio = self.fillet_max_area_ratio
        scene.prop_plasticity_select_fillet_min_adjacent_groups = self.fillet_min_adjacent_groups
        scene.prop_plasticity_select_include_vertex_adjacency = self.include_vertex_adjacency
        scene.prop_plasticity_select_vertex_adjacent_max_length_ratio = (
            self.vertex_adjacent_max_length_ratio
        )

        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)

        groups = mesh["groups"]
        if not groups:
            self.report({'ERROR'}, "No groups found")
            return {'CANCELLED'}

        face_ids = mesh["face_ids"]
        if not face_ids:
            self.report({'ERROR'}, "No face_ids found")
            return {'CANCELLED'}

        selected_group_indices, _ = expand_plasticity_selection(
            groups,
            mesh,
            bm,
            self.select_adjacent_fillets,
            self.fillet_min_curvature_angle,
            self.fillet_max_area_ratio,
            self.fillet_min_adjacent_groups,
            self.include_vertex_adjacency,
            self.vertex_adjacent_max_length_ratio,
            allow_full_selection_seed=True,
        )

        if not selected_group_indices:
            self.report({'ERROR'}, "No Plasticity faces selected")
            return {'CANCELLED'}

        bmesh.update_edit_mesh(mesh)
        return {'FINISHED'}


class SelectByFaceIDEdgeOperator(bpy.types.Operator):
    bl_idname = "mesh.select_by_plasticity_face_id_edge"
    bl_label = "Select by Plasticity Face ID (Edge)"
    bl_description = (
        "Edit Mode: select boundary edges of the selected Plasticity surface(s). "
        "Deselects faces in those groups"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'EDIT_MESH':
            return False
        obj = context.active_object
        if not obj or obj.type != 'MESH' or "plasticity_id" not in obj.keys():
            return False
        return True

    def execute(self, context):
        obj = context.object
        bpy.ops.object.mode_set(mode='EDIT')
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        groups = mesh["groups"]

        if not groups:
            self.report({'ERROR'}, "No groups found")
            return {'CANCELLED'}

        face_ids = mesh["face_ids"]
        if not face_ids:
            self.report({'ERROR'}, "No face_ids found")
            return {'CANCELLED'}

        selected_group_ids = get_selected_group_ids(groups, mesh, bm)
        boundary_edges = get_boundary_edges_for_group_ids(
            groups, mesh, bm, selected_group_ids)

        # Unselect the faces in selected_group_ids
        selected_group_indices = {group_id // 2 for group_id in selected_group_ids}
        group_faces, _ = build_group_faces_map(groups, mesh, bm)
        bm.faces.ensure_lookup_table()
        for group_idx in selected_group_indices:
            if group_idx >= len(group_faces):
                continue
            for face_index in group_faces[group_idx]:
                if face_index < len(bm.faces):
                    bm.faces[face_index].select = False

        # Select the boundary edges
        for edge in boundary_edges:
            edge.select = True

        bmesh.update_edit_mesh(mesh)
        return {'FINISHED'}


class MergeUVSeams(bpy.types.Operator):
    bl_idname = "mesh.merge_uv_seams"
    bl_label = "Merge UV Seams"
    bl_description = (
        "Edit Mode: merge UV islands between adjacent faces by rewriting seams. "
        "Requires a face selection"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'EDIT_MESH':
            return False
        obj = context.active_object
        active_poly_index = obj.data.polygons.active
        if active_poly_index is None:
            return False
        return True

    def execute(self, context):
        def expand_selection_by_seams(bm, seed_faces):
            if not seed_faces:
                return set()
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            expanded = {idx for idx in seed_faces if idx < len(bm.faces)}
            stack = list(expanded)
            while stack:
                face = bm.faces[stack.pop()]
                for edge in face.edges:
                    if edge.seam:
                        continue
                    for linked in edge.link_faces:
                        if linked.index in expanded:
                            continue
                        expanded.add(linked.index)
                        stack.append(linked.index)
            return expanded

        edit_objects = getattr(context, "objects_in_mode", None)
        if not edit_objects:
            edit_objects = [context.active_object] if context.active_object else []
        edit_objects = [
            obj for obj in edit_objects
            if obj and obj.type == 'MESH'
        ]

        if not edit_objects:
            self.report({'WARNING'}, "Select faces to merge UV seams")
            return {'CANCELLED'}

        occluded_only = bool(
            getattr(context.scene, "prop_plasticity_auto_cylinder_seam_occluded_only", False)
        )
        view_context = _find_view3d_region(context.scene) if occluded_only else None
        respect_existing = bool(
            getattr(context.scene, "prop_plasticity_live_expand_respect_seams", False)
        )
        enable_cylinder = bool(
            getattr(context.scene, "prop_plasticity_auto_cylinder_seam", False)
        )
        prev_active = context.view_layer.objects.active
        any_processed = False

        for obj in edit_objects:
            mesh = obj.data
            bm = bmesh.from_edit_mesh(mesh)
            bm.faces.ensure_lookup_table()
            original_selected = {face.index for face in bm.faces if face.select}
            if not original_selected:
                continue

            expanded_faces = expand_selection_by_seams(bm, original_selected)
            for face in bm.faces:
                face.select = face.index in expanded_faces

            changed_to_true, changed_to_false = _auto_merge_seams_on_selection(
                bm,
                expanded_faces,
                respect_existing,
            )

            if enable_cylinder:
                cylinder_changed = _auto_cylinder_seam_on_selection(
                    bm,
                    expanded_faces,
                    mode=str(context.scene.prop_plasticity_auto_cylinder_seam_mode),
                    partial_angle=float(context.scene.prop_plasticity_auto_cylinder_partial_angle),
                    occluded_only=occluded_only,
                    obj=obj,
                    scene=context.scene,
                    view_context=view_context,
                )
                if cylinder_changed:
                    changed_to_true.extend(cylinder_changed)

            for face in bm.faces:
                face.select = face.index in original_selected

            did_merge = bool(changed_to_true or changed_to_false)
            if did_merge:
                any_processed = True
                _touch_seams_version(mesh)
                bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=False)
                if prev_active != obj:
                    context.view_layer.objects.active = obj
                did_unwrap = _touch_live_unwrap_after_seam_change(
                    context,
                    changed_to_true,
                    changed_to_false,
                )
                if not did_unwrap:
                    if not _maybe_live_unwrap(context, force=True):
                        _queue_live_unwrap()

            _invalidate_live_expand_overlay_cache()

        if prev_active is not None:
            context.view_layer.objects.active = prev_active

        if not any_processed:
            self.report({'WARNING'}, "Select faces to merge UV seams")
            return {'CANCELLED'}
        return {'FINISHED'}


def _relax_select_mode(context):
    select_mode = context.tool_settings.mesh_select_mode
    if select_mode[2]:
        return "FACE"
    if select_mode[1]:
        return "EDGE"
    return "VERT"


def _relax_uv_loop_selected(loop, uv_layer, mode):
    uv = loop[uv_layer]
    if mode == "EDGE":
        return uv.select_edge
    return uv.select


def _relax_uv_face_selected(face, uv_layer, mode):
    if mode == "EDGE":
        return all(loop[uv_layer].select_edge for loop in face.loops)
    if mode == "VERT":
        return all(loop[uv_layer].select for loop in face.loops)
    if face.select:
        return True
    return all(loop[uv_layer].select for loop in face.loops)


def _relax_uv_edge_linked(loop, uv_layer):
    other = loop.link_loop_radial_prev
    if other == loop:
        return False
    return (
        loop[uv_layer].uv == other.link_loop_next[uv_layer].uv
        and loop.link_loop_next[uv_layer].uv == other[uv_layer].uv
    )


def _relax_linked_uv_loops(loop, uv_layer):
    uv = loop[uv_layer].uv
    return [l for l in loop.vert.link_loops if l[uv_layer].uv == uv]


def _relax_is_boundary(loop, uv_layer, face_selected_fn):
    other = loop.link_loop_radial_prev
    if other == loop:
        return True
    if not face_selected_fn(other.face):
        return True
    return (
        loop[uv_layer].uv.to_tuple() != other.link_loop_next[uv_layer].uv.to_tuple()
        or loop.link_loop_next[uv_layer].uv.to_tuple() != other[uv_layer].uv.to_tuple()
    )


def _relax_collect_islands(faces, uv_layer):
    face_set = set(faces)
    islands = []
    visited = set()

    for face in face_set:
        if face in visited:
            continue
        stack = [face]
        island = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            island.append(current)

            for loop in current.loops:
                other = loop.link_loop_radial_prev
                if other == loop:
                    continue
                if other.face not in face_set:
                    continue
                if loop.edge.seam:
                    continue
                if not _relax_uv_edge_linked(loop, uv_layer):
                    continue
                stack.append(other.face)

        islands.append(island)
    return islands


def _relax_pick_anchor_loops(loops, uv_layer):
    if len(loops) < 2:
        return None, None
    max_dist = -1.0
    anchor_a = None
    anchor_b = None
    coords = [loop[uv_layer].uv.copy() for loop in loops]
    for i, co_a in enumerate(coords):
        for j in range(i + 1, len(coords)):
            dist = (co_a - coords[j]).length_squared
            if dist > max_dist:
                max_dist = dist
                anchor_a = loops[i]
                anchor_b = loops[j]
    return anchor_a, anchor_b


class _RelaxIslandTransform:
    def __init__(self, loops, uv_layer):
        self.loops = loops
        self.uv_layer = uv_layer
        anchor_a, anchor_b = _relax_pick_anchor_loops(loops, uv_layer)
        self.anchor_a = anchor_a
        self.anchor_b = anchor_b
        if anchor_a is None or anchor_b is None:
            self.valid = False
            self.a0 = None
            self.b0 = None
            return
        self.valid = True
        self.a0 = anchor_a[uv_layer].uv.copy()
        self.b0 = anchor_b[uv_layer].uv.copy()

    def apply(self):
        if not self.valid:
            return
        a1 = self.anchor_a[self.uv_layer].uv.copy()
        b1 = self.anchor_b[self.uv_layer].uv.copy()
        v0 = self.b0 - self.a0
        v1 = b1 - a1
        if v0.length < 1e-10 or v1.length < 1e-10:
            return
        scale = v0.length / v1.length
        angle = math.atan2(v0.y, v0.x) - math.atan2(v1.y, v1.x)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        for loop in self.loops:
            uv = loop[self.uv_layer].uv
            rel = uv - a1
            new_x = rel.x * cos_a - rel.y * sin_a
            new_y = rel.x * sin_a + rel.y * cos_a
            uv[:] = (new_x * scale + self.a0.x, new_y * scale + self.a0.y)


def _relax_any_uv_selected(bm, uv_layer):
    for face in bm.faces:
        for loop in face.loops:
            uv = loop[uv_layer]
            if uv.select or uv.select_edge:
                return True
    return False


def _iter_uv_editors(context):
    window_manager = getattr(context, "window_manager", None)
    if not window_manager:
        return []
    seen = set()
    for window in window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            for space in area.spaces:
                if space.type != "IMAGE_EDITOR":
                    continue
                uv_editor = getattr(space, "uv_editor", None)
                if uv_editor is None or not hasattr(uv_editor, "use_live_unwrap"):
                    continue
                key = id(uv_editor)
                if key in seen:
                    continue
                seen.add(key)
                yield uv_editor


def _snapshot_live_unwrap_state(context):
    if not context:
        return None
    states = []
    scene = getattr(context, "scene", None)
    tool_settings = scene.tool_settings if scene else None
    if tool_settings:
        if hasattr(tool_settings, "use_live_unwrap"):
            states.append((tool_settings, "use_live_unwrap", tool_settings.use_live_unwrap))
        if hasattr(tool_settings, "use_edge_path_live_unwrap"):
            states.append((
                tool_settings,
                "use_edge_path_live_unwrap",
                tool_settings.use_edge_path_live_unwrap,
            ))
    for uv_editor in _iter_uv_editors(context):
        try:
            states.append((uv_editor, "use_live_unwrap", uv_editor.use_live_unwrap))
        except Exception:
            pass
    return states or None


def _set_live_unwrap_state(states, value):
    if not states:
        return
    if value is None:
        for target, attr_name, prev_value in states:
            if hasattr(target, attr_name):
                try:
                    setattr(target, attr_name, prev_value)
                except Exception:
                    pass
        return
    for target, attr_name, _ in states:
        if hasattr(target, attr_name):
            try:
                setattr(target, attr_name, value)
            except Exception:
                pass


def _set_space_uv_mode(space):
    prev_ui_mode = getattr(space, "ui_mode", None)
    prev_mode = getattr(space, "mode", None)
    set_uv = False
    if hasattr(space, "ui_mode"):
        try:
            space.ui_mode = "UV"
            set_uv = True
        except Exception:
            set_uv = False
    if not set_uv and hasattr(space, "mode"):
        try:
            space.mode = "UV"
        except Exception:
            pass
    return prev_ui_mode, prev_mode


def _restore_space_mode(space, prev_ui_mode, prev_mode):
    if prev_ui_mode is not None and hasattr(space, "ui_mode"):
        try:
            space.ui_mode = prev_ui_mode
        except Exception:
            pass
    if prev_mode is not None and hasattr(space, "mode"):
        try:
            space.mode = prev_mode
        except Exception:
            pass


def _is_uv_editor_live_unwrap_enabled(context):
    if not context:
        return False
    scene = getattr(context, "scene", None)
    tool_settings = scene.tool_settings if scene else None
    if tool_settings and getattr(tool_settings, "use_live_unwrap", False):
        return True
    for uv_editor in _iter_uv_editors(context):
        if getattr(uv_editor, "use_live_unwrap", False):
            return True
    return False


def _is_live_unwrap_enabled(context):
    if _is_uv_editor_live_unwrap_enabled(context):
        return True
    if not context:
        return False
    scene = getattr(context, "scene", None)
    tool_settings = scene.tool_settings if scene else None
    if tool_settings and getattr(tool_settings, "use_edge_path_live_unwrap", False):
        return True
    return False


def _relax_run_uv_op(context, op_fn, force_uv_sync=False, suspend_live_unwrap=True, **kwargs):
    def cancelled(result):
        return isinstance(result, set) and 'CANCELLED' in result

    scene = context.scene if context else None
    tool_settings = scene.tool_settings if scene else None
    prev_uv_sync = None
    if tool_settings and force_uv_sync:
        prev_uv_sync = tool_settings.use_uv_select_sync
        tool_settings.use_uv_select_sync = True
    live_unwrap_states = None
    if suspend_live_unwrap:
        live_unwrap_states = _snapshot_live_unwrap_state(context)
        _set_live_unwrap_state(live_unwrap_states, False)

    try:
        window_manager = context.window_manager
        candidates = []
        if window_manager:
            for area_type in ("IMAGE_EDITOR", "VIEW_3D"):
                for window in window_manager.windows:
                    screen = window.screen
                    if screen is None:
                        continue
                    for area in screen.areas:
                        if area.type != area_type:
                            continue
                        region = next((r for r in area.regions if r.type == "WINDOW"), None)
                        if region is None:
                            continue
                        candidates.append((window, area, region))
                    if candidates and area_type == "IMAGE_EDITOR":
                        break
                if candidates and area_type == "IMAGE_EDITOR":
                    break

        def build_override(window, area, region):
            space = area.spaces.active
            override = {
                "window": window,
                "area": area,
                "region": region,
                "space_data": space,
                "scene": context.scene,
                "view_layer": context.view_layer,
                "active_object": context.active_object,
                "object": context.object,
                "edit_object": context.edit_object,
            }
            region_data = getattr(space, "region_3d", None)
            if region_data is not None:
                override["region_data"] = region_data
            return override

        def run_with_override(window, area, region):
            override_ctx = build_override(window, area, region)
            with bpy.context.temp_override(**override_ctx):
                return op_fn(**kwargs)

        if candidates:
            for window, area, region in candidates:
                result = run_with_override(window, area, region)
                if not cancelled(result):
                    return True

                if area.type != "IMAGE_EDITOR":
                    original_type = area.type
                    area.type = "IMAGE_EDITOR"
                    temp_space = area.spaces.active
                    prev_ui_mode, prev_mode = _set_space_uv_mode(temp_space)
                    try:
                        region = next((r for r in area.regions if r.type == "WINDOW"), None)
                        if region is None:
                            continue
                        result = run_with_override(window, area, region)
                        if not cancelled(result):
                            return True
                    finally:
                        _restore_space_mode(temp_space, prev_ui_mode, prev_mode)
                        area.type = original_type

        result = op_fn(**kwargs)
        return not cancelled(result)
    finally:
        if tool_settings and prev_uv_sync is not None:
            tool_settings.use_uv_select_sync = prev_uv_sync
        if suspend_live_unwrap:
            _set_live_unwrap_state(live_unwrap_states, None)


def _run_uv_unwrap_in_view3d(context, unwrap_kwargs, force_uv_sync=False):
    def cancelled(result):
        return isinstance(result, set) and 'CANCELLED' in result

    if not context or not unwrap_kwargs:
        return False
    scene = getattr(context, "scene", None)
    tool_settings = scene.tool_settings if scene else None
    prev_uv_sync = None
    if tool_settings and force_uv_sync:
        prev_uv_sync = tool_settings.use_uv_select_sync
        tool_settings.use_uv_select_sync = True
    try:
        view = _find_view3d_region(scene)
        if not view:
            return False
        window, area, region, region_3d = view
        override_ctx = {
            "window": window,
            "area": area,
            "region": region,
            "space_data": area.spaces.active,
            "scene": scene,
            "view_layer": context.view_layer,
            "active_object": context.active_object,
            "object": context.object,
            "edit_object": context.edit_object,
            "region_data": region_3d,
        }
        if window.screen is not None:
            override_ctx["screen"] = window.screen
        with bpy.context.temp_override(**override_ctx):
            result = bpy.ops.uv.unwrap(**unwrap_kwargs)
        return not cancelled(result)
    finally:
        if tool_settings and prev_uv_sync is not None:
            tool_settings.use_uv_select_sync = prev_uv_sync


def _snapshot_unwrap_last_props(context):
    window_manager = getattr(context, "window_manager", None)
    if not window_manager:
        return None
    try:
        props = window_manager.operator_properties_last("uv.unwrap")
    except Exception:
        return None
    if props is None:
        return None
    values = {}
    try:
        rna_props = props.bl_rna.properties
    except Exception:
        return None
    for prop in rna_props:
        if prop.is_readonly:
            continue
        if prop.type not in {"BOOLEAN", "INT", "FLOAT", "ENUM"}:
            continue
        name = prop.identifier
        if not hasattr(props, name):
            continue
        try:
            values[name] = getattr(props, name)
        except Exception:
            pass
    return values or None


def _restore_unwrap_last_props(context, values):
    if not values:
        return
    window_manager = getattr(context, "window_manager", None)
    if not window_manager:
        return
    try:
        props = window_manager.operator_properties_last("uv.unwrap")
    except Exception:
        return
    if props is None:
        return
    for name, value in values.items():
        if hasattr(props, name):
            try:
                setattr(props, name, value)
            except Exception:
                pass


def _default_unwrap_props():
    try:
        rna_props = bpy.ops.uv.unwrap.get_rna_type().properties
    except Exception:
        return None
    defaults = {}
    for prop in rna_props:
        if prop.is_readonly:
            continue
        if prop.type not in {"BOOLEAN", "INT", "FLOAT", "ENUM"}:
            continue
        defaults[prop.identifier] = prop.default
    return defaults or None


def _unwrap_kwargs_from_last_props(context):
    global _LIVE_UNWRAP_LAST_PROPS
    props = _snapshot_unwrap_last_props(context)
    if not props:
        props = _default_unwrap_props()
    if not props:
        return {}
    method = props.get("method")
    if method == "MINIMUM_STRETCH":
        if _LIVE_UNWRAP_LAST_PROPS:
            props = _LIVE_UNWRAP_LAST_PROPS
        else:
            defaults = _default_unwrap_props()
            if defaults:
                props = defaults
    else:
        _LIVE_UNWRAP_LAST_PROPS = dict(props)
    allowed = {
        "method",
        "fill_holes",
        "correct_aspect",
        "use_subsurf_data",
        "margin_method",
        "margin",
        "iterations",
        "no_flip",
    }
    return {name: props[name] for name in allowed if name in props}


def _unwrap_kwargs_from_props(props):
    if not props:
        return {}
    allowed = {
        "method",
        "fill_holes",
        "correct_aspect",
        "use_subsurf_data",
        "margin_method",
        "margin",
        "iterations",
        "no_flip",
    }
    return {name: props[name] for name in allowed if name in props}


def _unwrap_kwargs_without_min_stretch(props):
    global _LIVE_UNWRAP_LAST_PROPS
    unwrap_kwargs = _unwrap_kwargs_from_props(props) if props else {}
    method = unwrap_kwargs.get("method")
    if method and method != "MINIMUM_STRETCH":
        return unwrap_kwargs
    fallback_props = _LIVE_UNWRAP_LAST_PROPS or _default_unwrap_props() or {}
    fallback_kwargs = _unwrap_kwargs_from_props(fallback_props)
    fallback_method = fallback_kwargs.get("method")
    if not fallback_method or fallback_method == "MINIMUM_STRETCH":
        fallback_method = "CONFORMAL"
    unwrap_kwargs = dict(unwrap_kwargs)
    unwrap_kwargs["method"] = fallback_method
    return unwrap_kwargs


def _pin_uv_faces(bm, uv_layer, face_indices):
    if bm is None or uv_layer is None or not face_indices:
        return []
    bm.faces.ensure_lookup_table()
    pinned = []
    for face_index in face_indices:
        if face_index >= len(bm.faces):
            continue
        face = bm.faces[face_index]
        for loop_index, loop in enumerate(face.loops):
            uv = loop[uv_layer]
            pinned.append((face_index, loop_index, uv.pin_uv))
            uv.pin_uv = True
    return pinned


def _restore_pinned_uvs(bm, uv_layer, pinned):
    if bm is None or uv_layer is None or not pinned:
        return
    bm.faces.ensure_lookup_table()
    for face_index, loop_index, pin_state in pinned:
        if face_index >= len(bm.faces):
            continue
        face = bm.faces[face_index]
        if loop_index >= len(face.loops):
            continue
        face.loops[loop_index][uv_layer].pin_uv = pin_state


def _mark_relaxed_faces(bm, face_indices):
    if bm is None or not face_indices:
        return
    bm.faces.ensure_lookup_table()
    layer = bm.faces.layers.int.get("plasticity_relaxed")
    if layer is None:
        layer = bm.faces.layers.int.new("plasticity_relaxed")
    for face_index in face_indices:
        if face_index >= len(bm.faces):
            continue
        bm.faces[face_index][layer] = 1


def _reset_live_unwrap_method_after_relax(context, targets, unwrap_props):
    if not context:
        return
    scene = getattr(context, "scene", None)
    tool_settings = scene.tool_settings if scene else None
    edge_live = bool(getattr(tool_settings, "use_edge_path_live_unwrap", False)) if tool_settings else False
    uv_live = _is_uv_editor_live_unwrap_enabled(context)
    if not edge_live and not uv_live:
        return
    unwrap_kwargs = _unwrap_kwargs_without_min_stretch(unwrap_props)
    if not unwrap_kwargs:
        return

    active_obj = getattr(context, "active_object", None)
    target = None
    if active_obj is not None:
        for candidate in targets:
            if candidate.get("mesh") == active_obj.data:
                target = candidate
                break
    if target is None and targets:
        target = targets[0]
    if target is None:
        return

    mesh = target.get("mesh")
    bm = target.get("bm")
    uv_layer = target.get("uv_layer")
    if mesh is None or bm is None or uv_layer is None:
        return
    bm.faces.ensure_lookup_table()
    face = next((f for f in bm.faces if not f.hide), None)
    if face is None:
        return

    face_index = face.index
    uv_backup = [loop[uv_layer].uv.copy() for loop in face.loops]
    for f in bm.faces:
        f.select = False
    face.select = True
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

    ran = False
    if edge_live:
        ran = _run_uv_unwrap_in_view3d(
            context,
            unwrap_kwargs,
            force_uv_sync=True,
        )
    if not ran:
        _relax_run_uv_op(
            context,
            bpy.ops.uv.unwrap,
            force_uv_sync=True,
            suspend_live_unwrap=False,
            **unwrap_kwargs,
        )

    bm = bmesh.from_edit_mesh(mesh)
    bm.faces.ensure_lookup_table()
    if face_index >= len(bm.faces):
        return
    uv_layer = bm.loops.layers.uv.active or bm.loops.layers.uv.verify()
    face = bm.faces[face_index]
    for loop, uv in zip(face.loops, uv_backup):
        loop[uv_layer].uv = uv
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)


def _snapshot_tool_settings_unwrap(tool_settings):
    if tool_settings is None:
        return None
    values = {}
    try:
        props = tool_settings.bl_rna.properties
    except Exception:
        return None
    for prop in props:
        if prop.is_readonly:
            continue
        name = prop.identifier
        if "uv" not in name and "unwrap" not in name:
            continue
        if prop.type not in {"BOOLEAN", "INT", "FLOAT", "ENUM"}:
            continue
        try:
            values[name] = getattr(tool_settings, name)
        except Exception:
            pass
    return values or None


def _restore_tool_settings_unwrap(tool_settings, values):
    if tool_settings is None or not values:
        return
    for name, value in values.items():
        if hasattr(tool_settings, name):
            try:
                setattr(tool_settings, name, value)
            except Exception:
                pass


def _unwrap_kwargs_from_tool_settings(tool_settings):
    if tool_settings is None:
        return {}
    try:
        props = bpy.ops.uv.unwrap.get_rna_type().properties
    except Exception:
        return {}
    available = {prop.identifier for prop in props}
    mapping = {
        "method": ("uv_unwrap_method",),
        "fill_holes": ("uv_unwrap_fill_holes",),
        "correct_aspect": ("uv_unwrap_correct_aspect",),
        "use_subsurf_data": ("uv_unwrap_use_subsurf_data",),
        "margin": ("uv_unwrap_margin",),
        "iterations": ("uv_unwrap_iterations",),
    }
    kwargs = {}
    for prop_name, attr_names in mapping.items():
        if prop_name not in available:
            continue
        for attr_name in attr_names:
            if hasattr(tool_settings, attr_name):
                try:
                    kwargs[prop_name] = getattr(tool_settings, attr_name)
                except Exception:
                    pass
                break
    return kwargs


class RelaxUVsPlasticityOperator(bpy.types.Operator):
    bl_idname = "mesh.relax_uvs_plasticity"
    bl_label = "Relax UVs"
    bl_description = "Relax UVs while keeping boundary corners blended"
    bl_options = {'REGISTER', 'UNDO'}

    iterations: bpy.props.IntProperty(name='Iterations', default=20, min=5, max=150, soft_max=50)
    use_correct_aspect: bpy.props.BoolProperty(name='Correct Aspect', default=True)

    @classmethod
    def poll(cls, context):
        if bpy.app.version < (4, 3, 0):
            return False
        if context.mode != 'EDIT_MESH':
            return False
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def draw(self, context):
        self.layout.prop(self, 'iterations', slider=True)
        self.layout.prop(self, 'use_correct_aspect')

    @staticmethod
    def _edit_mesh_objects(context):
        edit_objects = getattr(context, "objects_in_mode", None)
        if edit_objects:
            return [obj for obj in edit_objects if obj and obj.type == 'MESH']
        obj = context.active_object
        if obj and obj.type == 'MESH':
            return [obj]
        return []

    def _snapshot_selection(self, bm, uv_layer, uv_sync):
        selection = {
            "verts": {v.index for v in bm.verts if v.select},
            "edges": {e.index for e in bm.edges if e.select},
            "faces": {f.index for f in bm.faces if f.select},
        }
        uv_selection = None
        if not uv_sync:
            uv_selection = []
            for face in bm.faces:
                for loop_index, loop in enumerate(face.loops):
                    uv = loop[uv_layer]
                    uv_selection.append(
                        (face.index, loop_index, uv.select, uv.select_edge)
                    )
        return selection, uv_selection

    @staticmethod
    def _restore_selection(bm, uv_layer, selection, uv_selection):
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        for v in bm.verts:
            v.select = v.index in selection["verts"]
        for e in bm.edges:
            e.select = e.index in selection["edges"]
        for f in bm.faces:
            f.select = f.index in selection["faces"]
        if uv_selection is not None:
            if uv_layer is None:
                uv_layer = bm.loops.layers.uv.verify()
            for face_index, loop_index, select, select_edge in uv_selection:
                if face_index >= len(bm.faces):
                    continue
                face = bm.faces[face_index]
                if loop_index >= len(face.loops):
                    continue
                uv = face.loops[loop_index][uv_layer]
                uv.select = select
                uv.select_edge = select_edge

    def _collect_sync_vert_edge(self, bm, uv_layer, mode):
        selected_elems = []
        if mode == "EDGE":
            selected_elems = [e for e in bm.edges if e.select]
        else:
            selected_elems = [v for v in bm.verts if v.select]
        if not selected_elems:
            return [], []

        for face in bm.faces:
            if face.hide:
                continue
            if mode == "EDGE":
                if any(edge.select for edge in face.edges):
                    face.select = True
            else:
                if any(vert.select for vert in face.verts):
                    face.select = True

        if mode == "EDGE":
            for edge in bm.edges:
                edge.select = edge.verts[0].select and edge.verts[1].select

        return selected_elems, []

    def _collect_sync_face(self, bm, uv_layer):
        selected_faces = [face for face in bm.faces if face.select and not face.hide]
        if not selected_faces:
            return [], []

        faces_to_select = set()
        border_loops = set()
        for face in selected_faces:
            for loop in face.loops:
                other = loop.link_loop_radial_prev
                is_border = False
                if other == loop:
                    is_border = True
                else:
                    if other.face.hide:
                        is_border = True
                    elif not other.face.select:
                        if _relax_uv_edge_linked(loop, uv_layer):
                            faces_to_select.add(other.face)
                        is_border = True
                    elif not _relax_uv_edge_linked(loop, uv_layer):
                        is_border = True
                if is_border:
                    border_loops.update(_relax_linked_uv_loops(loop, uv_layer))

        for face in faces_to_select:
            face.select = True
        return selected_faces, list(border_loops)

    def _collect_non_sync(self, bm, uv_layer, mode):
        def face_selected(face):
            return _relax_uv_face_selected(face, uv_layer, mode)

        selected_faces = [face for face in bm.faces if face_selected(face)]
        if not selected_faces:
            return [], []

        border_loops = set()
        for face in selected_faces:
            for loop in face.loops:
                if not _relax_uv_loop_selected(loop, uv_layer, mode):
                    continue
                if _relax_is_boundary(loop, uv_layer, face_selected):
                    border_loops.add(loop)
                    for linked in _relax_linked_uv_loops(loop, uv_layer):
                        if face_selected(linked.face):
                            border_loops.add(linked)
        return selected_faces, list(border_loops)

    def execute(self, context):
        global _LIVE_UNWRAP_LAST_PROPS
        if bpy.app.version < (4, 3, 0):
            self.report({'WARNING'}, 'Relax requires Blender 4.3 or newer')
            return {'CANCELLED'}

        edit_objects = self._edit_mesh_objects(context)
        if not edit_objects:
            self.report({'WARNING'}, 'No editable mesh objects found')
            return {'CANCELLED'}

        uv_sync = context.tool_settings.use_uv_select_sync
        selection_sync = uv_sync
        force_uv_sync = False
        if not uv_sync:
            any_uv_selected = False
            for obj in edit_objects:
                mesh = obj.data
                if not mesh.uv_layers:
                    continue
                bm = bmesh.from_edit_mesh(mesh)
                uv_layer = bm.loops.layers.uv.active
                if uv_layer is None:
                    uv_layer = bm.loops.layers.uv.verify()
                bm.faces.ensure_lookup_table()
                if _relax_any_uv_selected(bm, uv_layer):
                    any_uv_selected = True
                    break
            if not any_uv_selected:
                force_uv_sync = True
                selection_sync = True

        mode = _relax_select_mode(context)
        targets = []

        for obj in edit_objects:
            mesh = obj.data
            if not mesh.uv_layers:
                continue
            bm = bmesh.from_edit_mesh(mesh)
            uv_layer = bm.loops.layers.uv.active
            if uv_layer is None:
                uv_layer = bm.loops.layers.uv.verify()
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            selection, uv_selection = self._snapshot_selection(bm, uv_layer, uv_sync)

            if selection_sync:
                if mode == "FACE":
                    selected, _ = self._collect_sync_face(bm, uv_layer)
                else:
                    selected, _ = self._collect_sync_vert_edge(bm, uv_layer, mode)
            else:
                selected, _ = self._collect_non_sync(bm, uv_layer, mode)

            if not selected:
                self._restore_selection(bm, uv_layer, selection, uv_selection)
                continue

            relax_faces = []
            if selected:
                if hasattr(selected[0], "loops"):
                    relax_faces = [face.index for face in selected]
                else:
                    relax_faces = [
                        face.index for face in bm.faces if face.select and not face.hide
                    ]

            visible_faces = [face for face in bm.faces if not face.hide]
            islands = _relax_collect_islands(visible_faces, uv_layer)
            transforms = []
            for island in islands:
                if selection_sync:
                    if mode == "FACE":
                        if not any(face.select for face in island):
                            continue
                    else:
                        if not any(vert.select for face in island for vert in face.verts):
                            continue
                loops = [loop for face in island for loop in face.loops]
                transform = _RelaxIslandTransform(loops, uv_layer)
                if transform.valid:
                    transforms.append(transform)

            targets.append({
                "object": obj,
                "mesh": mesh,
                "bm": bm,
                "uv_layer": uv_layer,
                "selection": selection,
                "uv_selection": uv_selection,
                "transforms": transforms,
                "relax_faces": relax_faces,
            })

        if not targets:
            self.report({'WARNING'}, 'Need selected geometry')
            return {'CANCELLED'}

        try:
            unwrap_last_props = _snapshot_unwrap_last_props(context)
            if unwrap_last_props and unwrap_last_props.get("method") != "MINIMUM_STRETCH":
                _LIVE_UNWRAP_LAST_PROPS = dict(unwrap_last_props)
            unwrap_tool_settings = _snapshot_tool_settings_unwrap(context.scene.tool_settings)
            for target in targets:
                bmesh.update_edit_mesh(target["mesh"], loop_triangles=False, destructive=False)

            prev_active = context.view_layer.objects.active
            for target in targets:
                obj = target.get("object")
                if obj is None:
                    continue
                context.view_layer.objects.active = obj
                _relax_run_uv_op(
                    context,
                    bpy.ops.uv.unwrap,
                    method='MINIMUM_STRETCH',
                    iterations=self.iterations,
                    fill_holes=True,
                    correct_aspect=self.use_correct_aspect,
                    force_uv_sync=force_uv_sync,
                )
            if prev_active is not None:
                context.view_layer.objects.active = prev_active

            for target in targets:
                for transform in target["transforms"]:
                    transform.apply()
            for target in targets:
                _mark_relaxed_faces(target["bm"], target.get("relax_faces"))
            _reset_live_unwrap_method_after_relax(
                context,
                targets,
                unwrap_last_props,
            )

        finally:
            restore_last_props = unwrap_last_props
            restore_tool_settings = unwrap_tool_settings
            if _is_live_unwrap_enabled(context):
                fallback_kwargs = _unwrap_kwargs_without_min_stretch(unwrap_last_props)
                fallback_method = fallback_kwargs.get("method")
                if restore_last_props and restore_last_props.get("method") == "MINIMUM_STRETCH":
                    restore_last_props = dict(restore_last_props)
                    if fallback_method:
                        restore_last_props["method"] = fallback_method
                if (
                    restore_tool_settings
                    and restore_tool_settings.get("uv_unwrap_method") == "MINIMUM_STRETCH"
                ):
                    restore_tool_settings = dict(restore_tool_settings)
                    if fallback_method:
                        restore_tool_settings["uv_unwrap_method"] = fallback_method
            _restore_unwrap_last_props(context, restore_last_props)
            _restore_tool_settings_unwrap(context.scene.tool_settings, restore_tool_settings)
            for target in targets:
                self._restore_selection(
                    target["bm"],
                    target["uv_layer"],
                    target["selection"],
                    target["uv_selection"],
                )
                target["bm"].select_flush_mode()
                bmesh.update_edit_mesh(target["mesh"], loop_triangles=False, destructive=False)

        return {'FINISHED'}


class AutoUnwrapPlasticityOperator(bpy.types.Operator):
    bl_idname = "mesh.auto_unwrap_plasticity"
    bl_label = "Unwrap"
    bl_description = (
        "Create UV seams from Plasticity surface boundaries, then unwrap and pack UVs "
        "for selected objects"
    )
    bl_options = {'REGISTER', 'UNDO'}

    unwrap_method: bpy.props.EnumProperty(
        items=[
            ('CONFORMAL', "Conformal", "Angle preserving, good for hard surface"),
            ('ANGLE_BASED', "Angle Based", "Angle based unwrap"),
            ('MINIMUM_STRETCH', "Minimum Stretch", "Reduce UV stretch iteratively"),
        ],
        name="Unwrap Method",
        default='CONFORMAL',
    )
    selection_method: bpy.props.EnumProperty(
        items=[
            ('OBJECT', "Object", "Use selected mesh objects"),
            ('FACE', "Face", "Use selected faces on edit-mode objects"),
        ],
        name="Selection Method",
        default='OBJECT',
    )
    use_select_settings: bpy.props.BoolProperty(
        name="Use Select Settings",
        description="Use Select Plasticity Face(s) settings for fillet detection",
        default=False,
    )
    select_settings_applied: bpy.props.BoolProperty(
        name="Select Settings Applied",
        default=False,
        options={'HIDDEN'},
    )
    fill_holes: bpy.props.BoolProperty(
        name="Fill Holes",
        description="Fill holes during unwrap to reduce distortion around openings",
        default=True,
    )
    correct_aspect: bpy.props.BoolProperty(
        name="Correct Aspect",
        description="Correct image aspect ratio",
        default=True,
    )
    use_subsurf_data: bpy.props.BoolProperty(
        name="Use Subdivision Surface",
        description="Use subdivision data for calculating unwrap",
        default=False,
    )
    use_weights: bpy.props.BoolProperty(
        name="Importance Weights",
        description="Weight projection by importance when minimizing stretch",
        default=False,
    )
    margin_method: bpy.props.EnumProperty(
        items=[
            ('SCALED', "Scaled", "Use the scaled margin method"),
            ('ADD', "Add", "Use the additive margin method"),
            ('FRACTION', "Fraction", "Use the fractional margin method"),
        ],
        name="Margin Method",
        default='SCALED',
    )
    margin: bpy.props.FloatProperty(
        name="Margin",
        description="Space between UV islands",
        default=0.001,
        min=0.0,
        max=1.0,
        step=0.001,
        precision=4,
    )
    iterations: bpy.props.IntProperty(
        name="Iterations",
        description="Number of iterations for minimum stretch",
        default=5,
        min=1,
        max=1000,
    )
    no_flip: bpy.props.BoolProperty(
        name="No Flip",
        description="Disallow flipped faces",
        default=False,
    )
    preserve_existing_seams: bpy.props.BoolProperty(
        name="Preserve Existing Seams",
        description="Keep existing seams and add Plasticity seams on top",
        default=False,
    )
    merge_fillets: bpy.props.BoolProperty(
        name="Merge Fillets Into Neighbors",
        description="Treat fillet groups as part of their largest neighbor",
        default=False,
    )
    fillet_min_curvature_angle: bpy.props.FloatProperty(
        name="Min Curvature Angle",
        description="Minimum normal deviation (degrees) to treat a group as curved",
        default=5.0,
        min=0.0,
        max=90.0,
    )
    fillet_max_area_ratio: bpy.props.FloatProperty(
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
    fillet_min_adjacent_groups: bpy.props.IntProperty(
        name="Min Adjacent Groups",
        description="Minimum adjacent group count for a fillet candidate",
        default=2,
        min=1,
        max=8,
    )
    include_vertex_adjacency: bpy.props.BoolProperty(
        name="Include Vertex Adjacent",
        description="Also consider Plasticity groups that only touch at a vertex",
        default=False,
    )
    vertex_adjacent_max_length_ratio: bpy.props.FloatProperty(
        name="Max Vertex Adjacent Length Ratio",
        description="Limit vertex-adjacent fillet selection by relative size (1.0 disables)",
        default=0.5,
        min=0.0,
        max=10.0,
        step=0.01,
        precision=2,
    )
    mark_open_edges: bpy.props.BoolProperty(
        name="Mark Open Edges",
        description="Always mark open boundaries as seams",
        default=True,
    )
    average_islands: bpy.props.BoolProperty(
        name="Average Islands Scale",
        description="Normalize island scale after unwrap",
        default=True,
    )
    pack_islands: bpy.props.BoolProperty(
        name="Pack Islands",
        description="Pack UV islands after unwrap",
        default=False,
    )
    pack_margin: bpy.props.FloatProperty(
        name="Pack Margin",
        description="Margin used when packing islands",
        default=0.003,
        min=0.0,
        max=1000.0,
        soft_max=1.0,
        step=0.001,
        precision=4,
        subtype='FACTOR',
    )
    pack_rotate: bpy.props.BoolProperty(
        name="Rotate Islands",
        description="Allow island rotation during packing",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "selection_method", text="Selection Method")
        layout.prop(self, "unwrap_method", text="Unwrap Method")
        if self.unwrap_method == 'MINIMUM_STRETCH':
            layout.prop(self, "iterations")
            layout.prop(self, "no_flip")
            layout.prop(self, "use_weights")
            layout.prop(self, "use_subsurf_data")
            layout.prop(self, "correct_aspect")
            layout.prop(self, "margin_method")
            layout.prop(self, "margin")
        else:
            layout.prop(self, "fill_holes")
            layout.prop(self, "correct_aspect")
            layout.prop(self, "use_subsurf_data")
            layout.prop(self, "margin_method")
            layout.prop(self, "margin")
        layout.prop(self, "use_select_settings")
        layout.prop(self, "preserve_existing_seams")
        layout.prop(self, "mark_open_edges")
        layout.prop(self, "merge_fillets")
        if self.merge_fillets:
            if self.use_select_settings:
                layout.label(text="Using Select settings for fillet detection.")
            fillet_col = layout.column()
            fillet_col.enabled = not self.use_select_settings
            fillet_col.prop(self, "fillet_min_curvature_angle")
            fillet_col.prop(self, "fillet_max_area_ratio")
            fillet_col.prop(self, "fillet_min_adjacent_groups")
            fillet_col.prop(self, "include_vertex_adjacency")
            vertex_col = fillet_col.column()
            vertex_col.enabled = self.include_vertex_adjacency and fillet_col.enabled
            vertex_col.prop(self, "vertex_adjacent_max_length_ratio")
        layout.prop(self, "average_islands")
        layout.prop(self, "pack_islands")
        if self.pack_islands:
            layout.prop(self, "pack_margin")
            layout.prop(self, "pack_rotate")

    def _unwrap_kwargs(self):
        allowed = None
        try:
            rna_props = bpy.ops.uv.unwrap.get_rna_type().properties
            allowed = {prop.identifier for prop in rna_props}
        except Exception:
            allowed = None

        if self.unwrap_method == 'MINIMUM_STRETCH':
            kwargs = {
                "method": self.unwrap_method,
                "iterations": self.iterations,
                "no_flip": self.no_flip,
                "use_weights": self.use_weights,
                "use_subsurf_data": self.use_subsurf_data,
                "correct_aspect": self.correct_aspect,
                "margin_method": self.margin_method,
                "margin": self.margin,
            }
        else:
            kwargs = {
                "method": self.unwrap_method,
                "fill_holes": self.fill_holes,
                "correct_aspect": self.correct_aspect,
                "use_subsurf_data": self.use_subsurf_data,
                "margin_method": self.margin_method,
                "margin": self.margin,
            }

        if allowed is None:
            return kwargs
        return {key: value for key, value in kwargs.items() if key in allowed}

    @classmethod
    def poll(cls, context):
        if context.mode == 'EDIT_MESH':
            edit_objects = getattr(context, "objects_in_mode", None)
            if edit_objects is None:
                edit_objects = [context.active_object] if context.active_object else []
            return any(
                obj and obj.type == 'MESH' and "plasticity_id" in obj.keys()
                for obj in edit_objects
            )
        return any(obj.type == 'MESH' and "plasticity_id" in obj.keys() for obj in context.selected_objects)

    def execute(self, context):
        global _LIVE_EXPAND_SUPPRESS_AUTO_MERGE, _LIVE_EXPAND_SUSPENDED
        prev_suppress = _LIVE_EXPAND_SUPPRESS_AUTO_MERGE
        prev_suspended = _LIVE_EXPAND_SUSPENDED
        _LIVE_EXPAND_SUPPRESS_AUTO_MERGE = True
        _LIVE_EXPAND_SUSPENDED = True
        try:
            self._status_min_interval = 1.0
            self._last_status_time = 0.0
            self._last_status_text = None
            self._allow_redraw = False

            self._apply_select_settings(context)

            if context.mode == 'EDIT_MESH' and self._has_selected_plasticity_faces(context):
                self.selection_method = 'FACE'
                return self._execute_face_selection(context)

            if self.selection_method == 'FACE':
                if context.mode != 'EDIT_MESH':
                    self.report(
                        {'INFO'},
                        "Face selection mode requires Edit Mode; using Object selection.",
                    )
                    self.selection_method = 'OBJECT'
                    return self._execute_object_selection(context)
                return self._execute_face_selection(context)

            return self._execute_object_selection(context)
        finally:
            _LIVE_EXPAND_SUPPRESS_AUTO_MERGE = prev_suppress
            _LIVE_EXPAND_SUSPENDED = prev_suspended

    def _execute_object_selection(self, context):
        objects = self._get_target_objects(context)
        if not objects:
            self.report({'ERROR'}, "No mesh objects selected")
            return {'CANCELLED'}

        prev_mode = context.mode
        prev_active = context.view_layer.objects.active
        prev_selected = list(context.selected_objects)

        if context.mode != 'OBJECT':
            if prev_active is None:
                context.view_layer.objects.active = objects[0]
            bpy.ops.object.mode_set(mode='OBJECT')

        processed = 0
        skipped = 0
        total = len(objects)
        self._update_status_text(
            context,
            f"Progress: 0% (Auto Unwrap 0/{total})",
            force=True,
        )
        try:
            for idx, obj in enumerate(objects, start=1):
                if obj.type != 'MESH' or "plasticity_id" not in obj.keys():
                    skipped += 1
                    percent = int((idx / total) * 100)
                    self._update_status_text(
                        context,
                        f"Progress: {percent}% (Auto Unwrap {idx}/{total})",
                    )
                    continue

                bpy.ops.object.select_all(action='DESELECT')
                obj.select_set(True)
                context.view_layer.objects.active = obj

                if self._unwrap_object(context, obj):
                    processed += 1
                else:
                    skipped += 1

                percent = int((idx / total) * 100)
                self._update_status_text(
                    context,
                    f"Progress: {percent}% (Auto Unwrap {idx}/{total})",
                )
        finally:
            self._update_status_text(context, None, force=True)

        bpy.ops.object.select_all(action='DESELECT')
        for obj in prev_selected:
            if obj.name in bpy.data.objects:
                obj.select_set(True)
        if prev_active and prev_active.name in bpy.data.objects:
            context.view_layer.objects.active = prev_active

        if prev_mode == 'EDIT_MESH' and prev_active and prev_active.type == 'MESH':
            bpy.ops.object.mode_set(mode='EDIT')

        self.report({'INFO'}, f"Auto Unwrap: processed {processed}, skipped {skipped}")
        return {'FINISHED'}

    def _get_target_objects(self, context):
        objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not objects and context.active_object and context.active_object.type == 'MESH':
            objects = [context.active_object]
        return objects

    def _get_edit_mode_objects(self, context):
        edit_objects = getattr(context, "objects_in_mode", None)
        if edit_objects is None:
            edit_objects = [
                obj for obj in context.selected_objects
                if obj.type == 'MESH' and obj.mode == 'EDIT'
            ]
        if not edit_objects and context.active_object and context.active_object.mode == 'EDIT':
            edit_objects = [context.active_object]
        return [obj for obj in edit_objects if obj.type == 'MESH']

    def _apply_select_settings(self, context):
        if not self.use_select_settings:
            self.select_settings_applied = False
            return
        if self.select_settings_applied:
            return
        scene = context.scene
        self.merge_fillets = bool(
            getattr(scene, "prop_plasticity_select_adjacent_fillets", self.merge_fillets)
        )
        self.fillet_min_curvature_angle = float(
            getattr(
                scene,
                "prop_plasticity_select_fillet_min_curvature_angle",
                self.fillet_min_curvature_angle,
            )
        )
        self.fillet_max_area_ratio = float(
            getattr(
                scene,
                "prop_plasticity_select_fillet_max_area_ratio",
                self.fillet_max_area_ratio,
            )
        )
        self.fillet_min_adjacent_groups = int(
            getattr(
                scene,
                "prop_plasticity_select_fillet_min_adjacent_groups",
                self.fillet_min_adjacent_groups,
            )
        )
        self.include_vertex_adjacency = bool(
            getattr(
                scene,
                "prop_plasticity_select_include_vertex_adjacency",
                self.include_vertex_adjacency,
            )
        )
        self.vertex_adjacent_max_length_ratio = float(
            getattr(
                scene,
                "prop_plasticity_select_vertex_adjacent_max_length_ratio",
                self.vertex_adjacent_max_length_ratio,
            )
        )
        self.select_settings_applied = True

    def _has_selected_plasticity_faces(self, context):
        edit_objects = self._get_edit_mode_objects(context)
        for obj in edit_objects:
            if obj.type != 'MESH' or "plasticity_id" not in obj.keys():
                continue
            mesh = obj.data
            groups = mesh.get("groups")
            face_ids = mesh.get("face_ids")
            if not groups or not face_ids:
                continue
            bm = bmesh.from_edit_mesh(mesh)
            if get_selected_group_ids(groups, mesh, bm):
                return True
        return False

    def _unwrap_object(self, context, obj):
        mesh = obj.data
        groups = mesh.get("groups")
        face_ids = mesh.get("face_ids")
        if not groups or not face_ids:
            self.report({'WARNING'}, f"{obj.name}: Missing Plasticity groups/face_ids")
            return False

        if not mesh.uv_layers:
            mesh.uv_layers.new(name="UVMap")

        if not self._mark_plasticity_seams(mesh, None, edit_bmesh=None):
            return False
        _touch_seams_version(mesh)
        _invalidate_live_expand_overlay_cache()

        bpy.ops.object.mode_set(mode='EDIT')
        prev_uv_sync = context.tool_settings.use_uv_select_sync
        context.tool_settings.use_uv_select_sync = True
        try:
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.unwrap(**self._unwrap_kwargs())
            if self.average_islands:
                bpy.ops.uv.average_islands_scale()
            if self.pack_islands:
                bpy.ops.uv.pack_islands(
                    rotate=self.pack_rotate,
                    margin=self.pack_margin,
                )
        finally:
            context.tool_settings.use_uv_select_sync = prev_uv_sync
        bpy.ops.object.mode_set(mode='OBJECT')
        return True

    def _execute_face_selection(self, context):
        edit_objects = self._get_edit_mode_objects(context)
        if not edit_objects:
            self.report({'ERROR'}, "No mesh objects in Edit Mode")
            return {'CANCELLED'}

        processed = 0
        skipped = 0
        total = len(edit_objects)
        self._update_status_text(
            context,
            f"Progress: 0% (Auto Unwrap 0/{total})",
            force=True,
        )
        try:
            for idx, obj in enumerate(edit_objects, start=1):
                if obj.type != 'MESH' or "plasticity_id" not in obj.keys():
                    skipped += 1
                    percent = int((idx / total) * 100)
                    self._update_status_text(
                        context,
                        f"Progress: {percent}% (Auto Unwrap {idx}/{total})",
                    )
                    continue

                mesh = obj.data
                groups = mesh.get("groups")
                face_ids = mesh.get("face_ids")
                if not groups or not face_ids:
                    skipped += 1
                    percent = int((idx / total) * 100)
                    self._update_status_text(
                        context,
                        f"Progress: {percent}% (Auto Unwrap {idx}/{total})",
                    )
                    continue

                if not mesh.uv_layers:
                    mesh.uv_layers.new(name="UVMap")

                bm = bmesh.from_edit_mesh(mesh)
                selected_group_indices, _ = expand_plasticity_selection(
                    groups,
                    mesh,
                    bm,
                    self.merge_fillets,
                    self.fillet_min_curvature_angle,
                    self.fillet_max_area_ratio,
                    self.fillet_min_adjacent_groups,
                    self.include_vertex_adjacency,
                    self.vertex_adjacent_max_length_ratio,
                    allow_full_selection_seed=True,
                )
                if not selected_group_indices:
                    percent = int((idx / total) * 100)
                    self._update_status_text(
                        context,
                        f"Progress: {percent}% (Auto Unwrap {idx}/{total})",
                    )
                    continue

                if self._mark_plasticity_seams(
                    mesh,
                    selected_group_indices,
                    edit_bmesh=bm,
                ):
                    _touch_seams_version(mesh)
                    _invalidate_live_expand_overlay_cache()
                    processed += 1
                else:
                    skipped += 1

                percent = int((idx / total) * 100)
                self._update_status_text(
                    context,
                    f"Progress: {percent}% (Auto Unwrap {idx}/{total})",
                )
        finally:
            self._update_status_text(context, None, force=True)

        if processed == 0:
            self.report({'ERROR'}, "No Plasticity faces selected")
            return {'CANCELLED'}

        self._unwrap_edit_selection(context)
        self.report({'INFO'}, f"Auto Unwrap: processed {processed}, skipped {skipped}")
        return {'FINISHED'}

    def _unwrap_edit_selection(self, context):
        prev_uv_sync = context.tool_settings.use_uv_select_sync
        context.tool_settings.use_uv_select_sync = True
        try:
            bpy.ops.uv.unwrap(**self._unwrap_kwargs())
            if self.average_islands:
                bpy.ops.uv.average_islands_scale()
            if self.pack_islands:
                bpy.ops.uv.pack_islands(
                    rotate=self.pack_rotate,
                    margin=self.pack_margin,
                )
        finally:
            context.tool_settings.use_uv_select_sync = prev_uv_sync
        return True

    def _update_status_text(self, context, text, force=False):
        workspace = context.workspace
        if not workspace:
            return
        if text is None:
            force = True
        now = time.monotonic()
        last_time = getattr(self, "_last_status_time", 0.0)
        last_text = getattr(self, "_last_status_text", None)
        min_interval = getattr(self, "_status_min_interval", 0.5)
        if not force:
            if text == last_text:
                return
            if (now - last_time) < min_interval:
                return
        should_redraw = force or (now - last_time) >= min_interval
        self._last_status_time = now
        self._last_status_text = text
        workspace.status_text_set(text)
        if should_redraw and self._allow_redraw:
            try:
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
            except Exception:
                pass

    def _mark_plasticity_seams(
        self,
        mesh,
        selected_group_indices,
        edit_bmesh=None,
        use_selection_boundary=False,
    ):
        if edit_bmesh is None:
            bm = bmesh.new()
            bm.from_mesh(mesh)
            use_edit_mesh = False
        else:
            bm = edit_bmesh
            use_edit_mesh = True
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        groups = mesh["groups"]
        group_faces, face_to_group, group_areas, group_max_angles = build_group_data(
            groups, mesh, bm)
        group_count = len(group_faces)
        if group_count == 0:
            if not use_edit_mesh:
                bm.free()
            return False

        if not self.preserve_existing_seams:
            if selected_group_indices is None:
                for edge in bm.edges:
                    edge.seam = False
            else:
                for edge in bm.edges:
                    if self._edge_touches_groups(edge, face_to_group, selected_group_indices):
                        edge.seam = False

        adjacency = build_group_adjacency(bm, face_to_group, group_count)
        if self.include_vertex_adjacency:
            vertex_adjacency = build_group_vertex_adjacency(
                bm, face_to_group, group_count)
            adjacency = [
                adjacency[i] | vertex_adjacency[i]
                for i in range(group_count)
            ]

        merge_targets = list(range(group_count))
        fillet_groups = set()
        if self.merge_fillets:
            candidate_groups = (
                range(group_count)
                if selected_group_indices is None
                else selected_group_indices
            )
            fillet_groups = {
                group_idx for group_idx in candidate_groups
                if is_fillet_group(
                    group_idx,
                    group_areas,
                    group_max_angles,
                    adjacency,
                    self.fillet_min_curvature_angle,
                    self.fillet_max_area_ratio,
                    self.fillet_min_adjacent_groups,
                )
            }
            if fillet_groups:
                for group_idx in fillet_groups:
                    neighbors = adjacency[group_idx]
                    if not neighbors:
                        continue
                    target = self._pick_merge_neighbor(
                        neighbors, group_areas, fillet_groups, selected_group_indices)
                    if target is not None:
                        merge_targets[group_idx] = target
                merge_targets = self._resolve_merge_targets(merge_targets)

        selected_merge_targets = set()
        if use_selection_boundary and selected_group_indices is not None:
            selected_merge_targets = {
                merge_targets[group_idx] for group_idx in selected_group_indices
            }

        def is_face_selected(face):
            if not use_selection_boundary:
                group_idx = face_to_group.get(face.index)
                return group_idx in selected_group_indices
            if face.select:
                return True
            if not self.merge_fillets or not fillet_groups:
                return False
            group_idx = face_to_group.get(face.index)
            if group_idx is None or group_idx not in fillet_groups:
                return False
            return merge_targets[group_idx] in selected_merge_targets

        ignore_group_boundaries = False
        if use_selection_boundary and selected_group_indices is not None:
            # Partial group selections imply the selection boundary should drive seams.
            for group_idx in selected_group_indices:
                if group_idx >= len(group_faces):
                    continue
                faces = group_faces[group_idx]
                if not faces:
                    continue
                selected_count = 0
                for face_index in faces:
                    if face_index < len(bm.faces) and bm.faces[face_index].select:
                        selected_count += 1
                if selected_count and selected_count < len(faces):
                    ignore_group_boundaries = True
                    break

        if ignore_group_boundaries:
            for edge in bm.edges:
                if len(edge.link_faces) != 2:
                    continue
                face_a, face_b = edge.link_faces
                if is_face_selected(face_a) and is_face_selected(face_b):
                    edge.seam = False

        for edge in bm.edges:
            if len(edge.link_faces) == 0:
                continue
            if len(edge.link_faces) == 1:
                if self.mark_open_edges:
                    if selected_group_indices is None:
                        edge.seam = True
                    else:
                        face = edge.link_faces[0]
                        if is_face_selected(face):
                            edge.seam = True
                continue
            if len(edge.link_faces) != 2:
                if self.mark_open_edges:
                    if selected_group_indices is None:
                        edge.seam = True
                    else:
                        if any(is_face_selected(face) for face in edge.link_faces):
                            edge.seam = True
                continue

            face_a, face_b = edge.link_faces
            group_a = face_to_group.get(face_a.index)
            group_b = face_to_group.get(face_b.index)
            if group_a is None or group_b is None:
                continue
            if selected_group_indices is None:
                if merge_targets[group_a] != merge_targets[group_b]:
                    edge.seam = True
            else:
                selected_a = is_face_selected(face_a)
                selected_b = is_face_selected(face_b)
                if selected_a and selected_b:
                    if not ignore_group_boundaries and merge_targets[group_a] != merge_targets[group_b]:
                        edge.seam = True
                elif selected_a or selected_b:
                    edge.seam = True

        if use_edit_mesh:
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        else:
            bm.to_mesh(mesh)
            bm.free()
        return True

    def _edge_touches_groups(self, edge, face_to_group, selected_group_indices):
        for face in edge.link_faces:
            group_idx = face_to_group.get(face.index)
            if group_idx in selected_group_indices:
                return True
        return False

    def _pick_merge_neighbor(self, neighbors, group_areas, fillet_groups, allowed_groups):
        best_neighbor = None
        best_area = -1.0
        for neighbor_idx in neighbors:
            if neighbor_idx in fillet_groups:
                continue
            if allowed_groups is not None and neighbor_idx not in allowed_groups:
                continue
            area = group_areas[neighbor_idx]
            if area > best_area:
                best_neighbor = neighbor_idx
                best_area = area
        if best_neighbor is None:
            for neighbor_idx in neighbors:
                if allowed_groups is not None and neighbor_idx not in allowed_groups:
                    continue
                area = group_areas[neighbor_idx]
                if area > best_area:
                    best_neighbor = neighbor_idx
                    best_area = area
        return best_neighbor

    def _resolve_merge_targets(self, merge_targets):
        resolved = list(merge_targets)
        for idx in range(len(merge_targets)):
            seen = set()
            target = merge_targets[idx]
            while target != merge_targets[target] and target not in seen:
                seen.add(target)
                target = merge_targets[target]
            resolved[idx] = target
        return resolved


class AutoMarkEdgesOperator(bpy.types.Operator):
    bl_idname = "mesh.auto_mark_edges"
    bl_label = "Auto Mark Edges"
    bl_description = (
        "Mark seams/sharp edges around Plasticity face groups. "
        "Edit Mode uses selected faces; Object Mode uses whole objects"
    )
    bl_options = {'REGISTER', 'UNDO'}

    mark_smart: bpy.props.BoolProperty(name="Smart Edges Marking", default=False)
    mark_sharp: bpy.props.BoolProperty(name="Mark Sharp", default=False)
    mark_seam: bpy.props.BoolProperty(name="Mark Seam", default=True)

    @classmethod
    def poll(cls, context):
        return (
            any("plasticity_id" in obj.keys() and obj.type ==
                'MESH' for obj in context.selected_objects)
            or (context.mode == 'EDIT_MESH' and context.active_object and "plasticity_id" in context.active_object.keys())
        )

    def execute(self, context):
        prev_obj_mode = bpy.context.object.mode

        if context.mode == 'EDIT_MESH':
            obj = context.active_object
            mesh = obj.data
            bm = bmesh.from_edit_mesh(mesh)
            groups = mesh["groups"]
            selected_group_ids = get_selected_group_ids(groups, mesh, bm)
            if len(selected_group_ids) == 0:
                bpy.ops.object.mode_set(mode='OBJECT')
                self.mark_sharp_edges(obj, groups)
                bpy.ops.object.mode_set(mode='EDIT')
            else:
                self.mark_edges_for_selected_faces(context, selected_group_ids)
        else:
            for obj in context.selected_objects:
                if obj.type != 'MESH':
                    continue
                if not "plasticity_id" in obj.keys():
                    continue

                mesh = obj.data
                bpy.ops.object.mode_set(mode='OBJECT')

                if "plasticity_id" not in obj.keys():
                    self.report(
                        {'ERROR'}, "Object doesn't have a plasticity_id attribute.")
                    return {'CANCELLED'}

                groups = mesh["groups"]
                self.mark_sharp_edges(obj, groups)

        bpy.ops.object.mode_set(mode=prev_obj_mode)
        return {'FINISHED'}

    def mark_edges_for_selected_faces(self, context, selected_group_ids):
        obj = context.active_object
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)

        boundary_edges = get_boundary_edges_for_group_ids(
            mesh["groups"], mesh, bm, selected_group_ids)

        for edge in boundary_edges:
            if self.mark_sharp:
                edge.smooth = False
            if self.mark_seam:
                edge.seam = True

        bmesh.update_edit_mesh(mesh)
        _touch_seams_version(mesh)
        _invalidate_live_expand_overlay_cache()

    def mark_sharp_edges(self, obj, groups):
        mesh = obj.data
        bm = bmesh.new()
        # mesh.calc_normals_split()
        bm.from_mesh(mesh)
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        loops = mesh.loops

        all_face_boundary_edges = face_boundary_edges(groups, mesh, bm)

        split_edges = set()
        if self.mark_smart:
            for vert in bm.verts:
                for edge in vert.link_edges:
                    loops_for_vert_and_edge = []
                    for face in edge.link_faces:
                        for loop in face.loops:
                            if loop.vert == vert:
                                loops_for_vert_and_edge.append(loop)
                    if len(loops_for_vert_and_edge) != 2:
                        continue
                    loop1, loop2 = loops_for_vert_and_edge
                    normal1 = loops[loop1.index].normal
                    normal2 = loops[loop2.index].normal
                    if are_normals_different(normal1, normal2):
                        split_edges.add(edge)

        for edge in all_face_boundary_edges:
            if self.mark_sharp:
                if self.mark_smart and edge in split_edges:
                    edge.smooth = False
                elif not self.mark_smart:
                    edge.smooth = False

            if self.mark_seam:
                if self.mark_smart and edge in split_edges:
                    edge.seam = True
                elif not self.mark_smart:
                    edge.seam = True

        bm.to_mesh(obj.data)
        bm.free()
        _touch_seams_version(mesh)
        _invalidate_live_expand_overlay_cache()


def _group_index_mode(groups, mesh):
    if not groups:
        return "loops"
    counts_total = 0
    max_end = 0
    group_len = len(groups)
    for idx in range(0, group_len, 2):
        start = int(groups[idx])
        count = int(groups[idx + 1]) if idx + 1 < group_len else 0
        counts_total += count
        end = start + count
        if end > max_end:
            max_end = end
    if max_end <= len(mesh.polygons):
        return "faces"
    if max_end <= len(mesh.loops):
        return "loops"
    if counts_total == len(mesh.polygons):
        return "faces"
    if counts_total == len(mesh.loops):
        return "loops"
    return "loops"


def _iter_group_ranges(groups, face_ids):
    group_count = min(len(groups) // 2, len(face_ids))
    ranges = []
    for group_idx in range(group_count):
        start = int(groups[group_idx * 2])
        count = int(groups[group_idx * 2 + 1])
        face_id = int(face_ids[group_idx])
        if count <= 0:
            continue
        ranges.append((start, count, face_id))
    ranges.sort(key=lambda item: item[0])
    return ranges


def _face_id_coverage(face_id_by_face):
    return sum(1 for face_id in face_id_by_face if face_id is not None)


def _build_face_id_map_faces(ranges, mesh):
    face_count = len(mesh.polygons)
    face_id_by_face = [None] * face_count
    for start, count, face_id in ranges:
        if start < 0 or count <= 0:
            continue
        end = min(start + count, face_count)
        for face_index in range(start, end):
            if face_id_by_face[face_index] is None:
                face_id_by_face[face_index] = face_id
    return face_id_by_face


def _build_face_id_map_loops(ranges, mesh):
    loop_count = len(mesh.loops)
    loop_face_ids = [None] * loop_count
    for start, count, face_id in ranges:
        if start < 0 or count <= 0:
            continue
        end = min(start + count, loop_count)
        for loop_index in range(start, end):
            if loop_face_ids[loop_index] is None:
                loop_face_ids[loop_index] = face_id

    face_id_by_face = [None] * len(mesh.polygons)
    for poly in mesh.polygons:
        loop_start = poly.loop_start
        loop_end = loop_start + poly.loop_total
        best_face_id = None
        best_count = 0
        counts = {}
        for loop_index in range(loop_start, loop_end):
            face_id = loop_face_ids[loop_index]
            if face_id is None:
                continue
            count = counts.get(face_id, 0) + 1
            counts[face_id] = count
            if count > best_count:
                best_count = count
                best_face_id = face_id
        face_id_by_face[poly.index] = best_face_id
    return face_id_by_face


def _build_face_id_map(groups, face_ids, mesh):
    face_count = len(mesh.polygons)
    face_id_by_face = [None] * face_count
    if not groups or not face_ids or face_count == 0:
        return face_id_by_face

    ranges = _iter_group_ranges(groups, face_ids)
    if not ranges:
        return face_id_by_face

    mode = _group_index_mode(groups, mesh)
    face_map = _build_face_id_map_faces(ranges, mesh)
    loop_map = _build_face_id_map_loops(ranges, mesh)

    if mode == "faces":
        primary = face_map
        secondary = loop_map
    else:
        primary = loop_map
        secondary = face_map

    if _face_id_coverage(secondary) > _face_id_coverage(primary):
        return secondary
    return primary


_PLASTICITY_GROUP_CACHE = {}


def _get_group_cache_key(mesh):
    try:
        return mesh.as_pointer()
    except Exception:
        return id(mesh)


def _get_group_cache(mesh, groups=None, face_ids=None):
    if mesh is None:
        return None
    if groups is None:
        groups = mesh.get("groups")
    if face_ids is None:
        face_ids = mesh.get("face_ids")
    if not groups or not face_ids:
        return None

    version_token = mesh.get("plasticity_groups_version")
    if version_token is None:
        version = (len(groups), len(face_ids), len(mesh.polygons), len(mesh.loops))
    else:
        version = int(version_token)

    key = _get_group_cache_key(mesh)
    cache = _PLASTICITY_GROUP_CACHE.get(key)
    if cache:
        mesh_name = cache.get("mesh_name")
        if mesh_name and mesh_name != mesh.name_full:
            _PLASTICITY_GROUP_CACHE.pop(key, None)
            cache = None
        elif mesh_name and bpy.data.meshes.get(mesh_name) is None:
            _PLASTICITY_GROUP_CACHE.pop(key, None)
            cache = None
    if cache and cache.get("version") == version:
        return cache

    face_id_by_face = _build_face_id_map(groups, face_ids, mesh)
    face_id_to_group = {}
    group_faces = []
    face_to_group = {}

    for face_index, face_id in enumerate(face_id_by_face):
        if face_id is None:
            continue
        group_idx = face_id_to_group.get(face_id)
        if group_idx is None:
            group_idx = len(group_faces)
            face_id_to_group[face_id] = group_idx
            group_faces.append([])
        group_faces[group_idx].append(face_index)
        face_to_group[face_index] = group_idx

    cache = {
        "mesh_name": mesh.name_full,
        "version": version,
        "group_faces": group_faces,
        "face_to_group": face_to_group,
        "group_count": len(group_faces),
    }
    _PLASTICITY_GROUP_CACHE[key] = cache
    return cache


def face_boundary_edges(groups, mesh, bm):
    bm.faces.ensure_lookup_table()
    face_id_by_face = _build_face_id_map(groups, mesh.get("face_ids"), mesh)
    boundary_edges = set()

    for edge in bm.edges:
        faces = edge.link_faces
        if len(faces) != 2:
            boundary_edges.add(edge)
            continue
        face_a, face_b = faces
        id_a = face_id_by_face[face_a.index] if face_a.index < len(face_id_by_face) else None
        id_b = face_id_by_face[face_b.index] if face_b.index < len(face_id_by_face) else None
        if id_a is None or id_b is None or id_a != id_b:
            boundary_edges.add(edge)

    return boundary_edges


def build_group_faces_map(groups, mesh, bm):
    cache = _get_group_cache(mesh, groups, mesh.get("face_ids"))
    if cache is None:
        return [], {}
    return cache["group_faces"], cache["face_to_group"]


def collect_group_selection(groups, mesh, bm):
    group_faces, face_to_group = build_group_faces_map(groups, mesh, bm)
    selected_counts = [0 for _ in range(len(group_faces))]
    for face in bm.faces:
        if not face.select:
            continue
        group_idx = face_to_group.get(face.index)
        if group_idx is not None:
            selected_counts[group_idx] += 1
    selected_group_indices = {
        group_idx for group_idx, count in enumerate(selected_counts) if count
    }
    partial_group_indices = {
        group_idx
        for group_idx, count in enumerate(selected_counts)
        if count and count < len(group_faces[group_idx])
    }
    return group_faces, face_to_group, selected_group_indices, partial_group_indices


def compute_group_stats(group_faces, bm):
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    group_areas = [0.0 for _ in range(len(group_faces))]
    group_normal_sums = [
        mathutils.Vector((0.0, 0.0, 0.0)) for _ in range(len(group_faces))
    ]
    for group_idx, faces in enumerate(group_faces):
        for face_index in faces:
            if face_index >= len(bm.faces):
                continue
            face = bm.faces[face_index]
            group_areas[group_idx] += face.calc_area()
            group_normal_sums[group_idx] += face.normal

    group_max_angles = [0.0 for _ in range(len(group_faces))]
    for group_idx, faces in enumerate(group_faces):
        normal_sum = group_normal_sums[group_idx]
        if normal_sum.length_squared > 0.0:
            avg_normal = normal_sum.normalized()
        else:
            avg_normal = mathutils.Vector((0.0, 0.0, 1.0))

        max_angle = 0.0
        for face_index in faces:
            if face_index >= len(bm.faces):
                continue
            face = bm.faces[face_index]
            dot = max(-1.0, min(1.0, avg_normal.dot(face.normal)))
            angle = math.degrees(math.acos(dot))
            if angle > max_angle:
                max_angle = angle
        group_max_angles[group_idx] = max_angle
    return group_areas, group_max_angles


def compute_group_bbox_sizes(group_faces, bm):
    bm.faces.ensure_lookup_table()
    inf = float("inf")
    group_mins = [mathutils.Vector((inf, inf, inf)) for _ in range(len(group_faces))]
    group_maxs = [mathutils.Vector((-inf, -inf, -inf)) for _ in range(len(group_faces))]

    for group_idx, faces in enumerate(group_faces):
        min_v = group_mins[group_idx]
        max_v = group_maxs[group_idx]
        for face_index in faces:
            if face_index >= len(bm.faces):
                continue
            face = bm.faces[face_index]
            for vert in face.verts:
                co = vert.co
                if co.x < min_v.x:
                    min_v.x = co.x
                if co.y < min_v.y:
                    min_v.y = co.y
                if co.z < min_v.z:
                    min_v.z = co.z
                if co.x > max_v.x:
                    max_v.x = co.x
                if co.y > max_v.y:
                    max_v.y = co.y
                if co.z > max_v.z:
                    max_v.z = co.z

    sizes = []
    for idx in range(len(group_faces)):
        min_v = group_mins[idx]
        max_v = group_maxs[idx]
        if min_v.x == inf:
            sizes.append(0.0)
            continue
        dims = max_v - min_v
        sizes.append(max(dims.x, dims.y, dims.z))
    return sizes


def expand_plasticity_selection(
    groups,
    mesh,
    bm,
    select_adjacent_fillets,
    fillet_min_curvature_angle,
    fillet_max_area_ratio,
    fillet_min_adjacent_groups,
    include_vertex_adjacency,
    vertex_adjacent_max_length_ratio,
    allow_full_selection_seed=True,
    seed_group_indices=None,
):
    try:
        vertex_adjacent_max_length_ratio = float(vertex_adjacent_max_length_ratio)
    except Exception:
        vertex_adjacent_max_length_ratio = 1.0

    group_faces, face_to_group, selected_group_indices, partial_group_indices = collect_group_selection(
        groups, mesh, bm)
    if not group_faces:
        return set(), set()

    if seed_group_indices is None:
        if partial_group_indices:
            seed_group_indices = partial_group_indices
        elif allow_full_selection_seed:
            seed_group_indices = selected_group_indices
        else:
            seed_group_indices = set()

    fillet_group_indices = set()
    if select_adjacent_fillets and seed_group_indices:
        group_areas, group_max_angles = compute_group_stats(group_faces, bm)
        edge_adjacency = build_group_adjacency(bm, face_to_group, len(group_faces))
        vertex_adjacency = None
        vertex_only_candidates = set()
        vertex_adjacent_filter = (
            include_vertex_adjacency
            and vertex_adjacent_max_length_ratio is not None
            and float(vertex_adjacent_max_length_ratio) < 1.0
        )
        group_sizes = None

        if include_vertex_adjacency:
            vertex_adjacency = build_group_vertex_adjacency(
                bm, face_to_group, len(group_faces))
            if vertex_adjacent_filter:
                group_sizes = compute_group_bbox_sizes(group_faces, bm)
            adjacency = [
                edge_adjacency[i] | vertex_adjacency[i]
                for i in range(len(edge_adjacency))
            ]
            edge_neighbors = set()
            for group_idx in seed_group_indices:
                if group_idx < len(edge_adjacency):
                    edge_neighbors.update(edge_adjacency[group_idx])
            vertex_neighbors = set()
            for group_idx in seed_group_indices:
                if group_idx < len(vertex_adjacency):
                    vertex_neighbors.update(vertex_adjacency[group_idx])
            vertex_only_candidates = vertex_neighbors - edge_neighbors
        else:
            adjacency = edge_adjacency

        candidate_groups = set()
        for group_idx in seed_group_indices:
            if group_idx < len(adjacency):
                candidate_groups.update(adjacency[group_idx])
        candidate_groups.difference_update(seed_group_indices)

        if vertex_adjacent_filter and vertex_only_candidates:
            seed_sizes = [
                group_sizes[idx]
                for idx in seed_group_indices
                if idx < len(group_sizes) and group_sizes[idx] > 0.0
            ]
            seed_min_size = min(seed_sizes) if seed_sizes else 0.0

        for group_idx in candidate_groups:
            if (
                vertex_adjacent_filter
                and group_idx in vertex_only_candidates
                and group_sizes is not None
            ):
                neighbor_seeds = set()
                if vertex_adjacency and group_idx < len(vertex_adjacency):
                    neighbor_seeds = vertex_adjacency[group_idx] & seed_group_indices
                ref_size = seed_min_size
                if neighbor_seeds:
                    neighbor_sizes = [
                        group_sizes[idx]
                        for idx in neighbor_seeds
                        if idx < len(group_sizes) and group_sizes[idx] > 0.0
                    ]
                    if neighbor_sizes:
                        ref_size = min(neighbor_sizes)
                if ref_size > 0.0:
                    max_size = ref_size * float(vertex_adjacent_max_length_ratio)
                    if group_sizes[group_idx] > max_size:
                        continue
            if is_fillet_group(
                group_idx,
                group_areas,
                group_max_angles,
                adjacency,
                fillet_min_curvature_angle,
                fillet_max_area_ratio,
                fillet_min_adjacent_groups,
            ):
                fillet_group_indices.add(group_idx)

    final_group_indices = set(selected_group_indices)
    final_group_indices.update(seed_group_indices)
    final_group_indices.update(fillet_group_indices)

    bm.faces.ensure_lookup_table()
    for group_idx in final_group_indices:
        if group_idx >= len(group_faces):
            continue
        for face_index in group_faces[group_idx]:
            if face_index < len(bm.faces):
                bm.faces[face_index].select = True

    return final_group_indices, partial_group_indices


def get_boundary_edges_for_group_ids(groups, mesh, bm, selected_group_ids):
    boundary_edges = set()
    if not selected_group_ids:
        return boundary_edges

    selected_group_indices = {group_id // 2 for group_id in selected_group_ids}
    group_faces, face_to_group = build_group_faces_map(groups, mesh, bm)
    for face in bm.faces:
        group_idx = face_to_group.get(face.index)
        if group_idx in selected_group_indices:
            for edge in face.edges:
                if edge in boundary_edges:
                    boundary_edges.remove(edge)
                else:
                    boundary_edges.add(edge)
    return boundary_edges


def get_selected_group_ids(groups, mesh, bm):
    _, _, selected_group_indices, _ = collect_group_selection(
        groups, mesh, bm)
    return {group_idx * 2 for group_idx in selected_group_indices}

_LIVE_REFACET_TIMER_RUNNING = False
_LIVE_REFACET_LAST_SIGNATURE = None
_LIVE_REFACET_LAST_APPLIED_SIGNATURE = None
_LIVE_REFACET_LAST_CHANGE_TIME = 0.0
_LIVE_REFACET_INTERVAL_DEFAULT = 0.2


def _get_live_refacet_interval(scene):
    value = getattr(scene, "prop_plasticity_live_refacet_interval", _LIVE_REFACET_INTERVAL_DEFAULT)
    try:
        value = float(value)
    except Exception:
        value = _LIVE_REFACET_INTERVAL_DEFAULT
    return max(0.0, value)


def ensure_live_refacet_timer():
    global _LIVE_REFACET_TIMER_RUNNING
    global _LIVE_REFACET_LAST_SIGNATURE, _LIVE_REFACET_LAST_APPLIED_SIGNATURE
    global _LIVE_REFACET_LAST_CHANGE_TIME
    if _LIVE_REFACET_TIMER_RUNNING:
        return
    _LIVE_REFACET_TIMER_RUNNING = True
    _LIVE_REFACET_LAST_SIGNATURE = None
    _LIVE_REFACET_LAST_APPLIED_SIGNATURE = None
    _LIVE_REFACET_LAST_CHANGE_TIME = 0.0
    scene = bpy.context.scene
    interval = _get_live_refacet_interval(scene) if scene else _LIVE_REFACET_INTERVAL_DEFAULT
    bpy.app.timers.register(_live_refacet_timer, first_interval=interval)


def stop_live_refacet_timer():
    global _LIVE_REFACET_TIMER_RUNNING
    global _LIVE_REFACET_LAST_SIGNATURE, _LIVE_REFACET_LAST_APPLIED_SIGNATURE
    global _LIVE_REFACET_LAST_CHANGE_TIME
    if _LIVE_REFACET_TIMER_RUNNING:
        try:
            bpy.app.timers.unregister(_live_refacet_timer)
        except Exception:
            pass
    _LIVE_REFACET_TIMER_RUNNING = False
    _LIVE_REFACET_LAST_SIGNATURE = None
    _LIVE_REFACET_LAST_APPLIED_SIGNATURE = None
    _LIVE_REFACET_LAST_CHANGE_TIME = 0.0


def _build_refacet_signature(context):
    if context is None:
        return None
    scene = context.scene
    if scene is None:
        return None
    selected = []
    for obj in context.selected_objects:
        if obj.type != 'MESH':
            continue
        if "plasticity_id" not in obj.keys():
            continue
        filename = obj.get("plasticity_filename")
        plasticity_id = obj.get("plasticity_id")
        if filename is None or plasticity_id is None:
            continue
        selected.append((filename, int(plasticity_id)))
    if not selected:
        return None
    selected.sort()

    advanced = bool(scene.prop_plasticity_ui_show_advanced_facet)
    use_presets = (
        len(scene.refacet_presets) > 0
        and 0 <= scene.active_refacet_preset_index < len(scene.refacet_presets)
    )
    preset_index = scene.active_refacet_preset_index if use_presets else -1

    if use_presets:
        preset = scene.refacet_presets[preset_index]
        base = (
            preset.facet_tri_or_ngon,
            None if advanced else float(preset.tolerance),
            None if advanced else float(preset.angle),
        )
        if advanced:
            advanced_values = (
                float(preset.min_width),
                float(preset.max_width),
                float(preset.Edge_chord_tolerance),
                float(preset.Edge_Angle_tolerance),
                float(preset.Face_plane_tolerance),
                float(preset.Face_Angle_tolerance),
                float(preset.plane_angle),
                bool(preset.convex_ngons_only),
                bool(preset.curve_max_length_enabled),
                float(preset.curve_max_length),
                bool(preset.relative_to_bbox),
                bool(preset.match_topology),
            )
        else:
            advanced_values = None
    else:
        base = (
            scene.prop_plasticity_facet_tri_or_ngon,
            None if advanced else float(scene.prop_plasticity_facet_tolerance),
            None if advanced else float(scene.prop_plasticity_facet_angle),
        )
        if advanced:
            advanced_values = (
                float(scene.prop_plasticity_facet_min_width),
                float(scene.prop_plasticity_facet_max_width),
                float(scene.prop_plasticity_curve_chord_tolerance),
                float(scene.prop_plasticity_curve_angle_tolerance),
                float(scene.prop_plasticity_surface_plane_tolerance),
                float(scene.prop_plasticity_surface_angle_tolerance),
                float(scene.prop_plasticity_plane_angle),
                bool(scene.prop_plasticity_convex_ngons_only),
                bool(scene.prop_plasticity_curve_max_length_enabled),
                float(scene.prop_plasticity_curve_max_length),
                bool(scene.prop_plasticity_relative_to_bbox),
                bool(scene.prop_plasticity_match_topology),
            )
        else:
            advanced_values = None

    return (
        use_presets,
        preset_index,
        advanced,
        base,
        advanced_values,
        tuple(selected),
    )


def _live_refacet_timer():
    global _LIVE_REFACET_TIMER_RUNNING
    global _LIVE_REFACET_LAST_SIGNATURE, _LIVE_REFACET_LAST_APPLIED_SIGNATURE
    global _LIVE_REFACET_LAST_CHANGE_TIME
    scene = bpy.context.scene
    if scene is None or not getattr(scene, "prop_plasticity_live_refacet", False):
        _LIVE_REFACET_TIMER_RUNNING = False
        _LIVE_REFACET_LAST_SIGNATURE = None
        _LIVE_REFACET_LAST_APPLIED_SIGNATURE = None
        _LIVE_REFACET_LAST_CHANGE_TIME = 0.0
        return None

    context = bpy.context
    if context.mode != 'OBJECT':
        if getattr(scene, "prop_plasticity_live_refacet", False):
            scene.prop_plasticity_live_refacet = False
        _LIVE_REFACET_TIMER_RUNNING = False
        _LIVE_REFACET_LAST_SIGNATURE = None
        _LIVE_REFACET_LAST_APPLIED_SIGNATURE = None
        _LIVE_REFACET_LAST_CHANGE_TIME = 0.0
        return None

    interval = _get_live_refacet_interval(scene)
    signature = _build_refacet_signature(context)
    if signature is None:
        _LIVE_REFACET_LAST_SIGNATURE = None
        _LIVE_REFACET_LAST_APPLIED_SIGNATURE = None
        _LIVE_REFACET_LAST_CHANGE_TIME = 0.0
        return interval

    now = time.monotonic()
    if signature != _LIVE_REFACET_LAST_SIGNATURE:
        _LIVE_REFACET_LAST_SIGNATURE = signature
        _LIVE_REFACET_LAST_CHANGE_TIME = now
        return interval

    if _LIVE_REFACET_LAST_APPLIED_SIGNATURE == signature:
        return interval
    if getattr(context.window_manager, "plasticity_busy", False):
        return interval
    if not bpy.ops.wm.refacet.poll():
        return interval
    result = bpy.ops.wm.refacet()
    if isinstance(result, set) and 'FINISHED' in result:
        _LIVE_REFACET_LAST_APPLIED_SIGNATURE = signature
    return interval

_LIVE_EXPAND_TIMER_RUNNING = False
_LIVE_EXPAND_LAST_SETTINGS = {}
_LIVE_EXPAND_LAST_MERGE_SETTINGS = {}
_LIVE_EXPAND_BASE_SELECTION = {}
_LIVE_EXPAND_EXPANDED_SELECTION = {}
_LIVE_EXPAND_INTERVAL = 0.01
_LIVE_EXPAND_LAST_UNWRAP_TIME = 0.0
_LIVE_EXPAND_UNWRAP_INTERVAL = 0.2
_LIVE_EXPAND_SUPPRESS_AUTO_MERGE = False
_LIVE_EXPAND_SUSPENDED = False
_LIVE_EXPAND_PENDING_UNWRAP = False
_LIVE_EXPAND_LAST_SELECTION_TIME = 0.0
_LIVE_EXPAND_OVERLAY_HANDLE = None
_LIVE_EXPAND_OVERLAY_CACHE = None
_LIVE_EXPAND_ACTIVE_VIEW = None
_LIVE_UNWRAP_LAST_PROPS = None


def _get_live_expand_interval(scene):
    if scene is None:
        return _LIVE_EXPAND_INTERVAL
    value = getattr(scene, "prop_plasticity_live_expand_interval", _LIVE_EXPAND_INTERVAL)
    try:
        value = float(value)
    except Exception:
        value = _LIVE_EXPAND_INTERVAL
    if value < 0.01:
        value = 0.01
    return value


def ensure_live_expand_timer():
    global _LIVE_EXPAND_TIMER_RUNNING
    if _LIVE_EXPAND_TIMER_RUNNING:
        return
    _LIVE_EXPAND_TIMER_RUNNING = True
    interval = _get_live_expand_interval(bpy.context.scene)
    bpy.app.timers.register(_live_expand_timer, first_interval=interval)


def stop_live_expand_timer():
    global _LIVE_EXPAND_TIMER_RUNNING
    global _LIVE_EXPAND_LAST_SETTINGS, _LIVE_EXPAND_LAST_MERGE_SETTINGS
    global _LIVE_EXPAND_BASE_SELECTION, _LIVE_EXPAND_EXPANDED_SELECTION
    global _LIVE_EXPAND_SUSPENDED, _LIVE_EXPAND_PENDING_UNWRAP
    global _LIVE_EXPAND_LAST_SELECTION_TIME
    if _LIVE_EXPAND_TIMER_RUNNING:
        try:
            bpy.app.timers.unregister(_live_expand_timer)
        except Exception:
            pass
    _LIVE_EXPAND_TIMER_RUNNING = False
    _LIVE_EXPAND_LAST_SETTINGS = {}
    _LIVE_EXPAND_LAST_MERGE_SETTINGS = {}
    _LIVE_EXPAND_BASE_SELECTION = {}
    _LIVE_EXPAND_EXPANDED_SELECTION = {}
    _LIVE_EXPAND_SUSPENDED = False
    _LIVE_EXPAND_PENDING_UNWRAP = False
    _LIVE_EXPAND_LAST_SELECTION_TIME = 0.0


def _get_viewport_key(context):
    if context is None:
        return None
    area = context.area
    region = context.region
    window = context.window
    if not window or not area or area.type != 'VIEW_3D' or not region or region.type != 'WINDOW':
        return None
    try:
        window_key = window.as_pointer()
    except Exception:
        window_key = id(window)
    try:
        area_key = area.as_pointer()
    except Exception:
        area_key = id(area)
    try:
        region_key = region.as_pointer()
    except Exception:
        region_key = id(region)
    return (window_key, area_key, region_key)


def _get_viewport_key_from_parts(window, area, region):
    if not window or not area or not region:
        return None
    try:
        window_key = window.as_pointer()
    except Exception:
        window_key = id(window)
    try:
        area_key = area.as_pointer()
    except Exception:
        area_key = id(area)
    try:
        region_key = region.as_pointer()
    except Exception:
        region_key = id(region)
    return (window_key, area_key, region_key)


def set_live_expand_active_view(context):
    global _LIVE_EXPAND_ACTIVE_VIEW
    key = _get_viewport_key(context)
    if key is not None:
        _LIVE_EXPAND_ACTIVE_VIEW = key


def _is_live_expand_active_view(context, scene):
    if scene is None or not getattr(scene, "prop_plasticity_live_expand_active_view_only", False):
        return True
    key = _get_viewport_key(context)
    if key is None:
        return False
    global _LIVE_EXPAND_ACTIVE_VIEW
    if _LIVE_EXPAND_ACTIVE_VIEW is None:
        _LIVE_EXPAND_ACTIVE_VIEW = key
    return key == _LIVE_EXPAND_ACTIVE_VIEW


def _find_view3d_region(scene):
    context = bpy.context
    target_key = _LIVE_EXPAND_ACTIVE_VIEW
    require_match = bool(
        scene is not None and getattr(scene, "prop_plasticity_live_expand_active_view_only", False)
    )

    if (
        context.window
        and context.area
        and context.area.type == 'VIEW_3D'
        and context.region
        and context.region.type == 'WINDOW'
    ):
        key = _get_viewport_key(context)
        if not require_match or target_key is None or key == target_key:
            region_3d = context.area.spaces.active.region_3d
            if region_3d is not None:
                return (context.window, context.area, context.region, region_3d)

    window_manager = context.window_manager
    if not window_manager:
        return None
    if target_key is not None:
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
                key = _get_viewport_key_from_parts(window, area, region)
                if key != target_key:
                    continue
                region_3d = area.spaces.active.region_3d
                if region_3d is None:
                    continue
                return (window, area, region, region_3d)
        if require_match:
            return None
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
            region_3d = area.spaces.active.region_3d
            if region_3d is None:
                continue
            return (window, area, region, region_3d)
    return None


def _invalidate_live_expand_overlay_cache():
    global _LIVE_EXPAND_OVERLAY_CACHE
    _LIVE_EXPAND_OVERLAY_CACHE = None


def _touch_seams_version(mesh):
    if mesh is None:
        return
    try:
        mesh["plasticity_seams_version"] = int(mesh.get("plasticity_seams_version", 0)) + 1
    except Exception:
        pass


def ensure_live_expand_overlay():
    global _LIVE_EXPAND_OVERLAY_HANDLE
    if _LIVE_EXPAND_OVERLAY_HANDLE is not None:
        return
    _invalidate_live_expand_overlay_cache()
    _LIVE_EXPAND_OVERLAY_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
        _draw_live_expand_overlay,
        (),
        'WINDOW',
        'POST_PIXEL',
    )


def stop_live_expand_overlay():
    global _LIVE_EXPAND_OVERLAY_HANDLE, _LIVE_EXPAND_ACTIVE_VIEW
    if _LIVE_EXPAND_OVERLAY_HANDLE is None:
        return
    try:
        bpy.types.SpaceView3D.draw_handler_remove(_LIVE_EXPAND_OVERLAY_HANDLE, 'WINDOW')
    except Exception:
        pass
    _LIVE_EXPAND_OVERLAY_HANDLE = None
    _invalidate_live_expand_overlay_cache()
    _LIVE_EXPAND_ACTIVE_VIEW = None


def _draw_live_expand_overlay():
    global _LIVE_EXPAND_OVERLAY_CACHE
    scene = bpy.context.scene
    if scene is None:
        return
    if not getattr(scene, "prop_plasticity_live_expand_edge_highlight", False):
        return
    if bpy.context.mode != 'EDIT_MESH':
        return
    if not _is_live_expand_active_view(bpy.context, scene):
        return
    edit_objects = getattr(bpy.context, "objects_in_mode", None)
    if not edit_objects:
        edit_objects = [bpy.context.active_object] if bpy.context.active_object else []
    edit_objects = [
        obj for obj in edit_objects
        if obj and obj.type == 'MESH' and "plasticity_id" in obj.keys()
    ]
    if not edit_objects:
        return

    cache = _LIVE_EXPAND_OVERLAY_CACHE
    if cache is None:
        cache = {"objects": {}, "object_names": set()}

    current_names = {obj.name for obj in edit_objects}
    cache_objects = cache.get("objects", {})
    if cache.get("object_names") != current_names:
        for stale in set(cache_objects.keys()) - current_names:
            cache_objects.pop(stale, None)
        cache["object_names"] = current_names

    all_coords = []
    for obj in edit_objects:
        mesh = obj.data
        groups = mesh.get("groups")
        face_ids = mesh.get("face_ids")
        if not groups or not face_ids:
            cache_objects.pop(obj.name, None)
            continue

        mesh_key = _get_group_cache_key(mesh)
        seams_version = int(mesh.get("plasticity_seams_version", 0))
        entry = cache_objects.get(obj.name)
        if (
            entry is None
            or entry.get("mesh_key") != mesh_key
            or entry.get("seams_version") != seams_version
        ):
            bm = bmesh.from_edit_mesh(mesh)
            bm.edges.ensure_lookup_table()
            coords = []
            mat = obj.matrix_world
            for edge in bm.edges:
                if not edge.seam or not edge.is_valid:
                    continue
                v1, v2 = edge.verts
                coords.append(mat @ v1.co)
                coords.append(mat @ v2.co)
            entry = {
                "mesh_key": mesh_key,
                "seams_version": seams_version,
                "coords": coords,
            }
            cache_objects[obj.name] = entry
        all_coords.extend(entry.get("coords", []))

    cache["objects"] = cache_objects
    _LIVE_EXPAND_OVERLAY_CACHE = cache

    coords = all_coords
    if not coords:
        return

    thickness = float(getattr(scene, "prop_plasticity_live_expand_edge_thickness", 1.0))
    color = getattr(scene, "prop_plasticity_live_expand_overlay_color", (1.0, 0.15, 0.15, 1.0))
    occlude = bool(getattr(scene, "prop_plasticity_live_expand_edge_occlude", True))
    hidden_thickness = max(1.0, thickness * 0.5)
    hidden_color = (color[0], color[1], color[2], color[3] * 0.35)
    gpu.state.blend_set('ALPHA')
    try:
        region = bpy.context.region
        region_3d = getattr(bpy.context, "region_data", None)
        if region_3d is None and bpy.context.area and bpy.context.area.type == 'VIEW_3D':
            region_3d = bpy.context.area.spaces.active.region_3d
        if region_3d is None:
            return
        shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINES', {"pos": coords})
        gpu.matrix.push()
        gpu.matrix.load_projection_matrix(region_3d.perspective_matrix)
        gpu.matrix.load_matrix(mathutils.Matrix.Identity(4))

        def draw_pass(depth_mode, pass_color, pass_thickness):
            gpu.state.depth_test_set(depth_mode)
            shader.bind()
            shader.uniform_float("color", pass_color)
            if region:
                shader.uniform_float("viewportSize", (region.width, region.height))
            shader.uniform_float("lineWidth", pass_thickness)
            batch.draw(shader)

        if occlude:
            draw_pass('LESS_EQUAL', color, thickness)
        else:
            draw_pass('LESS_EQUAL', color, thickness)
            draw_pass('GREATER', hidden_color, hidden_thickness)

        gpu.matrix.pop()
    except Exception:
        shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINES', {"pos": coords})
        region_3d = getattr(bpy.context, "region_data", None)
        if region_3d is None and bpy.context.area and bpy.context.area.type == 'VIEW_3D':
            region_3d = bpy.context.area.spaces.active.region_3d
        if region_3d is None:
            return
        gpu.matrix.push()
        gpu.matrix.load_projection_matrix(region_3d.perspective_matrix)
        gpu.matrix.load_matrix(mathutils.Matrix.Identity(4))

        def draw_pass(depth_mode, pass_color, pass_thickness):
            gpu.state.depth_test_set(depth_mode)
            gpu.state.line_width_set(pass_thickness)
            shader.bind()
            shader.uniform_float("color", pass_color)
            batch.draw(shader)
            gpu.state.line_width_set(1.0)

        if occlude:
            draw_pass('LESS_EQUAL', color, thickness)
        else:
            draw_pass('LESS_EQUAL', color, thickness)
            draw_pass('GREATER', hidden_color, hidden_thickness)

        gpu.matrix.pop()
    finally:
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')


def _auto_merge_seams_on_selection(bm, selected_faces, respect_existing_seams):
    if not selected_faces:
        return [], []
    bm.edges.ensure_lookup_table()

    existing_seams = set()
    if respect_existing_seams:
        existing_seams = {edge.index for edge in bm.edges if edge.seam}

    changed_to_true = []
    changed_to_false = []
    for edge in bm.edges:
        faces = edge.link_faces
        if not faces:
            continue
        if respect_existing_seams and edge.index in existing_seams:
            continue

        selected_count = 0
        for face in faces:
            if face.select:
                selected_count += 1

        if selected_count == 0:
            continue
        if selected_count == len(faces):
            new_seam = (len(faces) == 1)
        else:
            new_seam = True
        if edge.seam != new_seam:
            edge.seam = new_seam
            if new_seam:
                changed_to_true.append(edge.index)
            else:
                changed_to_false.append(edge.index)
    return changed_to_true, changed_to_false


def _jacobi_eigen_3x3(matrix, max_iter=32):
    values = [
        [float(matrix[0][0]), float(matrix[0][1]), float(matrix[0][2])],
        [float(matrix[1][0]), float(matrix[1][1]), float(matrix[1][2])],
        [float(matrix[2][0]), float(matrix[2][1]), float(matrix[2][2])],
    ]
    vectors = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]

    for _ in range(max_iter):
        p = 0
        q = 1
        max_val = abs(values[0][1])
        if abs(values[0][2]) > max_val:
            p, q = 0, 2
            max_val = abs(values[0][2])
        if abs(values[1][2]) > max_val:
            p, q = 1, 2
            max_val = abs(values[1][2])
        if max_val < 1e-10:
            break

        if values[p][p] == values[q][q]:
            theta = math.pi / 4.0
        else:
            tau = (values[q][q] - values[p][p]) / (2.0 * values[p][q])
            t = math.copysign(1.0, tau) / (abs(tau) + math.sqrt(1.0 + tau * tau))
            theta = math.atan(t)
        c = math.cos(theta)
        s = math.sin(theta)

        for i in range(3):
            if i == p or i == q:
                continue
            vip = values[i][p]
            viq = values[i][q]
            values[i][p] = values[p][i] = c * vip - s * viq
            values[i][q] = values[q][i] = c * viq + s * vip

        vpp = values[p][p]
        vqq = values[q][q]
        vpq = values[p][q]
        values[p][p] = c * c * vpp - 2.0 * s * c * vpq + s * s * vqq
        values[q][q] = s * s * vpp + 2.0 * s * c * vpq + c * c * vqq
        values[p][q] = values[q][p] = 0.0

        for i in range(3):
            vip = vectors[i][p]
            viq = vectors[i][q]
            vectors[i][p] = c * vip - s * viq
            vectors[i][q] = c * viq + s * vip

    eigenvalues = [values[i][i] for i in range(3)]
    eigenvectors = [
        mathutils.Vector((vectors[0][i], vectors[1][i], vectors[2][i]))
        for i in range(3)
    ]
    return eigenvalues, eigenvectors


def _estimate_axis_from_faces(bm, selected_set):
    if not selected_set:
        return None, None
    centers = []
    normals = []
    for face_index in selected_set:
        if face_index >= len(bm.faces):
            continue
        face = bm.faces[face_index]
        centers.append(face.calc_center_median())
        n = face.normal
        if n.length > 1e-8:
            normals.append(n.normalized())
    if not centers:
        return None, None
    mean = mathutils.Vector((0.0, 0.0, 0.0))
    for center in centers:
        mean += center
    mean /= len(centers)

    cov = [[0.0, 0.0, 0.0] for _ in range(3)]
    for center in centers:
        offset = center - mean
        cov[0][0] += offset.x * offset.x
        cov[0][1] += offset.x * offset.y
        cov[0][2] += offset.x * offset.z
        cov[1][1] += offset.y * offset.y
        cov[1][2] += offset.y * offset.z
        cov[2][2] += offset.z * offset.z
    cov[1][0] = cov[0][1]
    cov[2][0] = cov[0][2]
    cov[2][1] = cov[1][2]

    eigenvalues, eigenvectors = _jacobi_eigen_3x3(cov)
    if not eigenvectors:
        return None, mean
    best_axis = None
    best_score = None
    if normals:
        for axis in eigenvectors:
            if axis.length < 1e-6:
                continue
            axis = axis.normalized()
            total = 0.0
            for n in normals:
                total += abs(n.dot(axis))
            score = total / max(1, len(normals))
            if best_score is None or score < best_score:
                best_score = score
                best_axis = axis
    if best_axis is None:
        max_index = 0
        for idx in range(1, 3):
            if eigenvalues[idx] > eigenvalues[max_index]:
                max_index = idx
        best_axis = eigenvectors[max_index]
        if best_axis.length < 1e-6:
            return None, mean
        best_axis = best_axis.normalized()
    return best_axis, mean


def _candidate_axes_from_faces(bm, selected_set):
    if not selected_set:
        return [], None
    centers = []
    normals = []
    for face_index in selected_set:
        if face_index >= len(bm.faces):
            continue
        face = bm.faces[face_index]
        centers.append(face.calc_center_median())
        n = face.normal
        if n.length > 1e-8:
            normals.append(n.normalized())
    if not centers:
        return [], None
    mean = mathutils.Vector((0.0, 0.0, 0.0))
    for center in centers:
        mean += center
    mean /= len(centers)

    cov = [[0.0, 0.0, 0.0] for _ in range(3)]
    for center in centers:
        offset = center - mean
        cov[0][0] += offset.x * offset.x
        cov[0][1] += offset.x * offset.y
        cov[0][2] += offset.x * offset.z
        cov[1][1] += offset.y * offset.y
        cov[1][2] += offset.y * offset.z
        cov[2][2] += offset.z * offset.z
    cov[1][0] = cov[0][1]
    cov[2][0] = cov[0][2]
    cov[2][1] = cov[1][2]

    eigenvalues, eigenvectors = _jacobi_eigen_3x3(cov)
    if not eigenvectors:
        return [], mean

    candidates = []
    for axis in eigenvectors:
        if axis.length > 1e-6:
            candidates.append(axis.normalized())
    if normals:
        best_axis = None
        best_score = None
        for axis in candidates:
            total = 0.0
            for n in normals:
                total += abs(n.dot(axis))
            score = total / max(1, len(normals))
            if best_score is None or score < best_score:
                best_score = score
                best_axis = axis
        if best_axis is not None:
            candidates.insert(0, best_axis)

    if eigenvalues:
        max_idx = 0
        min_idx = 0
        for idx in range(1, 3):
            if eigenvalues[idx] > eigenvalues[max_idx]:
                max_idx = idx
            if eigenvalues[idx] < eigenvalues[min_idx]:
                min_idx = idx
        for idx in (max_idx, min_idx):
            axis = eigenvectors[idx]
            if axis.length > 1e-6:
                axis = axis.normalized()
                if axis not in candidates:
                    candidates.append(axis)

    unique = []
    for axis in candidates:
        if not any(abs(axis.dot(other)) > 0.999 for other in unique):
            unique.append(axis)
    return unique, mean


def _angle_delta(first, second):
    diff = first - second
    diff = (diff + math.pi) % (2.0 * math.pi) - math.pi
    return abs(diff)


def _dijkstra_seam(
    internal_graph,
    start_set,
    end_set,
    edges_by_index=None,
    edge_angles=None,
    turn_weight=0.0,
    meridian_weight=0.0,
):
    import heapq
    dist = {}
    prev = {}
    heap = []
    for vert_index in start_set:
        state = (vert_index, -1)
        dist[state] = 0.0
        heapq.heappush(heap, (0.0, state))

    found = None
    while heap:
        current_dist, state = heapq.heappop(heap)
        if current_dist != dist.get(state):
            continue
        vert_index, prev_edge_index = state
        if vert_index in end_set:
            found = state
            break
        prev_dir = None
        prev_angle = None
        if prev_edge_index != -1 and edges_by_index is not None:
            prev_edge = edges_by_index.get(prev_edge_index)
            if prev_edge and prev_edge.is_valid:
                v1, v2 = prev_edge.verts
                if v1.index == vert_index:
                    prev_vec = v1.co - v2.co
                else:
                    prev_vec = v2.co - v1.co
                if prev_vec.length > 1e-6:
                    prev_dir = prev_vec.normalized()
            if edge_angles is not None:
                prev_angle = edge_angles.get(prev_edge_index)

        for next_index, base_cost, edge, direction in internal_graph.get(vert_index, []):
            cost = base_cost
            if prev_dir is not None:
                dot = prev_dir.dot(direction)
                if dot > 1.0:
                    dot = 1.0
                elif dot < -1.0:
                    dot = -1.0
                cost += turn_weight * (1.0 - dot) * base_cost
            if meridian_weight and edge_angles is not None and prev_angle is not None:
                next_angle = edge_angles.get(edge.index)
                if next_angle is not None:
                    delta = _angle_delta(next_angle, prev_angle)
                    cost += meridian_weight * (delta / math.pi) * base_cost
            next_state = (next_index, edge.index)
            new_dist = current_dist + cost
            if new_dist < dist.get(next_state, float("inf")):
                dist[next_state] = new_dist
                prev[next_state] = (state, edge)
                heapq.heappush(heap, (new_dist, next_state))

    if found is None:
        return [], None
    seam_edges = []
    current = found
    while current in prev:
        prev_state, edge = prev[current]
        seam_edges.append(edge)
        current = prev_state
    return seam_edges, dist.get(found, 0.0)


def _occluded_edge_indices_for_view(
    obj,
    edges,
    scene,
    view_context,
    selection_center_world,
    center_radius=0.3,
):
    if obj is None or scene is None or view_context is None:
        return set()
    if selection_center_world is None:
        return set()
    window, area, region, region_3d = view_context
    if region is None or region_3d is None:
        return set()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mat = obj.matrix_world
    occluded = set()
    epsilon = 1e-4
    selection_center_screen = view3d_utils.location_3d_to_region_2d(
        region,
        region_3d,
        selection_center_world,
    )
    region_center = mathutils.Vector((region.width * 0.5, region.height * 0.5))
    if selection_center_screen is None:
        selection_center_screen = region_center
    view_origin = view3d_utils.region_2d_to_origin_3d(
        region,
        region_3d,
        selection_center_screen,
    )
    view_dir = view3d_utils.region_2d_to_vector_3d(
        region,
        region_3d,
        selection_center_screen,
    )
    if view_dir.length <= 1e-8:
        return set()
    view_dir.normalize()
    t_center = (selection_center_world - view_origin).dot(view_dir)
    max_radius = min(region.width, region.height) * float(center_radius)
    for edge in edges:
        if not edge.is_valid:
            continue
        midpoint = (edge.verts[0].co + edge.verts[1].co) * 0.5
        world_midpoint = mat @ midpoint
        coord = view3d_utils.location_3d_to_region_2d(region, region_3d, world_midpoint)
        if coord is None:
            continue
        if (coord - selection_center_screen).length > max_radius:
            continue
        t_edge = (world_midpoint - view_origin).dot(view_dir)
        if t_edge <= t_center + epsilon:
            continue
        origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, coord)
        if direction.length <= 1e-8:
            continue
        distance = (world_midpoint - origin).length
        if distance <= epsilon:
            continue
        hit, _, _, _, _, _ = scene.ray_cast(
            depsgraph,
            origin,
            direction,
            distance=distance - epsilon,
        )
        if hit:
            occluded.add(edge.index)
    return occluded


def _auto_cylinder_seam_on_selection(
    bm,
    selected_faces,
    mode='FULL',
    partial_angle=200.0,
    occluded_only=False,
    obj=None,
    scene=None,
    view_context=None,
):
    if not selected_faces:
        return []
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()

    selected_set = {idx for idx in selected_faces if idx < len(bm.faces)}
    if len(selected_set) < 2:
        return []

    candidate_axes, _ = _candidate_axes_from_faces(bm, selected_set)
    edges_by_index = {edge.index: edge for edge in bm.edges}

    if occluded_only:
        if scene is None:
            scene = bpy.context.scene
        if view_context is None:
            view_context = _find_view3d_region(scene)
        if scene is None or view_context is None or obj is None:
            return []

    boundary_edges = []
    for edge in bm.edges:
        if not edge.is_valid:
            continue
        selected_count = 0
        for face in edge.link_faces:
            if face.index in selected_set:
                selected_count += 1
        if selected_count == 1:
            boundary_edges.append(edge)

    internal_edges = []
    for edge in bm.edges:
        if not edge.is_valid:
            continue
        if len(edge.link_faces) != 2:
            continue
        if not all(face.index in selected_set for face in edge.link_faces):
            continue
        internal_edges.append(edge)
    if not internal_edges:
        return []

    occluded_edges = None
    if occluded_only:
        selection_center = mathutils.Vector((0.0, 0.0, 0.0))
        for face_index in selected_set:
            selection_center += bm.faces[face_index].calc_center_median()
        selection_center /= len(selected_set)
        selection_center_world = obj.matrix_world @ selection_center
        occluded_edges = _occluded_edge_indices_for_view(
            obj,
            internal_edges,
            scene,
            view_context,
            selection_center_world,
        )
        if not occluded_edges:
            return []

    def _build_boundary_components(edges):
        if not edges:
            return []
        vertex_to_edges = {}
        for edge in edges:
            for vert in edge.verts:
                vertex_to_edges.setdefault(vert.index, []).append(edge)

        visited_edges = set()
        components = []
        for edge in edges:
            if edge.index in visited_edges:
                continue
            stack = [edge]
            comp_edges = []
            comp_verts = set()
            visited_edges.add(edge.index)
            while stack:
                current = stack.pop()
                comp_edges.append(current)
                for vert in current.verts:
                    comp_verts.add(vert.index)
                    for next_edge in vertex_to_edges.get(vert.index, []):
                        if next_edge.index in visited_edges:
                            continue
                        visited_edges.add(next_edge.index)
                        stack.append(next_edge)
            components.append((comp_edges, comp_verts))
        return components

    selection_boundary_components = _build_boundary_components(boundary_edges)

    def _component_center_from_verts(vert_indices):
        if not vert_indices:
            return None
        center = mathutils.Vector((0.0, 0.0, 0.0))
        count = 0
        for vert_index in vert_indices:
            if vert_index >= len(bm.verts):
                continue
            center += bm.verts[vert_index].co
            count += 1
        if count == 0:
            return None
        return center / count

    def _legacy_axis_from_boundary_components(components):
        if len(components) != 2:
            return None
        center_a = _component_center_from_verts(components[0][1])
        center_b = _component_center_from_verts(components[1][1])
        if center_a is None or center_b is None:
            return None
        axis = center_b - center_a
        if axis.length < 1e-6:
            return None
        axis.normalize()

        total_dot = 0.0
        face_count = 0
        for face_index in selected_set:
            face = bm.faces[face_index]
            total_dot += abs(face.normal.dot(axis))
            face_count += 1
        if face_count == 0:
            return None
        if total_dot / face_count > 0.35:
            return None

        for comp_edges, _ in components:
            if not comp_edges:
                return None
            edge_dot = 0.0
            for edge in comp_edges:
                v1, v2 = edge.verts
                direction = v2.co - v1.co
                if direction.length <= 1e-6:
                    continue
                direction.normalize()
                edge_dot += abs(direction.dot(axis))
            if edge_dot / max(1, len(comp_edges)) > 0.35:
                return None
        return axis

    legacy_axis = _legacy_axis_from_boundary_components(selection_boundary_components)
    if legacy_axis is not None:
        if not any(abs(legacy_axis.dot(other)) > 0.999 for other in candidate_axes):
            candidate_axes.insert(0, legacy_axis)

    if not candidate_axes:
        return []

    def _component_edge_alignment(comp_edges, axis):
        if not comp_edges:
            return 1.0
        edge_dot = 0.0
        for edge in comp_edges:
            v1, v2 = edge.verts
            direction = v2.co - v1.co
            if direction.length <= 1e-6:
                continue
            direction.normalize()
            edge_dot += abs(direction.dot(axis))
        return edge_dot / max(1, len(comp_edges))

    def _wrap_angle_for_faces(face_indices, axis, center_mean, x_axis, y_axis):
        if not face_indices:
            return None
        angles = []
        for face_index in face_indices:
            face = bm.faces[face_index]
            face_center = face.calc_center_median()
            radial = face_center - center_mean
            radial -= axis * radial.dot(axis)
            if radial.length <= 1e-6:
                continue
            radial.normalize()
            angle = math.atan2(radial.dot(y_axis), radial.dot(x_axis))
            angles.append(angle)
        if not angles:
            return None
        angles.sort()
        angles = angles + [angles[0] + math.tau]
        max_gap = 0.0
        for idx in range(len(angles) - 1):
            gap = angles[idx + 1] - angles[idx]
            if gap > max_gap:
                max_gap = gap
        return math.tau - max_gap

    try:
        partial_threshold = math.radians(float(partial_angle))
    except Exception:
        partial_threshold = math.radians(200.0)
    full_threshold = max(math.radians(320.0), partial_threshold)
    axis_weight = 0.9
    cap_weight = 0.6
    turn_weight = 0.4
    meridian_weight = 0.9

    best_seam = []
    best_score = None

    for axis in candidate_axes:
        cap_dot = 0.9
        side_set = set()
        for face_index in selected_set:
            face = bm.faces[face_index]
            if abs(face.normal.dot(axis)) < cap_dot:
                side_set.add(face_index)

        if len(side_set) < 2:
            continue

        basis = mathutils.Vector((1.0, 0.0, 0.0))
        if abs(axis.dot(basis)) > 0.9:
            basis = mathutils.Vector((0.0, 1.0, 0.0))
        x_axis = axis.cross(basis).normalized()
        y_axis = axis.cross(x_axis).normalized()
        center_mean = mathutils.Vector((0.0, 0.0, 0.0))
        for face_index in selected_set:
            center_mean += bm.faces[face_index].calc_center_median()
        center_mean /= len(selected_set)

        boundary_components = selection_boundary_components
        if not boundary_edges:
            # Fallback to cap boundaries when selection covers the whole closed mesh.
            cap_boundary_edges = []
            for edge in internal_edges:
                face_a, face_b = edge.link_faces
                in_a = face_a.index in side_set
                in_b = face_b.index in side_set
                if in_a != in_b:
                    cap_boundary_edges.append(edge)
            boundary_components = _build_boundary_components(cap_boundary_edges)
        if len(boundary_components) < 2:
            continue

        wrap_angle = _wrap_angle_for_faces(selected_set, axis, center_mean, x_axis, y_axis)
        if wrap_angle is None:
            continue
        if mode == 'FULL':
            if len(boundary_components) != 2 and wrap_angle < full_threshold:
                continue
        else:
            if wrap_angle < partial_threshold:
                continue

        internal_graph = {}
        edge_angles = {}
        for edge in internal_edges:
            if not edge.is_valid:
                continue
            if occluded_edges is not None and edge.index not in occluded_edges:
                continue
            v1, v2 = edge.verts
            direction = v2.co - v1.co
            if direction.length <= 1e-6:
                continue
            direction.normalize()
            axis_alignment = abs(direction.dot(axis))
            axis_misalignment = 1.0 - axis_alignment
            edge_length = edge.calc_length()
            base_cost = edge_length * (1.0 + axis_weight * axis_misalignment)
            side_faces = 0
            align_sum = 0.0
            for face in edge.link_faces:
                align_sum += abs(face.normal.dot(axis))
                if face.index in side_set:
                    side_faces += 1
            align_avg = align_sum / len(edge.link_faces)
            if side_faces == len(edge.link_faces):
                penalty = 0.0
            else:
                penalty = cap_weight * (0.25 + 0.5 * align_avg)
            cost = base_cost + edge_length * penalty
            if edge.index not in edge_angles:
                midpoint = (v1.co + v2.co) * 0.5
                radial = midpoint - center_mean
                radial -= axis * radial.dot(axis)
                if radial.length > 1e-6:
                    radial.normalize()
                    edge_angles[edge.index] = math.atan2(
                        radial.dot(y_axis),
                        radial.dot(x_axis),
                    )
                else:
                    edge_angles[edge.index] = None
            internal_graph.setdefault(v1.index, []).append(
                (v2.index, cost, edge, direction)
            )
            internal_graph.setdefault(v2.index, []).append(
                (v1.index, cost, edge, -direction)
            )

        if not internal_graph:
            continue

        graph_vertices = set(internal_graph.keys())
        component_info = []
        max_length = 0.0
        for comp_edges, comp_verts in boundary_components:
            if not comp_edges or not comp_verts:
                continue
            comp_length = 0.0
            for edge in comp_edges:
                if edge.is_valid:
                    comp_length += edge.calc_length()
            center = mathutils.Vector((0.0, 0.0, 0.0))
            for vert_index in comp_verts:
                center += bm.verts[vert_index].co
            center /= len(comp_verts)
            alignment = _component_edge_alignment(comp_edges, axis)
            projection = center.dot(axis)
            side_verts = set()
            for vert_index in comp_verts:
                vert = bm.verts[vert_index]
                for face in vert.link_faces:
                    if face.index in side_set:
                        side_verts.add(vert_index)
                        break
            if not side_verts:
                continue
            component_info.append({
                "projection": projection,
                "alignment": alignment,
                "length": comp_length,
                "verts": side_verts,
            })
            if comp_length > max_length:
                max_length = comp_length

        if len(component_info) < 2:
            continue

        if max_length > 0.0 and len(component_info) > 2:
            length_threshold = max_length * 0.25
            component_info = [
                comp for comp in component_info if comp["length"] >= length_threshold
            ]
            if len(component_info) < 2:
                continue

        if mode == 'FULL':
            cap_components = [
                comp for comp in component_info if comp["alignment"] <= 0.45
            ]
            if len(cap_components) >= 2:
                component_info = cap_components

        component_info.sort(key=lambda comp: comp["projection"])
        start_set = {v for v in component_info[0]["verts"] if v in graph_vertices}
        end_set = {v for v in component_info[-1]["verts"] if v in graph_vertices}

        if not start_set or not end_set:
            continue

        seam_edges, seam_cost = _dijkstra_seam(
            internal_graph,
            start_set,
            end_set,
            edges_by_index=edges_by_index,
            edge_angles=edge_angles,
            turn_weight=turn_weight,
            meridian_weight=meridian_weight,
        )
        if not seam_edges:
            continue
        if seam_cost is None:
            continue
        if best_score is None or seam_cost < best_score:
            best_score = seam_cost
            best_seam = seam_edges

    if not best_seam:
        return []

    changed = []
    for edge in best_seam:
        if edge.is_valid and not edge.seam:
            edge.seam = True
            changed.append(edge.index)
    return changed


def _is_modal_selection_running():
    window_manager = bpy.context.window_manager
    if not window_manager:
        return False
    modal_ids = {
        "VIEW3D_OT_select_circle",
        "VIEW3D_OT_select_box",
        "VIEW3D_OT_select_lasso",
        "VIEW3D_OT_select",
    }
    for op in window_manager.operators:
        if getattr(op, "bl_idname", "") in modal_ids:
            return True
    return False


def _queue_live_unwrap():
    global _LIVE_EXPAND_PENDING_UNWRAP, _LIVE_EXPAND_LAST_SELECTION_TIME
    _LIVE_EXPAND_PENDING_UNWRAP = True
    _LIVE_EXPAND_LAST_SELECTION_TIME = time.monotonic()


def _flush_pending_unwrap(context):
    global _LIVE_EXPAND_PENDING_UNWRAP
    if not _LIVE_EXPAND_PENDING_UNWRAP:
        return False
    if time.monotonic() - _LIVE_EXPAND_LAST_SELECTION_TIME < _LIVE_EXPAND_UNWRAP_INTERVAL:
        return False
    if _maybe_live_unwrap(context, force=True):
        _LIVE_EXPAND_PENDING_UNWRAP = False
        return True
    return False


def _maybe_live_unwrap(context, force=False):
    global _LIVE_EXPAND_LAST_UNWRAP_TIME, _LIVE_EXPAND_PENDING_UNWRAP
    scene = context.scene if context else None
    tool_settings = scene.tool_settings if scene else None
    if not tool_settings:
        return False
    uv_live = _is_uv_editor_live_unwrap_enabled(context)
    edge_live = bool(getattr(tool_settings, "use_edge_path_live_unwrap", False))
    if not uv_live and not edge_live:
        return False
    if not context or context.mode != 'EDIT_MESH':
        return False
    if edge_live:
        _LIVE_EXPAND_PENDING_UNWRAP = False
        _LIVE_EXPAND_LAST_UNWRAP_TIME = time.monotonic()
        return True
    if _is_modal_selection_running() and not force:
        _LIVE_EXPAND_PENDING_UNWRAP = True
        return False
    now = time.monotonic()
    if not force and now - _LIVE_EXPAND_LAST_UNWRAP_TIME < _LIVE_EXPAND_UNWRAP_INTERVAL:
        return False
    _LIVE_EXPAND_LAST_UNWRAP_TIME = now

    window_manager = bpy.context.window_manager
    candidates = []
    if window_manager:
        for area_type in ("IMAGE_EDITOR", "VIEW_3D"):
            for window in window_manager.windows:
                screen = window.screen
                if screen is None:
                    continue
                for area in screen.areas:
                    if area.type != area_type:
                        continue
                    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                    if region is None:
                        continue
                    candidates.append((window, screen, area, region))
                if candidates and area_type == "IMAGE_EDITOR":
                    break
            if candidates and area_type == "IMAGE_EDITOR":
                break

    def build_override(window, screen, area, region):
        space = area.spaces.active
        override_ctx = {
            "window": window,
            "screen": screen,
            "area": area,
            "region": region,
            "space_data": space,
            "scene": scene,
            "view_layer": context.view_layer,
            "active_object": context.active_object,
            "object": context.object,
            "edit_object": context.edit_object,
        }
        region_data = getattr(space, "region_3d", None)
        if region_data is not None:
            override_ctx["region_data"] = region_data
        return override_ctx

    unwrap_kwargs = _unwrap_kwargs_from_tool_settings(tool_settings)
    if not unwrap_kwargs:
        unwrap_kwargs = _unwrap_kwargs_from_last_props(context)

    def run_unwrap_with_override(override_ctx):
        with bpy.context.temp_override(**override_ctx):
            return bpy.ops.uv.unwrap(**unwrap_kwargs)

    def unwrap_cancelled(result):
        return isinstance(result, set) and 'CANCELLED' in result

    prev_uv_sync = tool_settings.use_uv_select_sync
    try:
        tool_settings.use_uv_select_sync = True
        result = None
        if candidates:
            for window, screen, area, region in candidates:
                override_ctx = build_override(window, screen, area, region)
                result = run_unwrap_with_override(override_ctx)
                if not unwrap_cancelled(result):
                    break
                if area.type != "IMAGE_EDITOR":
                    original_type = area.type
                    area.type = "IMAGE_EDITOR"
                    temp_space = area.spaces.active
                    prev_ui_mode, prev_mode = _set_space_uv_mode(temp_space)
                    try:
                        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                        if region is None:
                            continue
                        override_ctx = build_override(window, screen, area, region)
                        result = run_unwrap_with_override(override_ctx)
                        if not unwrap_cancelled(result):
                            break
                    finally:
                        _restore_space_mode(temp_space, prev_ui_mode, prev_mode)
                        area.type = original_type
        else:
            result = bpy.ops.uv.unwrap(**unwrap_kwargs)

        if unwrap_cancelled(result):
            _LIVE_EXPAND_PENDING_UNWRAP = True
            return False
        if window_manager:
            for window in window_manager.windows:
                screen = window.screen
                if screen is None:
                    continue
                for area in screen.areas:
                    if area.type in {"VIEW_3D", "IMAGE_EDITOR"}:
                        area.tag_redraw()
            try:
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
            except Exception:
                pass
        return True
    except Exception:
        return False
    finally:
        tool_settings.use_uv_select_sync = prev_uv_sync


def _op_cancelled(result):
    return isinstance(result, set) and 'CANCELLED' in result


def _run_mesh_mark_seam(context, clear=False):
    window_manager = bpy.context.window_manager
    if window_manager:
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
                override_ctx = {
                    "window": window,
                    "screen": screen,
                    "area": area,
                    "region": region,
                    "scene": context.scene,
                    "view_layer": context.view_layer,
                    "active_object": context.active_object,
                    "object": context.object,
                    "edit_object": context.edit_object,
                }
                region_data = getattr(area.spaces.active, "region_3d", None)
                if region_data is not None:
                    override_ctx["region_data"] = region_data
                with bpy.context.temp_override(**override_ctx):
                    result = bpy.ops.mesh.mark_seam(clear=clear)
                if not _op_cancelled(result):
                    return True
    result = bpy.ops.mesh.mark_seam(clear=clear)
    return not _op_cancelled(result)


def _touch_live_unwrap_after_seam_change(context, seam_true_indices, seam_false_indices):
    if not seam_true_indices and not seam_false_indices:
        return False
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return False
    mesh = obj.data
    bm = bmesh.from_edit_mesh(mesh)
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    scene = getattr(context, "scene", None)
    tool_settings = scene.tool_settings if scene else None
    edge_live = bool(getattr(tool_settings, "use_edge_path_live_unwrap", False)) if tool_settings else False
    live_enabled = edge_live or _is_uv_editor_live_unwrap_enabled(context)

    changed_edges = set(seam_true_indices) | set(seam_false_indices)
    changed_faces = set()
    for edge_index in changed_edges:
        if edge_index >= len(bm.edges):
            continue
        edge = bm.edges[edge_index]
        if not edge.is_valid:
            continue
        for face in edge.link_faces:
            if face.is_valid:
                changed_faces.add(face.index)

    prev_face_selected = None
    pinned = None
    if live_enabled and changed_faces:
        prev_face_selected = {face.index for face in bm.faces if face.select}
        for face in bm.faces:
            face.select = face.index in changed_faces
        if edge_live:
            uv_layer = bm.loops.layers.uv.active
            if uv_layer is None:
                uv_layer = bm.loops.layers.uv.verify()
            relax_layer = bm.faces.layers.int.get("plasticity_relaxed")
            if relax_layer is not None:
                relaxed_faces = {
                    face.index for face in bm.faces if face[relax_layer]
                }
                faces_to_pin = relaxed_faces - changed_faces
                pinned = _pin_uv_faces(bm, uv_layer, faces_to_pin)
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        bm = bmesh.from_edit_mesh(mesh)
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

    prev_selected = {edge.index for edge in bm.edges if edge.select}
    ran = False
    if seam_false_indices:
        changed_set = set(seam_false_indices)
        for edge in bm.edges:
            edge.select = edge.index in changed_set
        bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=False)
        result = _run_mesh_mark_seam(context, clear=True)
        ran = ran or result
    if seam_true_indices:
        bm = bmesh.from_edit_mesh(mesh)
        bm.edges.ensure_lookup_table()
        changed_set = set(seam_true_indices)
        for edge in bm.edges:
            edge.select = edge.index in changed_set
        bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=False)
        result = _run_mesh_mark_seam(context, clear=False)
        ran = ran or result

    bm = bmesh.from_edit_mesh(mesh)
    bm.edges.ensure_lookup_table()
    if pinned:
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None:
            uv_layer = bm.loops.layers.uv.verify()
        _restore_pinned_uvs(bm, uv_layer, pinned)
    if prev_face_selected is not None:
        bm.faces.ensure_lookup_table()
    for edge in bm.edges:
        edge.select = edge.index in prev_selected
    if prev_face_selected is not None:
        for face in bm.faces:
            face.select = face.index in prev_face_selected
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    return bool(edge_live and ran)


def _live_expand_timer():
    global _LIVE_EXPAND_TIMER_RUNNING
    global _LIVE_EXPAND_LAST_SETTINGS, _LIVE_EXPAND_LAST_MERGE_SETTINGS
    global _LIVE_EXPAND_BASE_SELECTION, _LIVE_EXPAND_EXPANDED_SELECTION
    global _LIVE_EXPAND_SUPPRESS_AUTO_MERGE, _LIVE_EXPAND_SUSPENDED
    global _LIVE_EXPAND_PENDING_UNWRAP
    global _LIVE_EXPAND_LAST_SELECTION_TIME

    scene = bpy.context.scene
    if scene is None or not getattr(scene, "prop_plasticity_live_expand", False):
        _LIVE_EXPAND_TIMER_RUNNING = False
        _LIVE_EXPAND_LAST_SETTINGS = {}
        _LIVE_EXPAND_LAST_MERGE_SETTINGS = {}
        _LIVE_EXPAND_BASE_SELECTION = {}
        _LIVE_EXPAND_EXPANDED_SELECTION = {}
        _LIVE_EXPAND_SUSPENDED = False
        _LIVE_EXPAND_PENDING_UNWRAP = False
        _LIVE_EXPAND_LAST_SELECTION_TIME = 0.0
        return None

    interval = _get_live_expand_interval(scene)
    if _LIVE_EXPAND_SUSPENDED:
        _LIVE_EXPAND_PENDING_UNWRAP = False
        _LIVE_EXPAND_LAST_SELECTION_TIME = 0.0
        return interval

    context = bpy.context
    if getattr(scene, "prop_plasticity_live_expand_active_view_only", False):
        set_live_expand_active_view(context)
    if context.mode != 'EDIT_MESH':
        _LIVE_EXPAND_BASE_SELECTION = {}
        _LIVE_EXPAND_EXPANDED_SELECTION = {}
        _LIVE_EXPAND_LAST_MERGE_SETTINGS = {}
        _LIVE_EXPAND_LAST_SETTINGS = {}
        _LIVE_EXPAND_PENDING_UNWRAP = False
        _LIVE_EXPAND_LAST_SELECTION_TIME = 0.0
        return interval

    edit_objects = getattr(context, "objects_in_mode", None)
    if not edit_objects:
        edit_objects = [context.active_object] if context.active_object else []
    edit_objects = [
        obj for obj in edit_objects
        if obj and obj.type == 'MESH' and "plasticity_id" in obj.keys()
    ]
    if not edit_objects:
        _LIVE_EXPAND_BASE_SELECTION = {}
        _LIVE_EXPAND_EXPANDED_SELECTION = {}
        _LIVE_EXPAND_LAST_MERGE_SETTINGS = {}
        _LIVE_EXPAND_LAST_SETTINGS = {}
        _LIVE_EXPAND_PENDING_UNWRAP = False
        _LIVE_EXPAND_LAST_SELECTION_TIME = 0.0
        return interval

    current_names = {obj.name for obj in edit_objects}
    for state in (
        _LIVE_EXPAND_BASE_SELECTION,
        _LIVE_EXPAND_EXPANDED_SELECTION,
        _LIVE_EXPAND_LAST_MERGE_SETTINGS,
        _LIVE_EXPAND_LAST_SETTINGS,
    ):
        for stale_name in set(state.keys()) - current_names:
            state.pop(stale_name, None)

    settings_signature = (
        bool(scene.prop_plasticity_select_adjacent_fillets),
        float(scene.prop_plasticity_select_fillet_min_curvature_angle),
        float(scene.prop_plasticity_select_fillet_max_area_ratio),
        int(scene.prop_plasticity_select_fillet_min_adjacent_groups),
        bool(scene.prop_plasticity_select_include_vertex_adjacency),
        float(scene.prop_plasticity_select_vertex_adjacent_max_length_ratio),
    )
    occluded_only = bool(getattr(scene, "prop_plasticity_auto_cylinder_seam_occluded_only", False))
    merge_enabled = (
        bool(scene.prop_plasticity_live_expand_auto_merge_seams)
        and not _LIVE_EXPAND_SUPPRESS_AUTO_MERGE
    )
    merge_settings = (
        merge_enabled,
        bool(scene.prop_plasticity_auto_cylinder_seam),
        bool(scene.prop_plasticity_live_expand_respect_seams),
        str(scene.prop_plasticity_auto_cylinder_seam_mode),
        float(scene.prop_plasticity_auto_cylinder_partial_angle),
        occluded_only,
    )
    view_context = _find_view3d_region(scene) if occluded_only else None

    any_changes = False
    prev_active = context.view_layer.objects.active

    for obj in edit_objects:
        mesh = obj.data
        groups = mesh.get("groups")
        face_ids = mesh.get("face_ids")
        if not groups or not face_ids:
            continue

        bm = bmesh.from_edit_mesh(mesh)
        group_faces, face_to_group = build_group_faces_map(groups, mesh, bm)
        if not group_faces:
            continue

        current_selection = {face.index for face in bm.faces if face.select}

        base_selection = _LIVE_EXPAND_BASE_SELECTION.get(obj.name)
        expanded_selection = _LIVE_EXPAND_EXPANDED_SELECTION.get(obj.name)
        if base_selection is None or expanded_selection is None:
            base_selection = set(current_selection)
            expanded_selection = set(current_selection)

        manual_change = False
        if current_selection != expanded_selection:
            added = current_selection - expanded_selection
            removed = expanded_selection - current_selection
            base_selection = (base_selection - removed) | added
            manual_change = True

        last_settings = _LIVE_EXPAND_LAST_SETTINGS.get(obj.name)
        settings_changed = settings_signature != last_settings
        last_merge_settings = _LIVE_EXPAND_LAST_MERGE_SETTINGS.get(obj.name)
        merge_settings_changed = merge_settings != last_merge_settings

        if (
            not manual_change
            and not settings_changed
            and not merge_settings_changed
        ):
            _LIVE_EXPAND_BASE_SELECTION[obj.name] = base_selection
            _LIVE_EXPAND_EXPANDED_SELECTION[obj.name] = expanded_selection
            continue

        any_changes = True
        _LIVE_EXPAND_LAST_SETTINGS[obj.name] = settings_signature

        seed_group_indices = set()
        for face_index in base_selection:
            group_idx = face_to_group.get(face_index)
            if group_idx is not None:
                seed_group_indices.add(group_idx)

        if not seed_group_indices:
            expanded_faces = set(current_selection)
            selection_changed = expanded_faces != expanded_selection
            changed_to_true = []
            changed_to_false = []
            if merge_settings[0] and (selection_changed or merge_settings_changed):
                changed_to_true, changed_to_false = _auto_merge_seams_on_selection(
                    bm,
                    expanded_faces,
                    merge_settings[2],
                )
                if merge_settings[1]:
                    cylinder_changed = _auto_cylinder_seam_on_selection(
                        bm,
                        expanded_faces,
                        mode=merge_settings[3],
                        partial_angle=merge_settings[4],
                        occluded_only=occluded_only,
                        obj=obj,
                        scene=scene,
                        view_context=view_context,
                    )
                    if cylinder_changed:
                        changed_to_true.extend(cylinder_changed)
            did_merge = bool(changed_to_true or changed_to_false)
            if did_merge:
                _touch_seams_version(mesh)
                bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=False)
                if prev_active != obj:
                    context.view_layer.objects.active = obj
                did_unwrap = _touch_live_unwrap_after_seam_change(
                    context,
                    changed_to_true,
                    changed_to_false,
                )
                if not did_unwrap:
                    if not _maybe_live_unwrap(context, force=True):
                        _queue_live_unwrap()
            _LIVE_EXPAND_EXPANDED_SELECTION[obj.name] = expanded_faces
            _LIVE_EXPAND_LAST_MERGE_SETTINGS[obj.name] = merge_settings
            _LIVE_EXPAND_BASE_SELECTION[obj.name] = base_selection
            continue

        fillet_group_indices = set()
        if scene.prop_plasticity_select_adjacent_fillets:
            group_areas, group_max_angles = compute_group_stats(group_faces, bm)
            edge_adjacency = build_group_adjacency(bm, face_to_group, len(group_faces))
            vertex_adjacency = None
            vertex_only_candidates = set()
            try:
                vertex_adjacent_max_length_ratio = float(
                    scene.prop_plasticity_select_vertex_adjacent_max_length_ratio
                )
            except Exception:
                vertex_adjacent_max_length_ratio = 1.0
            vertex_adjacent_filter = (
                scene.prop_plasticity_select_include_vertex_adjacency
                and vertex_adjacent_max_length_ratio < 1.0
            )
            group_sizes = None

            if scene.prop_plasticity_select_include_vertex_adjacency:
                vertex_adjacency = build_group_vertex_adjacency(
                    bm, face_to_group, len(group_faces))
                if vertex_adjacent_filter:
                    group_sizes = compute_group_bbox_sizes(group_faces, bm)
                adjacency = [
                    edge_adjacency[i] | vertex_adjacency[i]
                    for i in range(len(edge_adjacency))
                ]
                edge_neighbors = set()
                for group_idx in seed_group_indices:
                    if group_idx < len(edge_adjacency):
                        edge_neighbors.update(edge_adjacency[group_idx])
                vertex_neighbors = set()
                for group_idx in seed_group_indices:
                    if group_idx < len(vertex_adjacency):
                        vertex_neighbors.update(vertex_adjacency[group_idx])
                vertex_only_candidates = vertex_neighbors - edge_neighbors
            else:
                adjacency = edge_adjacency

            candidate_groups = set()
            for group_idx in seed_group_indices:
                if group_idx < len(adjacency):
                    candidate_groups.update(adjacency[group_idx])
            candidate_groups.difference_update(seed_group_indices)

            if vertex_adjacent_filter and vertex_only_candidates:
                seed_sizes = [
                    group_sizes[idx]
                    for idx in seed_group_indices
                    if idx < len(group_sizes) and group_sizes[idx] > 0.0
                ]
                seed_min_size = min(seed_sizes) if seed_sizes else 0.0

            for group_idx in candidate_groups:
                if (
                    vertex_adjacent_filter
                    and group_idx in vertex_only_candidates
                    and group_sizes is not None
                ):
                    neighbor_seeds = set()
                    if vertex_adjacency and group_idx < len(vertex_adjacency):
                        neighbor_seeds = vertex_adjacency[group_idx] & seed_group_indices
                    ref_size = seed_min_size
                    if neighbor_seeds:
                        neighbor_sizes = [
                            group_sizes[idx]
                            for idx in neighbor_seeds
                            if idx < len(group_sizes) and group_sizes[idx] > 0.0
                        ]
                        if neighbor_sizes:
                            ref_size = min(neighbor_sizes)
                    if ref_size > 0.0:
                        max_size = ref_size * vertex_adjacent_max_length_ratio
                        if group_sizes[group_idx] > max_size:
                            continue
                if is_fillet_group(
                    group_idx,
                    group_areas,
                    group_max_angles,
                    adjacency,
                    scene.prop_plasticity_select_fillet_min_curvature_angle,
                    scene.prop_plasticity_select_fillet_max_area_ratio,
                    scene.prop_plasticity_select_fillet_min_adjacent_groups,
                ):
                    fillet_group_indices.add(group_idx)

        final_group_indices = set(seed_group_indices)
        final_group_indices.update(fillet_group_indices)

        expanded_faces = set()
        for group_idx in final_group_indices:
            if group_idx >= len(group_faces):
                continue
            for face_index in group_faces[group_idx]:
                expanded_faces.add(face_index)

        for face in bm.faces:
            face.select = face.index in expanded_faces

        selection_changed = expanded_faces != expanded_selection
        changed_to_true = []
        changed_to_false = []
        if merge_settings[0] and (selection_changed or merge_settings_changed):
            changed_to_true, changed_to_false = _auto_merge_seams_on_selection(
                bm,
                expanded_faces,
                merge_settings[2],
            )
            if merge_settings[1]:
                cylinder_changed = _auto_cylinder_seam_on_selection(
                    bm,
                    expanded_faces,
                    mode=merge_settings[3],
                    partial_angle=merge_settings[4],
                    occluded_only=occluded_only,
                    obj=obj,
                    scene=scene,
                    view_context=view_context,
                )
                if cylinder_changed:
                    changed_to_true.extend(cylinder_changed)

        bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=False)
        if changed_to_true or changed_to_false:
            _touch_seams_version(mesh)
            if prev_active != obj:
                context.view_layer.objects.active = obj
            did_unwrap = _touch_live_unwrap_after_seam_change(
                context,
                changed_to_true,
                changed_to_false,
            )
            if not did_unwrap:
                if not _maybe_live_unwrap(context, force=True):
                    _queue_live_unwrap()
        _LIVE_EXPAND_EXPANDED_SELECTION[obj.name] = expanded_faces
        _LIVE_EXPAND_LAST_MERGE_SETTINGS[obj.name] = merge_settings
        _LIVE_EXPAND_BASE_SELECTION[obj.name] = base_selection

    if prev_active and prev_active != context.view_layer.objects.active:
        context.view_layer.objects.active = prev_active

    if not any_changes:
        _flush_pending_unwrap(context)
    else:
        _flush_pending_unwrap(context)
    return interval


def build_group_data(groups, mesh, bm):
    group_faces, face_to_group = build_group_faces_map(groups, mesh, bm)
    group_areas, group_max_angles = compute_group_stats(group_faces, bm)
    return group_faces, face_to_group, group_areas, group_max_angles


def build_group_adjacency(bm, face_to_group, group_count):
    adjacency = [set() for _ in range(group_count)]
    for edge in bm.edges:
        if len(edge.link_faces) != 2:
            continue
        face_a, face_b = edge.link_faces
        group_a = face_to_group.get(face_a.index)
        group_b = face_to_group.get(face_b.index)
        if group_a is None or group_b is None or group_a == group_b:
            continue
        adjacency[group_a].add(group_b)
        adjacency[group_b].add(group_a)
    return adjacency


def build_group_vertex_adjacency(bm, face_to_group, group_count):
    adjacency = [set() for _ in range(group_count)]
    for vert in bm.verts:
        group_ids = set()
        for face in vert.link_faces:
            group_id = face_to_group.get(face.index)
            if group_id is not None:
                group_ids.add(group_id)
        if len(group_ids) < 2:
            continue
        for group_id in group_ids:
            adjacency[group_id].update(group_ids - {group_id})
    return adjacency


def is_fillet_group(
    group_id,
    group_areas,
    group_max_angles,
    adjacency,
    min_curvature_angle,
    max_area_ratio,
    min_adjacent_groups,
):
    if group_max_angles[group_id] < min_curvature_angle:
        return False
    neighbors = adjacency[group_id]
    if len(neighbors) < min_adjacent_groups:
        return False
    max_neighbor_area = 0.0
    for neighbor_id in neighbors:
        area = group_areas[neighbor_id]
        if area > max_neighbor_area:
            max_neighbor_area = area
    if max_neighbor_area <= 0.0:
        return False
    return group_areas[group_id] <= max_neighbor_area * max_area_ratio


class PaintPlasticityFacesOperator(bpy.types.Operator):
    bl_idname = "mesh.paint_plasticity_faces"
    bl_label = "Paint Plasticity Faces"
    bl_description = (
        "Assign random vertex colors per Plasticity surface and apply a vertex-color material. "
        "Overwrites the first material slot"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == 'EDIT_MESH':
            obj = context.active_object
            return bool(obj and obj.type == 'MESH' and "plasticity_id" in obj.keys())
        return any("plasticity_id" in obj.keys() and obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        prev_obj_mode = bpy.context.mode

        objects = list(context.selected_objects)
        if not objects and context.active_object:
            objects = [context.active_object]

        for obj in objects:
            if obj.type != 'MESH':
                continue
            if not "plasticity_id" in obj.keys():
                continue
            mesh = obj.data

            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='OBJECT')

            self.colorize_mesh(obj, mesh)

            mat = bpy.data.materials.new(name="VertexColorMat")
            mat.use_nodes = True
            nodes = mat.node_tree.nodes

            for node in nodes:
                nodes.remove(node)

            vertex_color_node = nodes.new(type='ShaderNodeVertexColor')
            shader_node = nodes.new(type='ShaderNodeBsdfPrincipled')
            shader_node.location = (400, 0)
            mat.node_tree.links.new(
                shader_node.inputs['Base Color'], vertex_color_node.outputs['Color'])

            material_output = nodes.new(type='ShaderNodeOutputMaterial')
            material_output.location = (800, 0)
            mat.node_tree.links.new(
                material_output.inputs['Surface'], shader_node.outputs['BSDF'])

            if obj.data.materials:
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)

        bpy.ops.object.mode_set(mode=map_mode(prev_obj_mode))

        return {'FINISHED'}

    def colorize_mesh(self, obj, mesh):
        groups = mesh["groups"]
        face_ids = mesh["face_ids"]

        if len(groups) == 0:
            return
        if len(face_ids) * 2 != len(groups):
            return

        if not mesh.vertex_colors:
            mesh.vertex_colors.new()
        color_layer = mesh.vertex_colors.active

        group_idx = 0
        group_start = groups[group_idx * 2 + 0]
        group_count = groups[group_idx * 2 + 1]
        face_id = face_ids[group_idx]
        color = generate_random_color(face_id)

        for poly in mesh.polygons:
            loop_start = poly.loop_start
            if loop_start >= group_start + group_count:
                group_idx += 1
                group_start = groups[group_idx * 2 + 0]
                group_count = groups[group_idx * 2 + 1]
                face_id = face_ids[group_idx]
                color = generate_random_color(face_id)
            for loop_index in range(loop_start, loop_start + poly.loop_total):
                color_layer.data[loop_index].color = color

class NonOverlappingMeshesMerger(bpy.types.Operator):
    bl_idname = "object.merge_nonoverlapping_meshes"
    bl_label = "Merge Non-overlapping Meshes"
    bl_description = (
        "Join meshes that do not overlap within the threshold (selection or visible objects). "
        "Destructive and can be slow on large scenes"
    )
    bl_options = {'REGISTER', 'UNDO'}

    overlap_threshold: bpy.props.FloatProperty(
        name="Overlap Threshold",
        description="Distance below which meshes are considered overlapping",
        default=0.01,
        min=0.0,
        max=1.0,
    )

    def check_overlap(self, obj1, obj2, overlap_threshold, object_data):
        data_a = object_data.get(obj1)
        data_b = object_data.get(obj2)
        if not data_a or not data_b:
            return False

        threshold_sq = overlap_threshold * overlap_threshold
        dist_sq = self._aabb_distance_sq(
            data_a["bbox_min"], data_a["bbox_max"],
            data_b["bbox_min"], data_b["bbox_max"],
        )
        if dist_sq > threshold_sq:
            return False

        if len(data_a["verts"]) <= len(data_b["verts"]):
            tree = data_b["tree"]
            coords = data_a["verts"]
        else:
            tree = data_a["tree"]
            coords = data_b["verts"]

        for co in coords:
            _, _, dist = tree.find(co)
            if dist < overlap_threshold:
                return True

        return False

    def _aabb_distance_sq(self, min_a, max_a, min_b, max_b):
        dx = max(min_b.x - max_a.x, min_a.x - max_b.x, 0.0)
        dy = max(min_b.y - max_a.y, min_a.y - max_b.y, 0.0)
        dz = max(min_b.z - max_a.z, min_a.z - max_b.z, 0.0)
        return dx * dx + dy * dy + dz * dz

    def _world_bounds(self, obj):
        mat = obj.matrix_world
        corners = [mat @ mathutils.Vector(corner) for corner in obj.bound_box]
        min_v = mathutils.Vector((
            min(c.x for c in corners),
            min(c.y for c in corners),
            min(c.z for c in corners),
        ))
        max_v = mathutils.Vector((
            max(c.x for c in corners),
            max(c.y for c in corners),
            max(c.z for c in corners),
        ))
        return min_v, max_v

    def _build_object_data(self, objects):
        object_data = {}
        for obj in objects:
            mesh = obj.data
            if not mesh or len(mesh.vertices) == 0:
                continue

            mat = obj.matrix_world
            verts_world = [mat @ v.co for v in mesh.vertices]
            tree = mathutils.kdtree.KDTree(len(verts_world))
            for i, co in enumerate(verts_world):
                tree.insert(co, i)
            tree.balance()

            bbox_min, bbox_max = self._world_bounds(obj)
            object_data[obj] = {
                "verts": verts_world,
                "tree": tree,
                "bbox_min": bbox_min,
                "bbox_max": bbox_max,
            }
        return object_data

    def merge_meshes(self, obj1, obj2):
        bpy.ops.object.select_all(action='DESELECT') 
        obj1.select_set(True)
        obj2.select_set(True)
        bpy.context.view_layer.objects.active = obj1
        bpy.ops.object.join()

    def execute(self, context):
        overlap_threshold = self.overlap_threshold
        context.scene.overlap_threshold = overlap_threshold

        selected_mesh_objects = [
            obj for obj in context.selected_objects if obj.type == 'MESH'
        ]
        use_selection = bool(selected_mesh_objects)
        if use_selection:
            base_object_names = [obj.name for obj in selected_mesh_objects]
        else:
            base_object_names = [
                obj.name for obj in context.scene.objects
                if obj.type == 'MESH' and obj.visible_get()
            ]
        if len(base_object_names) < 2:
            return {'FINISHED'}

        merged = True

        while merged:
            mesh_objects = [
                obj for name in base_object_names
                for obj in [bpy.data.objects.get(name)]
                if obj is not None
            ]
            if len(mesh_objects) < 2:
                return {'FINISHED'}

            object_data = self._build_object_data(mesh_objects)
            used = set()
            merge_occurred = False

            for i, obj1 in enumerate(mesh_objects):
                if obj1 in used:
                    continue
                for obj2 in mesh_objects[i + 1:]:
                    if obj2 in used:
                        continue
                    if not self.check_overlap(obj1, obj2, overlap_threshold, object_data):
                        self.merge_meshes(obj1, obj2)
                        used.add(obj1)
                        used.add(obj2)
                        merge_occurred = True
                        break

            merged = merge_occurred

        return {'FINISHED'}

class SimilarGeometrySelector(bpy.types.Operator):
    bl_idname = "object.select_similar_geometry"
    bl_label = "Select Similar Geometry"
    bl_description = (
        "Select meshes similar to the active object's vertex/poly counts and total area. "
        "Ignores transforms and materials"
    )
    bl_options = {'REGISTER', 'UNDO'}
    
    similarity_threshold: bpy.props.FloatProperty(
    name="Similarity Threshold",
    description="Percentage difference between objects to consider them similar",
    default=0.2,  # 20% difference allowed
    min=0.0,
    max=1.0)

    def execute(self, context):
        active_object = context.active_object
        if active_object and active_object.type == 'MESH':
            active_vert_count = len(active_object.data.vertices)
            active_poly_count = len(active_object.data.polygons)
            
            # Calculate total surface area for the active object
            active_surface_area = sum(poly.area for poly in active_object.data.polygons)

            for obj in bpy.context.scene.objects:
                if obj.type == 'MESH':
                    vert_count = len(obj.data.vertices)
                    poly_count = len(obj.data.polygons)
                    
                    # Calculate total surface area for the current object
                    surface_area = sum(poly.area for poly in obj.data.polygons)
                    
                    # Calculate percentage difference for vertices, polygons and surface area
                    vert_diff = abs(vert_count - active_vert_count) / active_vert_count
                    poly_diff = abs(poly_count - active_poly_count) / active_poly_count
                    area_diff = abs(surface_area - active_surface_area) / active_surface_area

                    # If all differences are within the threshold, select the object
                    if vert_diff <= self.similarity_threshold and poly_diff <= self.similarity_threshold and area_diff <= self.similarity_threshold:
                        obj.select_set(True)

        return {'FINISHED'}

class SelectedJoiner(bpy.types.Operator):
    bl_idname = "object.join_selected"
    bl_label = "Join Selected"
    bl_description = "Join selected objects into the active object. Destructive"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bpy.ops.object.join()
        
        return {'FINISHED'}

class SelectedUnjoiner(bpy.types.Operator):
    bl_idname = "object.unjoin_selected"
    bl_label = "Unjoin Selected"
    bl_description = (
        "Separate selected meshes by loose parts. "
        "Creates new objects and may change names"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        original_objects = context.selected_objects
        for obj in original_objects:
            context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.separate(type='LOOSE')
            bpy.ops.object.mode_set(mode='OBJECT')

            temp_name = obj.name + "_temp_unique_name"
            for new_obj in context.selected_objects:
                if new_obj not in original_objects: 
                    new_obj.name = temp_name

        for obj in bpy.data.objects:
            if obj.name.startswith(temp_name):
                obj.name = obj.name.replace(temp_name, "")

        return {'FINISHED'}    

class OpenUVEditorOperator(bpy.types.Operator):
    bl_idname = "object.open_uv_editor"
    bl_label = "Open UV Editor"
    bl_description = (
        "Open a temporary UV Editor window and select all faces on selected meshes. "
        "Temporarily changes render display settings"
    )
    bl_options = {'REGISTER'}

    def execute(self, context):
        wm = context.window_manager
        existing_windows = {window.as_pointer() for window in wm.windows}

        original_resolution_x = context.scene.render.resolution_x
        original_resolution_y = context.scene.render.resolution_y
        original_resolution_percentage = context.scene.render.resolution_percentage

        context.scene.render.resolution_x = 800
        context.scene.render.resolution_y = 600
        context.scene.render.resolution_percentage = 100

        original_display_type = context.preferences.view.render_display_type
        context.preferences.view.render_display_type = 'WINDOW'

        # Intentionally do not change mode or selection to avoid triggering
        # auto-merge seams or altering user selections.

        bpy.ops.render.view_show('INVOKE_DEFAULT')

        context.scene.render.resolution_x = original_resolution_x
        context.scene.render.resolution_y = original_resolution_y
        context.scene.render.resolution_percentage = original_resolution_percentage

        context.preferences.view.render_display_type = original_display_type

        new_window = None
        for window in wm.windows:
            if window.as_pointer() not in existing_windows:
                new_window = window
                break
        if new_window is None:
            new_window = wm.windows[-1]

        wm["plasticity_uv_window"] = str(new_window.as_pointer())
        new_area = new_window.screen.areas[0]
        new_area.type = 'IMAGE_EDITOR'
        new_area.spaces.active.mode = 'UV'

        new_area.spaces.active.image = None
        
        return {'FINISHED'}

class MaterialRemover(bpy.types.Operator):
    bl_idname = "object.remove_materials"
    bl_label = "Remove Materials"
    bl_description = "Remove all material slots from selected mesh objects. Destructive"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for obj in context.selected_editable_objects:
            if obj.type == 'MESH':
                obj.data.materials.clear()
        return {'FINISHED'}


class TextureReloader(bpy.types.Operator):
    bl_idname = "object.reload_textures"
    bl_label = "Reload Textures"
    bl_description = "Reload all images in the blend file from disk"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for image in bpy.data.images:
            image.reload()
        return {'FINISHED'}


class AssignUVCheckerTextureOperator(bpy.types.Operator):
    bl_idname = "object.assign_uv_checker_texture"
    bl_label = "Assign Checker Texture"
    bl_description = "Assign a UV checker image material to selected mesh objects"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode not in {'OBJECT', 'EDIT_MESH'}:
            return False
        if context.mode == 'EDIT_MESH':
            edit_objects = getattr(context, "objects_in_mode", None)
            return any(obj and obj.type == 'MESH' for obj in edit_objects or [])
        return any(obj.type == 'MESH' for obj in context.selected_objects) or (
            context.active_object and context.active_object.type == 'MESH'
        )

    def execute(self, context):
        filepath = self._resolve_image_path(context)
        if not filepath:
            return {'CANCELLED'}
        if not os.path.exists(filepath):
            self.report({'ERROR'}, "Checker image not found")
            return {'CANCELLED'}
        try:
            image = bpy.data.images.load(filepath, check_existing=True)
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to load image: {exc}")
            return {'CANCELLED'}

        material = self._get_checker_material(image)
        objects = self._target_objects(context)
        if not objects:
            self.report({'WARNING'}, "No mesh objects to assign")
            return {'CANCELLED'}

        for obj in objects:
            if obj.type != 'MESH':
                continue
            mesh = obj.data
            slot_index = self._ensure_material_slot(mesh, material)
            if context.mode == 'EDIT_MESH' and obj.mode == 'EDIT':
                bm = bmesh.from_edit_mesh(mesh)
                self._ensure_uv_map_edit(mesh, bm)
                selected_faces = [face for face in bm.faces if face.select]
                faces = selected_faces if selected_faces else bm.faces
                for face in faces:
                    face.material_index = slot_index
                bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
                self._ensure_uv_map_object(mesh)
            else:
                self._ensure_uv_map_object(mesh)
                for poly in mesh.polygons:
                    poly.material_index = slot_index

        return {'FINISHED'}

    def _resolve_image_path(self, context):
        scene = context.scene
        source = getattr(scene, "prop_plasticity_checker_source", "LIBRARY")
        if source == "FILE":
            filepath = getattr(scene, "prop_plasticity_checker_custom_path", "")
            if not filepath:
                message = "Select a checker image file using the folder button"
                self.report({'ERROR'}, message)
                return None
            return bpy.path.abspath(filepath)

        filename = getattr(scene, "prop_plasticity_checker_image", "NONE")
        if not filename or filename == "NONE":
            self.report({'ERROR'}, "Select a checker texture from the list")
            return None
        resolved = get_checker_filename(filename)
        if not resolved:
            self.report({'ERROR'}, "Selected checker texture is unavailable")
            return None
        return os.path.join(_checker_images_dir(), resolved)

    @staticmethod
    def _target_objects(context):
        if context.mode == 'EDIT_MESH':
            edit_objects = getattr(context, "objects_in_mode", None)
            if edit_objects:
                return [obj for obj in edit_objects if obj and obj.type == 'MESH']
            obj = context.active_object
            return [obj] if obj and obj.type == 'MESH' else []
        objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not objects and context.active_object and context.active_object.type == 'MESH':
            objects = [context.active_object]
        return objects

    @staticmethod
    def _ensure_material_slot(mesh, material):
        for idx, slot_mat in enumerate(mesh.materials):
            if slot_mat == material:
                return idx
        mesh.materials.append(material)
        return len(mesh.materials) - 1

    @staticmethod
    def _ensure_uv_map_object(mesh):
        if not mesh.uv_layers:
            mesh.uv_layers.new(name="UVMap")
        if mesh.uv_layers.active is None and mesh.uv_layers:
            mesh.uv_layers.active_index = 0

    @staticmethod
    def _ensure_uv_map_edit(mesh, bm):
        if not mesh.uv_layers or bm.loops.layers.uv.active is None:
            bm.loops.layers.uv.verify()

    @staticmethod
    def _get_checker_material(image):
        image_id = image.filepath or image.name
        for mat in bpy.data.materials:
            if mat.get("plasticity_uv_checker_image") == image_id:
                return mat

        mat_name = f"Plasticity_UV_Checker_{image.name}" if image.name else "Plasticity_UV_Checker"
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        for node in list(nodes):
            nodes.remove(node)

        tex_node = nodes.new(type='ShaderNodeTexImage')
        tex_node.name = "PlasticityUVCheckerImage"
        tex_node.label = "Plasticity UV Checker"
        tex_node["plasticity_uv_checker_node"] = True
        tex_node.image = image
        tex_node.location = (-400, 0)
        bsdf_node = nodes.new(type='ShaderNodeBsdfPrincipled')
        bsdf_node.location = (0, 0)
        output_node = nodes.new(type='ShaderNodeOutputMaterial')
        output_node.location = (300, 0)
        mat.node_tree.links.new(bsdf_node.inputs['Base Color'], tex_node.outputs['Color'])
        mat.node_tree.links.new(output_node.inputs['Surface'], bsdf_node.outputs['BSDF'])

        mat["plasticity_uv_checker_image"] = image_id
        return mat


class SelectCheckerImageOperator(bpy.types.Operator):
    bl_idname = "object.select_checker_image"
    bl_label = "Select Checker Image"
    bl_description = "Select a custom checker image from disk"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.tga;*.tif;*.tiff;*.bmp;*.exr",
        options={'HIDDEN'},
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self.filepath:
            self.report({'ERROR'}, "Select an image file")
            return {'CANCELLED'}
        context.scene.prop_plasticity_checker_custom_path = self.filepath
        context.scene.prop_plasticity_checker_source = "FILE"
        return {'FINISHED'}


class RemoveUVCheckerNodesOperator(bpy.types.Operator):
    bl_idname = "object.remove_uv_checker_nodes"
    bl_label = "Remove Checker Nodes"
    bl_description = "Remove Plasticity checker texture nodes from selected objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objects = AssignUVCheckerTextureOperator._target_objects(context)
        if not objects:
            self.report({'WARNING'}, "No mesh objects to update")
            return {'CANCELLED'}
        removed = 0
        for obj in objects:
            if obj.type != 'MESH':
                continue
            for slot in obj.material_slots:
                mat = slot.material
                if not mat or not mat.use_nodes or not mat.node_tree:
                    continue
                removed += self._remove_checker_nodes(mat)
        if removed == 0:
            self.report({'INFO'}, "No checker nodes found")
        return {'FINISHED'}

    @staticmethod
    def _remove_checker_nodes(material):
        nodes = material.node_tree.nodes
        removed = 0
        for node in list(nodes):
            if node.type != 'TEX_IMAGE':
                continue
            if node.get("plasticity_uv_checker_node"):
                nodes.remove(node)
                removed += 1
        if removed and "plasticity_uv_checker_image" in material:
            del material["plasticity_uv_checker_image"]
        return removed


class CloseUVEditorOperator(bpy.types.Operator):
    bl_idname = "object.close_uv_editor"
    bl_label = "Close UV Editor"
    bl_description = (
        "Close the UV Editor window opened by this add-on. "
        "If not found, tries to close a temporary UV window"
    )
    bl_options = {'REGISTER'}

    def execute(self, context):
        wm = context.window_manager
        target_pointer = wm.get("plasticity_uv_window")
        target_window = None

        if target_pointer:
            for window in wm.windows:
                if str(window.as_pointer()) == str(target_pointer):
                    target_window = window
                    break

        if target_window is None:
            for window in wm.windows:
                if window == context.window:
                    continue
                screen = window.screen
                if hasattr(screen, "is_temporary") and not screen.is_temporary:
                    continue
                if len(screen.areas) != 1:
                    continue
                area = screen.areas[0]
                if area.type != 'IMAGE_EDITOR':
                    continue
                if area.spaces.active.mode != 'UV':
                    continue
                target_window = window
                break

        if target_window is None:
            self.report({'INFO'}, "No UV editor window found.")
            return {'CANCELLED'}

        with context.temp_override(window=target_window):
            bpy.ops.wm.window_close()
        if "plasticity_uv_window" in wm:
            del wm["plasticity_uv_window"]
        return {'FINISHED'}


class ImportFBXOperator(bpy.types.Operator):
    bl_idname = "object.import_fbx"
    bl_label = "Import FBX"
    bl_description = "Import an FBX file using the file browser"
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        bpy.ops.import_scene.fbx(filepath=self.filepath)
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class ExportFBXOperator(bpy.types.Operator):
    bl_idname = "object.export_fbx"
    bl_label = "Export FBX"
    bl_description = "Export selected objects to FBX"
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        bpy.ops.export_scene.fbx(filepath=self.filepath, use_selection=True)
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class ImportOBJOperator(bpy.types.Operator):
    bl_idname = "object.import_obj"
    bl_label = "Import OBJ"
    bl_description = "Import an OBJ file (tries the new importer first, then legacy)"
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        result = None
        try:
            result = bpy.ops.wm.obj_import(filepath=self.filepath)
        except Exception:
            result = None

        if result is None or 'CANCELLED' in result:
            try:
                result = bpy.ops.import_scene.obj(filepath=self.filepath)
            except Exception as exc:
                self.report({'ERROR'}, f"OBJ import failed: {exc}")
                return {'CANCELLED'}

        return result

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class ExportOBJOperator(bpy.types.Operator):
    bl_idname = "object.export_obj"
    bl_label = "Export OBJ"
    bl_description = "Export selected objects to OBJ (tries the new exporter first, then legacy)"
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        result = None
        try:
            result = bpy.ops.wm.obj_export(
                filepath=self.filepath, export_selected_objects=True)
        except Exception:
            result = None

        if result is None or 'CANCELLED' in result:
            try:
                result = bpy.ops.export_scene.obj(
                    filepath=self.filepath, use_selection=True)
            except Exception as exc:
                self.report({'ERROR'}, f"OBJ export failed: {exc}")
                return {'CANCELLED'}

        return result

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class MirrorOperator(bpy.types.Operator):
    bl_idname = "object.mirror"
    bl_label = "Mirror Selected"
    bl_description = (
        "Duplicate and mirror selected objects around the chosen axis and center. "
        "Uses the cursor pivot temporarily"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        axis = context.scene.mirror_axis
        mirror_center_object = context.scene.mirror_center_object

        if mirror_center_object:
            mirror_center = mirror_center_object.location
        else:
            mirror_center = mathutils.Vector((0, 0, 0))

        original_cursor_location = mathutils.Vector(context.scene.cursor.location)
        original_pivot_point = context.tool_settings.transform_pivot_point

        context.scene.cursor.location = mirror_center
        context.tool_settings.transform_pivot_point = 'CURSOR'

        for obj in context.selected_objects:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)

            bpy.ops.object.duplicate()

            if axis == 'X':
                bpy.ops.transform.mirror(constraint_axis=(True, False, False))
            elif axis == 'Y':
                bpy.ops.transform.mirror(constraint_axis=(False, True, False))
            elif axis == 'Z':
                bpy.ops.transform.mirror(constraint_axis=(False, False, True))

        context.scene.cursor.location = original_cursor_location
        context.tool_settings.transform_pivot_point = original_pivot_point

        return {'FINISHED'}


class RemoveModifiers(bpy.types.Operator):
    bl_idname = "object.remove_modifiers"
    bl_label = "Remove Modifiers"
    bl_description = "Remove all modifiers from selected objects. Destructive"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for obj in bpy.context.selected_objects:
            for modifier in obj.modifiers:
                obj.modifiers.remove(modifier)
        return {'FINISHED'}


class ApplyModifiers(bpy.types.Operator):
    bl_idname = "object.apply_modifiers"
    bl_label = "Apply Modifiers"
    bl_description = "Apply all modifiers on selected objects. Destructive and may change topology"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_objects = bpy.context.selected_objects

        for obj in selected_objects:
            if obj.modifiers:
                for modifier in obj.modifiers:
                    bpy.context.view_layer.objects.active = obj
                    bpy.ops.object.modifier_apply(modifier=modifier.name)
        return {'FINISHED'}


class RemoveVertexGroups(bpy.types.Operator):
    bl_idname = "object.remove_vertex_groups"
    bl_label = "Remove Vertex Groups"
    bl_description = "Remove all vertex groups from selected mesh objects. Destructive"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_objects = bpy.context.selected_objects

        for obj in selected_objects:
            if obj.type == 'MESH':
                if obj.vertex_groups:
                    for vg in obj.vertex_groups:
                        obj.vertex_groups.remove(vg)
        return {'FINISHED'}


class SnapToCursorOperator(bpy.types.Operator):
    bl_idname = "object.snap_to_cursor"
    bl_label = "Snap to 3D Cursor"
    bl_description = (
        "Move selected objects or armature bones to the 3D cursor. "
        "Useful for snapping bones before rigging; optional plane constraint"
    )
    bl_options = {'REGISTER', 'UNDO'}

    plane: bpy.props.EnumProperty(
        items=[
            ('XY', "XY", "Constrain to XY plane"),
            ('YZ', "YZ", "Constrain to YZ plane"),
            ('XZ', "XZ", "Constrain to XZ plane"),
            ('NONE', "None", "No constraint")
        ],
        name="Constraint Plane",
        description="The plane to constrain the snap to",
        default='NONE'
    )

    def execute(self, context):
        cursor_location = context.scene.cursor.location
        if context.object.type == 'ARMATURE' and context.mode == 'EDIT_ARMATURE':
            armature = context.object
            override = {'selected_editable_bones': armature.data.edit_bones}
            for bone in bpy.data.armatures[armature.data.name].edit_bones:
                if bone.select_head:
                    if self.plane == 'XY':
                        bone.head.x = cursor_location.x
                        bone.head.y = cursor_location.y
                    elif self.plane == 'YZ':
                        bone.head.y = cursor_location.y
                        bone.head.z = cursor_location.z
                    elif self.plane == 'XZ':
                        bone.head.x = cursor_location.x
                        bone.head.z = cursor_location.z
                    else:
                        bone.head = cursor_location
                if bone.select_tail:
                    if self.plane == 'XY':
                        bone.tail.x = cursor_location.x
                        bone.tail.y = cursor_location.y
                    elif self.plane == 'YZ':
                        bone.tail.y = cursor_location.y
                        bone.tail.z = cursor_location.z
                    elif self.plane == 'XZ':
                        bone.tail.x = cursor_location.x
                        bone.tail.z = cursor_location.z
                    else:
                        bone.tail = cursor_location
        else:
            for obj in context.selected_objects:
                if self.plane == 'XY':
                    obj.location.x = cursor_location.x
                    obj.location.y = cursor_location.y
                elif self.plane == 'YZ':
                    obj.location.y = cursor_location.y
                    obj.location.z = cursor_location.z
                elif self.plane == 'XZ':
                    obj.location.x = cursor_location.x
                    obj.location.z = cursor_location.z
                else:
                    obj.location = cursor_location
        return {'FINISHED'}



class SelectMeshesWithNgons(bpy.types.Operator):
    bl_idname = "object.select_meshes_with_ngons"
    bl_label = "Select Meshes with Ngons"
    bl_description = "Select mesh objects that contain ngons (>4 vertices). Scans the whole scene"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bpy.ops.object.select_all(action='DESELECT')

        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                obj.select_set(False)
                for polygon in obj.data.polygons:
                    if len(polygon.vertices) > 4:
                        obj.select_set(True)
                        bpy.context.view_layer.objects.active = obj
                        break

        self.report({'INFO'}, "Selected all objects with ngons!")
        return {'FINISHED'}


class SelectObjectsWithoutUVs(bpy.types.Operator):
    bl_idname = "object.select_without_uvs"
    bl_label = "Select Objects Without UVs"
    bl_description = "Select mesh objects that have no UV layers. Scans the whole scene"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for obj in context.view_layer.objects:
            obj.select_set(False)

        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                mesh = obj.data
                if not mesh.uv_layers:
                    obj.select_set(True)

        return {'FINISHED'}


class RemoveUVsFromSelectedObjects(bpy.types.Operator):
    bl_idname = "object.remove_uvs_from_selected"
    bl_label = "Remove UVs from Selected Objects"
    bl_description = "Remove all UV layers from selected mesh objects. Destructive"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for obj in bpy.context.selected_objects:
            if obj.type == 'MESH':
                mesh = obj.data
                for uv_layer in mesh.uv_layers:
                    mesh.uv_layers.remove(uv_layer)

        return {'FINISHED'}


def are_normals_different(normal_a, normal_b, threshold_angle_degrees=5.0):
    threshold_cosine = math.cos(math.radians(threshold_angle_degrees))
    dot_product = normal_a.dot(normal_b)
    return dot_product < threshold_cosine


def generate_random_color(face_id):
    return (random.random(), random.random(), random.random(), 1.0)  # RGBA


mode_map = {
    'EDIT_MESH': 'EDIT',
    'EDIT_CURVE': 'EDIT',
    'EDIT_SURFACE': 'EDIT',
    'EDIT_TEXT': 'EDIT',
    'EDIT_ARMATURE': 'EDIT',
    'EDIT_METABALL': 'EDIT',
    'EDIT_LATTICE': 'EDIT',
    'POSE': 'EDIT',
}


def map_mode(context_mode):
    return mode_map.get(context_mode, context_mode)
