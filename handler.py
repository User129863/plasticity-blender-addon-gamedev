# TODO:
# - [ ] All on_... methods should call operators (to better handle undo, to have reporting be visible in the ui, etc)
from collections import defaultdict
from enum import Enum
import time

import bpy
import mathutils
import numpy as np


class PlasticityIdUniquenessScope(Enum):
    ITEM = 0
    GROUP = 1
    EMPTY = 2


class ObjectType(Enum):
    SOLID = 0
    SHEET = 1
    WIRE = 2
    GROUP = 5
    EMPTY = 6


class SceneHandler:
    def __init__(self):
        # NOTE: filename -> [item/group] -> id -> object
        # NOTE: items/groups have overlapping ids
        # NOTE: it turns out that caching this is unsafe with undo/redo; call __prepare() before every update
        self.files = {}
        self.list_filter_ids = None
        self._status_min_interval = 1.0
        self._last_status_time = 0.0
        self._last_status_text = None

    def __create_mesh(self, name, verts, indices, normals, groups, face_ids):
        mesh = bpy.data.meshes.new(name)
        mesh.vertices.add(len(verts) // 3)
        mesh.vertices.foreach_set("co", verts)
        mesh.loops.add(len(indices))
        mesh.loops.foreach_set("vertex_index", indices)
        mesh.polygons.add(len(indices) // 3)
        mesh.polygons.foreach_set("loop_total", np.full(
            len(indices) // 3, 3, dtype=np.int32))
        mesh.polygons.foreach_set("loop_start", np.arange(
            0, len(indices), 3, dtype=np.int32))

        # NOTE: As of blender 4.2, the concrete type of user attributes cannot be numpy arrays.
        assert isinstance(groups, list)
        assert isinstance(face_ids, list)
        _apply_plasticity_groups_and_normals(
            mesh, indices, normals, groups, face_ids)

        return mesh

    def __update_object_and_mesh(self, obj, object_type, version, name, verts, indices, normals, groups, face_ids):
        if obj.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')

        obj.name = name

        mesh = obj.data
        mesh.clear_geometry()

        mesh.vertices.add(len(verts) // 3)
        mesh.vertices.foreach_set("co", verts)

        mesh.loops.add(len(indices))
        mesh.loops.foreach_set("vertex_index", indices)

        mesh.polygons.add(len(indices) // 3)
        mesh.polygons.foreach_set("loop_start", range(0, len(indices), 3))
        mesh.polygons.foreach_set("loop_total", [3] * (len(indices) // 3))

        # NOTE: As of blender 4.2, the concrete type of user attributes cannot be numpy arrays.
        assert isinstance(groups, list)
        assert isinstance(face_ids, list)
        _apply_plasticity_groups_and_normals(
            mesh, indices, normals, groups, face_ids)

        self.update_pivot(obj)

    def __update_mesh_ngons(self, obj, version, faces, verts, indices, normals, groups, face_ids):
        if obj.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')

        mesh = obj.data
        mesh.clear_geometry()

        verts_array = np.array(verts).reshape(-1, 3)
        unique_verts, inverse_indices = np.unique(
            verts_array, axis=0, return_inverse=True)
        new_indices = inverse_indices[indices]

        mesh.vertices.add(len(unique_verts))
        mesh.vertices.foreach_set("co", unique_verts.ravel())

        mesh.loops.add(len(indices))
        mesh.loops.foreach_set("vertex_index", new_indices)

        if (len(faces) == 0):
            mesh.polygons.add(len(new_indices) // 3)
            mesh.polygons.foreach_set(
                "loop_start", range(0, len(new_indices), 3))
            mesh.polygons.foreach_set(
                "loop_total", [3] * (len(new_indices) // 3))
        else:
            # Find where a new face/polygon starts (value changes in the array)
            diffs = np.where(np.diff(faces))[0] + 1
            # Insert the starting index for the first polygon
            loop_start = np.insert(diffs, 0, 0)
            # Calculate the number of vertices per polygon
            loop_total = np.append(np.diff(loop_start), [
                                   len(faces) - loop_start[-1]])
            mesh.polygons.add(len(loop_start))
            mesh.polygons.foreach_set("loop_start", loop_start)
            mesh.polygons.foreach_set("loop_total", loop_total)
            # NOTE: safe_loop_normals happens after group validation.

        # NOTE: As of blender 4.2, the concrete type of user attributes cannot be numpy arrays.
        assert isinstance(groups, list)
        assert isinstance(face_ids, list)
        _apply_plasticity_groups_and_normals(
            mesh, indices, normals, groups, face_ids)

        self.update_pivot(obj)

    def update_pivot(self, obj):
        # NOTE: this doesn't work unfortunately. It seems like changing matrix_world or matrix_local
        # is only possible in special contexts that I cannot yet figure out.
        return
        if not "plasticity_transform" in obj:
            return
        transform_list = obj["plasticity_transform"]
        if transform_list is not None:
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            bpy.ops.object.mode_set(mode='OBJECT')
            old_matrix_world = obj.matrix_world.copy()
            transform = np.array(transform_list).reshape(4, 4)
            obj.matrix_world = mathutils.Matrix(transform)
            obj.matrix_world.invert()
            bpy.ops.object.transform_apply(
                location=True, rotation=True, scale=True)
            obj.matrix_world = old_matrix_world

    def __add_object(self, filename, object_type, plasticity_id, name, mesh):
        mesh_obj = bpy.data.objects.new(name, mesh)
        self.files[filename][PlasticityIdUniquenessScope.ITEM][plasticity_id] = mesh_obj
        mesh_obj["plasticity_id"] = plasticity_id
        mesh_obj["plasticity_filename"] = filename
        return mesh_obj

    def __delete_object(self, filename, version, plasticity_id):
        obj = self.files[filename][PlasticityIdUniquenessScope.ITEM].pop(
            plasticity_id, None)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)

    def __delete_group(self, filename, version, plasticity_id):
        group = self.files[filename][PlasticityIdUniquenessScope.GROUP].pop(
            plasticity_id, None)
        if group:
            bpy.data.collections.remove(group, do_unlink=True)

    def __replace_objects(self, filename, inbox_collection, version, objects):
        scene = bpy.context.scene
        prop_plasticity_unit_scale = scene.prop_plasticity_unit_scale

        collections_to_unlink = set()

        for item in objects:
            object_type = item['type']
            name = item['name']
            plasticity_id = item['id']
            material_id = item['material_id']
            parent_id = item['parent_id']
            flags = item['flags']
            verts = item['vertices']
            faces = item['faces']
            normals = item['normals']
            groups = item['groups']
            face_ids = item['face_ids']

            if object_type == ObjectType.SOLID.value or object_type == ObjectType.SHEET.value:
                obj = None
                if plasticity_id not in self.files[filename][PlasticityIdUniquenessScope.ITEM]:
                    mesh = self.__create_mesh(
                        name, verts, faces, normals, groups, face_ids)
                    obj = self.__add_object(filename, object_type,
                                            plasticity_id, name, mesh)
                    obj.scale = (prop_plasticity_unit_scale,
                                 prop_plasticity_unit_scale, prop_plasticity_unit_scale)
                else:
                    obj = self.files[filename][PlasticityIdUniquenessScope.ITEM].get(
                        plasticity_id)
                    if obj:
                        self.__update_object_and_mesh(
                            obj, object_type, version, name, verts, faces, normals, groups, face_ids)
                        for parent in obj.users_collection:
                            parent.objects.unlink(obj)

            elif object_type == ObjectType.GROUP.value:
                if plasticity_id > 0:
                    group_collection = None
                    if plasticity_id not in self.files[filename][PlasticityIdUniquenessScope.GROUP]:
                        group_collection = bpy.data.collections.new(name)
                        group_collection["plasticity_id"] = plasticity_id
                        group_collection["plasticity_filename"] = filename
                        self.files[filename][PlasticityIdUniquenessScope.GROUP][plasticity_id] = group_collection
                    else:
                        group_collection = self.files[filename][PlasticityIdUniquenessScope.GROUP].get(
                            plasticity_id)
                        group_collection.name = name
                        collections_to_unlink.add(group_collection)


        # Unlink all mirrored collections, in case they have moved. It doesn't seem like there is a more efficient way to do this??
        for potential_parent in bpy.data.collections:
            to_unlink = [
                child for child in potential_parent.children if child in collections_to_unlink]
            for child in to_unlink:
                potential_parent.children.unlink(child)

        for item in objects:
            object_type = item['type']
            uniqueness_scope = PlasticityIdUniquenessScope.ITEM if object_type != ObjectType.GROUP.value else PlasticityIdUniquenessScope.GROUP
            plasticity_id = item['id']
            parent_id = item['parent_id']
            flags = item['flags']
            is_hidden = flags & 1
            is_visible = flags & 2
            is_selectable = flags & 4

            if plasticity_id == 0:  # root group
                continue

            obj = self.files[filename][uniqueness_scope].get(
                plasticity_id)
            if not obj:
                self.report(
                    {'ERROR'}, "Object of type {} with id {} and parent_id {} not found".format(
                        object_type, plasticity_id, parent_id))
                continue

            parent = inbox_collection if parent_id == 0 else self.files[filename][PlasticityIdUniquenessScope.GROUP].get(
                parent_id)
            if not parent:
                self.report(
                    {'ERROR'}, "Parent of object of type {} with id {} and parent_id {} not found".format(
                        object_type, plasticity_id, parent_id))
                continue

            if object_type == ObjectType.GROUP.value:
                parent.children.link(obj)
                group_collection.hide_viewport = is_hidden or not is_visible
                group_collection.hide_select = not is_selectable
            else:
                parent.objects.link(obj)
                obj.hide_set(is_hidden or not is_visible)
                obj.hide_select = not is_selectable

    def __inbox_for_filename(self, filename):
        plasticity_collection = bpy.data.collections.get("Plasticity")
        if not plasticity_collection:
            plasticity_collection = bpy.data.collections.new("Plasticity")
            bpy.context.scene.collection.children.link(plasticity_collection)

        filename_collection = plasticity_collection.children.get(filename)
        if not filename_collection:
            filename_collection = bpy.data.collections.new(filename)
            plasticity_collection.children.link(filename_collection)

        inbox_collections = [
            child for child in filename_collection.children if "inbox" in child]
        inbox_collection = None
        if len(inbox_collections) > 0:
            inbox_collection = inbox_collections[0]
        if not inbox_collection:
            inbox_collection = bpy.data.collections.new("Inbox")
            filename_collection.children.link(inbox_collection)
            inbox_collection["inbox"] = True
        return inbox_collection

    def __prepare(self, filename):
        inbox_collection = self.__inbox_for_filename(filename)

        def gather_items(collection):
            objects = list(collection.objects)
            collections = list(collection.children)
            for sub_collection in collection.children:
                subobjects, subcollections = gather_items(sub_collection)
                objects.extend(subobjects)
                collections.extend(subcollections)
            return objects, collections
        objects, collections = gather_items(inbox_collection)

        existing_objects = {
            PlasticityIdUniquenessScope.ITEM: {},
            PlasticityIdUniquenessScope.GROUP: {}
        }
        for obj in objects:
            if "plasticity_id" not in obj:
                continue
            plasticity_filename = obj.get("plasticity_filename")
            plasticity_id = obj.get("plasticity_id")
            if plasticity_id:
                existing_objects[PlasticityIdUniquenessScope.ITEM][plasticity_id] = obj
        for collection in collections:
            if "plasticity_id" not in collection:
                continue
            plasticity_id = collection.get("plasticity_id")
            if plasticity_id:
                existing_objects[PlasticityIdUniquenessScope.GROUP][plasticity_id] = collection

        self.files[filename] = existing_objects

        return inbox_collection

    def on_transaction(self, transaction):
        bpy.context.window_manager.plasticity_busy = False
        filename = transaction["filename"]
        version = transaction["version"]
        # Mark incoming Live Link data so Live Refacet can react to real updates.
        try:
            from . import operators
            operators.note_live_link_update(filename)
        except Exception:
            pass

        self.report({'INFO'}, "Updating " + filename +
                    " to version " + str(version))
        bpy.ops.ed.undo_push(message="Plasticity update")

        inbox_collection = self.__prepare(filename)

        if "delete" in transaction:
            for plasticity_id in transaction["delete"]:
                self.__delete_object(filename, version, plasticity_id)

        if "add" in transaction:
            self.__replace_objects(filename, inbox_collection,
                                   version, transaction["add"])

        if "update" in transaction:
            self.__replace_objects(filename, inbox_collection,
                                   version, transaction["update"])

        bpy.ops.ed.undo_push(message="/Plasticity update")

    def on_list(self, message):
        bpy.context.window_manager.plasticity_busy = False
        filename = message["filename"]
        version = message["version"]

        self.report({'INFO'}, "Updating " + filename +
                    " to version " + str(version))
        bpy.ops.ed.undo_push(message="Plasticity update")

        inbox_collection = self.__prepare(filename)

        filter_ids = self.list_filter_ids
        selected_only = bool(filter_ids)
        if filter_ids:
            filter_ids = set(filter_ids)

        add_items = message.get("add", [])
        update_items = message.get("update", [])

        all_items = set()
        all_groups = set()
        for item in add_items + update_items:
            if item["type"] == ObjectType.GROUP.value:
                all_groups.add(item["id"])
            else:
                all_items.add(item["id"])

        if selected_only:
            filtered_add = [
                item for item in add_items
                if item["type"] == ObjectType.GROUP.value or item["id"] in filter_ids
            ]
            filtered_update = [
                item for item in update_items
                if item["type"] == ObjectType.GROUP.value or item["id"] in filter_ids
            ]
        else:
            filtered_add = add_items
            filtered_update = update_items

        if filtered_add:
            self.__replace_objects(filename, inbox_collection,
                                   version, filtered_add)
        if filtered_update:
            self.__replace_objects(filename, inbox_collection,
                                   version, filtered_update)

        if selected_only:
            for plasticity_id in filter_ids:
                if plasticity_id not in all_items:
                    self.__delete_object(filename, version, plasticity_id)
        else:
            to_delete = []
            for plasticity_id, obj in self.files[filename][PlasticityIdUniquenessScope.ITEM].items():
                if plasticity_id not in all_items:
                    to_delete.append(plasticity_id)
            for plasticity_id in to_delete:
                self.__delete_object(filename, version, plasticity_id)

            to_delete = []
            for plasticity_id, obj in self.files[filename][PlasticityIdUniquenessScope.GROUP].items():
                if plasticity_id not in all_groups:
                    to_delete.append(plasticity_id)
            for plasticity_id in to_delete:
                self.__delete_group(filename, version, plasticity_id)

        bpy.ops.ed.undo_push(message="/Plasticity update")
        self.list_filter_ids = None

    def on_refacet(self, filename, version, plasticity_ids, versions, faces, positions, indices, normals, groups, face_ids):
        bpy.context.window_manager.plasticity_busy = False
        self.report({'INFO'}, "Refaceting " + filename +
                    " to version " + str(version))
        bpy.ops.ed.undo_push(message="Plasticity refacet")

        self.__prepare(filename)

        prev_obj_mode = bpy.context.object.mode if bpy.context.object else None
        prev_active_object = bpy.context.view_layer.objects.active
        prev_selected_objects = bpy.context.selected_objects

        total = len(plasticity_ids)
        if total:
            self._update_status_text(
                f"Progress: 0% (Refacet 0/{total})",
                force=True,
            )
        try:
            for i in range(len(plasticity_ids)):
                plasticity_id = plasticity_ids[i]
                version = versions[i]
                face = faces[i] if len(faces) > 0 else None
                position = positions[i]
                index = indices[i]
                normal = normals[i]
                group = groups[i]
                face_id = face_ids[i]

                obj = self.files[filename][PlasticityIdUniquenessScope.ITEM].get(
                    plasticity_id)
                if obj:
                    self.__update_mesh_ngons(
                        obj, version, face, position, index, normal, group, face_id)
                if total:
                    percent = int(((i + 1) / total) * 100)
                    self._update_status_text(
                        f"Progress: {percent}% (Refacet {i + 1}/{total})",
                    )
        finally:
            if total:
                self._update_status_text(None, force=True)

        bpy.context.view_layer.objects.active = prev_active_object
        for obj in prev_selected_objects:
            obj.select_set(True)
        if prev_obj_mode:
            bpy.ops.object.mode_set(mode=prev_obj_mode)

        bpy.ops.ed.undo_push(message="/Plasticity refacet")

    def on_new_version(self, filename, version):
        bpy.context.window_manager.plasticity_busy = False
        self.report({'INFO'}, "New version of " +
                    filename + " available: " + str(version))

    def on_new_file(self, filename):
        bpy.context.window_manager.plasticity_busy = False
        self.report({'INFO'}, "New file available: " + filename)

    def on_connect(self):
        bpy.context.window_manager.plasticity_busy = False
        self.files = {}

    def on_disconnect(self):
        bpy.context.window_manager.plasticity_busy = False
        self.files = {}

    def report(self, level, message):
        print(message)

    def _update_status_text(self, text, force=False):
        workspace = bpy.context.workspace
        if not workspace:
            return
        if text is None:
            force = True
        now = time.monotonic()
        last_time = self._last_status_time
        last_text = self._last_status_text
        min_interval = self._status_min_interval
        if not force:
            if text == last_text:
                return
            if (now - last_time) < min_interval:
                return
        should_redraw = force or (now - last_time) >= min_interval
        self._last_status_time = now
        self._last_status_text = text
        workspace.status_text_set(text)
        if should_redraw:
            try:
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
            except Exception:
                pass


_PLASTICITY_LOOP_INDEX_ATTR = "_plasticity_loop_index_tmp"
_PLASTICITY_FACE_ID_ATTR = "_plasticity_face_id_tmp"


def _group_index_mode_for_mesh(groups, mesh):
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


def _build_loop_face_ids(mesh, groups, face_ids):
    if not groups or not face_ids:
        return []
    loop_count = len(mesh.loops)
    if loop_count == 0:
        return []
    loop_face_ids = [-1] * loop_count
    group_count = min(len(groups) // 2, len(face_ids))
    mode = _group_index_mode_for_mesh(groups, mesh)

    if mode == "faces":
        face_count = len(mesh.polygons)
        for group_idx in range(group_count):
            start = int(groups[group_idx * 2])
            count = int(groups[group_idx * 2 + 1])
            if count <= 0 or start < 0:
                continue
            end = min(start + count, face_count)
            face_id = int(face_ids[group_idx])
            for face_index in range(start, end):
                poly = mesh.polygons[face_index]
                loop_start = poly.loop_start
                loop_end = loop_start + poly.loop_total
                for loop_index in range(loop_start, loop_end):
                    loop_face_ids[loop_index] = face_id
    else:
        for group_idx in range(group_count):
            start = int(groups[group_idx * 2])
            count = int(groups[group_idx * 2 + 1])
            if count <= 0 or start < 0:
                continue
            end = min(start + count, loop_count)
            face_id = int(face_ids[group_idx])
            for loop_index in range(start, end):
                loop_face_ids[loop_index] = face_id

    return loop_face_ids


def _normalize_loop_face_ids(mesh, loop_face_ids):
    if not loop_face_ids:
        return
    for poly in mesh.polygons:
        loop_start = poly.loop_start
        loop_end = loop_start + poly.loop_total
        counts = {}
        for loop_index in range(loop_start, loop_end):
            face_id = loop_face_ids[loop_index]
            if face_id is None or face_id < 0:
                continue
            counts[face_id] = counts.get(face_id, 0) + 1
        if not counts:
            continue
        dominant_id = max(counts.items(), key=lambda item: item[1])[0]
        for loop_index in range(loop_start, loop_end):
            loop_face_ids[loop_index] = dominant_id


def _compress_loop_face_ids(loop_face_ids):
    groups_out = []
    face_ids_out = []
    current_id = None
    start = 0
    count = 0
    for loop_index, face_id in enumerate(loop_face_ids):
        if face_id is None or face_id < 0:
            if current_id is not None:
                groups_out.extend([start, count])
                face_ids_out.append(current_id)
                current_id = None
                count = 0
            continue
        if current_id is None:
            current_id = face_id
            start = loop_index
            count = 1
        elif face_id == current_id:
            count += 1
        else:
            groups_out.extend([start, count])
            face_ids_out.append(current_id)
            current_id = face_id
            start = loop_index
            count = 1

    if current_id is not None:
        groups_out.extend([start, count])
        face_ids_out.append(current_id)

    return groups_out, face_ids_out


def _ensure_loop_index_attribute(mesh, indices):
    loop_count = len(mesh.loops)
    if loop_count == 0:
        return None
    if _PLASTICITY_LOOP_INDEX_ATTR in mesh.attributes:
        mesh.attributes.remove(mesh.attributes[_PLASTICITY_LOOP_INDEX_ATTR])
    attr = mesh.attributes.new(_PLASTICITY_LOOP_INDEX_ATTR, 'INT', 'CORNER')
    if len(indices) == loop_count:
        attr.data.foreach_set("value", indices)
    else:
        loop_indices = np.empty(loop_count, dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", loop_indices)
        attr.data.foreach_set("value", loop_indices)
    return _PLASTICITY_LOOP_INDEX_ATTR


def _ensure_face_id_attribute(mesh, groups, face_ids):
    loop_face_ids = _build_loop_face_ids(mesh, groups, face_ids)
    if not loop_face_ids:
        return None
    if _PLASTICITY_FACE_ID_ATTR in mesh.attributes:
        mesh.attributes.remove(mesh.attributes[_PLASTICITY_FACE_ID_ATTR])
    attr = mesh.attributes.new(_PLASTICITY_FACE_ID_ATTR, 'INT', 'CORNER')
    attr.data.foreach_set("value", loop_face_ids)
    return _PLASTICITY_FACE_ID_ATTR


def _rebuild_groups_from_face_id_attribute(mesh, attr_name):
    attr = mesh.attributes.get(attr_name)
    if not attr:
        return [], []
    loop_count = len(mesh.loops)
    if loop_count == 0:
        return [], []
    loop_face_ids = np.empty(loop_count, dtype=np.int32)
    attr.data.foreach_get("value", loop_face_ids)
    loop_face_ids = loop_face_ids.tolist()
    _normalize_loop_face_ids(mesh, loop_face_ids)
    return _compress_loop_face_ids(loop_face_ids)


def _cleanup_temp_attributes(mesh, attr_names):
    for name in attr_names:
        if not name:
            continue
        attr = mesh.attributes.get(name)
        if attr:
            mesh.attributes.remove(attr)


def _apply_plasticity_groups_and_normals(mesh, indices, normals, groups, face_ids):
    face_attr = _ensure_face_id_attribute(mesh, groups, face_ids)
    loop_index_attr = None
    if face_attr:
        loop_index_attr = _ensure_loop_index_attribute(mesh, indices)
        mesh.validate(clean_customdata=False)
        groups, face_ids = _rebuild_groups_from_face_id_attribute(
            mesh, face_attr)

    mesh["groups"] = groups
    mesh["face_ids"] = face_ids
    mesh["plasticity_groups_version"] = int(mesh.get("plasticity_groups_version", 0)) + 1
    mesh["plasticity_seams_version"] = int(mesh.get("plasticity_seams_version", 0)) + 1
    safe_loop_normals(mesh, indices, normals)
    _cleanup_temp_attributes(mesh, [face_attr, loop_index_attr])


def safe_loop_normals(mesh, indices, normals):
    if "temp_custom_normals" in mesh.attributes:
        mesh.attributes.remove(mesh.attributes["temp_custom_normals"])
    if normals is None or len(mesh.loops) == 0:
        return
    normals_array = normals.reshape(-1, 3)
    loop_count = len(mesh.loops)

    loop_indices = None
    attr = mesh.attributes.get(_PLASTICITY_LOOP_INDEX_ATTR)
    if attr and attr.domain == 'CORNER':
        loop_indices = np.empty(loop_count, dtype=np.int32)
        attr.data.foreach_get("value", loop_indices)
    elif len(indices) == loop_count:
        loop_indices = np.asarray(indices, dtype=np.int32)
    else:
        loop_indices = np.empty(loop_count, dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", loop_indices)

    mesh.attributes.new("temp_custom_normals", 'FLOAT_VECTOR', 'CORNER')
    mesh.attributes["temp_custom_normals"].data.foreach_set(
        "vector", normals_array[loop_indices].ravel())

    mesh.validate(clean_customdata=False)

    buf = np.empty(len(mesh.loops) * 3, dtype=np.float32)
    mesh.attributes["temp_custom_normals"].data.foreach_get("vector", buf)

    mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))

    mesh.normals_split_custom_set(buf.reshape(-1, 3))
    mesh.attributes.remove(mesh.attributes["temp_custom_normals"])

    mesh.update()
