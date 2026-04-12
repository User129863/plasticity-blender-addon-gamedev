# TODO:
# - [ ] All on_... methods should call operators (to better handle undo, to have reporting be visible in the ui, etc)
from collections import defaultdict
from enum import Enum
import time

import bpy
import mathutils
import numpy as np


_PIVOT_IMPORT_BASIS_KEY = "plasticity_blender_import_basis_matrix"
_PIVOT_PIVOT_BASIS_KEY = "plasticity_blender_pivot_basis_matrix"
_PIVOT_TRANSFORM_BASIS_KEY = "plasticity_blender_transform_basis_matrix"
_PIVOT_COMPENSATION_KEY = "plasticity_blender_pivot_compensation_matrix"
_PIVOT_MATRIX_EPS = 1.0e-6
_PIVOT_CORNER_EPS = 1.0e-4
_PIVOT_MODE_PLASTICITY = "PLASTICITY"
_PIVOT_MODE_BLENDER = "BLENDER"


def _is_plasticity_mesh_object(obj):
    try:
        return obj is not None and obj.type == 'MESH' and "plasticity_id" in obj.keys()
    except Exception:
        return False


def _matrix_to_list(matrix):
    return [float(value) for row in matrix for value in row]


def _matrix_from_list(values):
    if values is None:
        return None
    try:
        flat = [float(value) for value in values]
    except Exception:
        return None
    if len(flat) != 16:
        return None
    return mathutils.Matrix((
        flat[0:4],
        flat[4:8],
        flat[8:12],
        flat[12:16],
    ))


def _get_matrix_property(obj, key):
    try:
        return _matrix_from_list(obj.get(key))
    except Exception:
        return None


def _set_matrix_property(obj, key, matrix, eps=_PIVOT_MATRIX_EPS):
    current = _get_matrix_property(obj, key)
    if current is not None and _matrices_close(current, matrix, eps=eps):
        return False
    obj[key] = _matrix_to_list(matrix)
    return True


def _matrices_close(left, right, eps=_PIVOT_MATRIX_EPS):
    if left is None or right is None:
        return False
    for row_index in range(4):
        for col_index in range(4):
            if abs(float(left[row_index][col_index]) - float(right[row_index][col_index])) > eps:
                return False
    return True


def _points_close(left, right, eps=_PIVOT_CORNER_EPS):
    if left is None or right is None:
        return False
    if len(left) != len(right):
        return False
    for left_point, right_point in zip(left, right):
        if len(left_point) != len(right_point):
            return False
        for left_value, right_value in zip(left_point, right_point):
            if abs(float(left_value) - float(right_value)) > eps:
                return False
    return True


def _scale_only_basis(obj):
    basis = mathutils.Matrix.Identity(4)
    scale = getattr(obj, "scale", (1.0, 1.0, 1.0))
    basis[0][0] = float(scale[0])
    basis[1][1] = float(scale[1])
    basis[2][2] = float(scale[2])
    return basis


def _transform_vertices(verts, matrix):
    verts_array = np.asarray(verts, dtype=np.float32)
    if verts_array.size == 0:
        return verts_array
    verts_array = verts_array.reshape(-1, 3)
    rotation = np.asarray(matrix.to_3x3(), dtype=np.float32)
    translation = np.asarray(matrix.to_translation(), dtype=np.float32)
    transformed = verts_array @ rotation.T
    transformed += translation
    return transformed.reshape(-1)


def _transform_normals(normals, matrix):
    if normals is None:
        return None
    normals_array = np.asarray(normals, dtype=np.float32)
    if normals_array.size == 0:
        return normals_array
    normals_array = normals_array.reshape(-1, 3)
    rotation = np.asarray(matrix.to_quaternion().to_matrix(), dtype=np.float32)
    rotated = normals_array @ rotation.T
    lengths = np.linalg.norm(rotated, axis=1)
    valid = lengths > 1.0e-8
    if np.any(valid):
        rotated[valid] /= lengths[valid][:, None]
    return rotated.reshape(-1)


def _bbox_center_from_flat_verts(verts):
    verts_array = np.asarray(verts, dtype=np.float32)
    if verts_array.size == 0:
        return mathutils.Vector((0.0, 0.0, 0.0))
    verts_array = verts_array.reshape(-1, 3)
    min_corner = verts_array.min(axis=0)
    max_corner = verts_array.max(axis=0)
    return mathutils.Vector((
        float((min_corner[0] + max_corner[0]) * 0.5),
        float((min_corner[1] + max_corner[1]) * 0.5),
        float((min_corner[2] + max_corner[2]) * 0.5),
    ))


def _bbox_center_from_object(obj):
    try:
        corners = tuple(obj.bound_box)
    except Exception:
        corners = ()
    if not corners:
        return mathutils.Vector((0.0, 0.0, 0.0))
    total = mathutils.Vector((0.0, 0.0, 0.0))
    count = 0
    for corner in corners:
        try:
            total += mathutils.Vector((float(corner[0]), float(corner[1]), float(corner[2])))
            count += 1
        except Exception:
            continue
    if count == 0:
        return mathutils.Vector((0.0, 0.0, 0.0))
    return total / count


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
        self.list_only_new = False
        self._status_min_interval = 1.0
        self._last_status_time = 0.0
        self._last_status_text = None
        self._pivot_objects = {}
        self._pivot_mesh_users = defaultdict(set)
        self._pivot_object_mesh = {}
        self._pivot_last_snapshot = {}
        self._pivot_pending_snapshot = {}
        self._pivot_suppressed = set()

    def __coerce_plasticity_id_set(self, values):
        ids = set()
        if values is None:
            return ids
        for value in values:
            try:
                ids.add(int(value))
            except Exception:
                continue
        return ids

    def __mesh_item_ids(self, items):
        ids = set()
        if not items:
            return ids
        for item in items:
            try:
                object_type = item.get("type")
                if object_type not in {ObjectType.SOLID.value, ObjectType.SHEET.value}:
                    continue
                plasticity_id = item.get("id")
                if plasticity_id is None:
                    continue
                ids.add(int(plasticity_id))
            except Exception:
                continue
        return ids

    def __filter_list_items_only_new(self, filename, add_items, update_items):
        ordered_items = list(add_items) + list(update_items)
        if not ordered_items:
            return [], set()

        existing_item_ids = set(
            self.files[filename][PlasticityIdUniquenessScope.ITEM].keys()
        )
        existing_group_ids = set(
            self.files[filename][PlasticityIdUniquenessScope.GROUP].keys()
        )

        group_items = {}
        for item in ordered_items:
            if item.get("type") != ObjectType.GROUP.value:
                continue
            plasticity_id = item.get("id")
            if plasticity_id is None:
                continue
            group_items[plasticity_id] = item

        new_mesh_ids = set()
        required_group_ids = set()
        mesh_types = {ObjectType.SOLID.value, ObjectType.SHEET.value}
        for item in ordered_items:
            if item.get("type") not in mesh_types:
                continue
            plasticity_id = item.get("id")
            if plasticity_id is None or plasticity_id in existing_item_ids:
                continue

            new_mesh_ids.add(plasticity_id)
            parent_id = item.get("parent_id", 0)
            while parent_id:
                if parent_id in existing_group_ids or parent_id in required_group_ids:
                    break
                parent_item = group_items.get(parent_id)
                if not parent_item:
                    break
                required_group_ids.add(parent_id)
                parent_id = parent_item.get("parent_id", 0)

        filtered_items = []
        for item in ordered_items:
            object_type = item.get("type")
            plasticity_id = item.get("id")
            if object_type == ObjectType.GROUP.value:
                if plasticity_id in required_group_ids:
                    filtered_items.append(item)
            elif object_type in mesh_types:
                if plasticity_id in new_mesh_ids:
                    filtered_items.append(item)

        return filtered_items, new_mesh_ids

    def __pivot_clear_runtime(self):
        self._pivot_objects = {}
        self._pivot_mesh_users = defaultdict(set)
        self._pivot_object_mesh = {}
        self._pivot_last_snapshot = {}
        self._pivot_pending_snapshot = {}
        self._pivot_suppressed = set()

    def __pivot_suppress_object(self, obj):
        if not _is_plasticity_mesh_object(obj):
            return
        try:
            self._pivot_suppressed.add(obj.as_pointer())
        except Exception:
            pass

    def __pivot_untrack_object(self, obj_or_ptr):
        try:
            obj_ptr = int(obj_or_ptr)
        except Exception:
            try:
                obj_ptr = obj_or_ptr.as_pointer()
            except Exception:
                return
        self._pivot_objects.pop(obj_ptr, None)
        self._pivot_last_snapshot.pop(obj_ptr, None)
        self._pivot_pending_snapshot.pop(obj_ptr, None)
        self._pivot_suppressed.discard(obj_ptr)
        mesh_ptr = self._pivot_object_mesh.pop(obj_ptr, None)
        if mesh_ptr is None:
            return
        users = self._pivot_mesh_users.get(mesh_ptr)
        if not users:
            return
        users.discard(obj_ptr)
        if not users:
            self._pivot_mesh_users.pop(mesh_ptr, None)

    def __pivot_snapshot(self, obj):
        basis = obj.matrix_basis.copy()
        local_corners = []
        world_corners = []
        matrix_world = obj.matrix_world.copy()
        try:
            bound_box = tuple(obj.bound_box)
        except Exception:
            bound_box = ()
        for corner in bound_box:
            try:
                local = mathutils.Vector((float(corner[0]), float(corner[1]), float(corner[2])))
            except Exception:
                continue
            world = matrix_world @ local
            local_corners.append((float(local.x), float(local.y), float(local.z)))
            world_corners.append((float(world.x), float(world.y), float(world.z)))
        return {
            "basis": basis,
            "local_corners": tuple(local_corners),
            "world_corners": tuple(world_corners),
        }

    def __pivot_track_object(self, obj, snapshot=None):
        if not _is_plasticity_mesh_object(obj):
            self.__pivot_untrack_object(obj)
            return
        obj_ptr = obj.as_pointer()
        self._pivot_objects[obj_ptr] = obj
        if snapshot is None:
            snapshot = self.__pivot_snapshot(obj)
        self._pivot_last_snapshot[obj_ptr] = snapshot
        previous_mesh_ptr = self._pivot_object_mesh.get(obj_ptr)
        mesh = getattr(obj, "data", None)
        mesh_ptr = mesh.as_pointer() if mesh is not None else None
        if previous_mesh_ptr and previous_mesh_ptr != mesh_ptr:
            users = self._pivot_mesh_users.get(previous_mesh_ptr)
            if users:
                users.discard(obj_ptr)
                if not users:
                    self._pivot_mesh_users.pop(previous_mesh_ptr, None)
        if mesh_ptr is None:
            self._pivot_object_mesh.pop(obj_ptr, None)
            return
        self._pivot_object_mesh[obj_ptr] = mesh_ptr
        self._pivot_mesh_users[mesh_ptr].add(obj_ptr)

    def __pivot_apply_snapshot_delta(self, obj, previous_snapshot, current_snapshot=None, scene=None):
        import_basis, _, _, current_compensation = self.__pivot_ensure_state(obj)
        if import_basis is None or previous_snapshot is None:
            return False
        if current_snapshot is None:
            current_snapshot = self.__pivot_snapshot(obj)
        previous_basis = previous_snapshot.get("basis")
        current_basis_snapshot = current_snapshot.get("basis")
        if previous_basis is None or current_basis_snapshot is None:
            return False
        basis_changed = not _matrices_close(previous_basis, current_basis_snapshot)
        if not basis_changed:
            return False
        local_changed = not _points_close(
            previous_snapshot.get("local_corners"),
            current_snapshot.get("local_corners"),
        )
        world_same = _points_close(
            previous_snapshot.get("world_corners"),
            current_snapshot.get("world_corners"),
        )
        pivot_mode, transform_mode = self.__pivot_scene_modes(scene)
        current_basis = self.__pivot_current_basis(obj)
        previous_world_basis = previous_basis @ current_compensation
        if local_changed and world_same:
            updated_compensation = current_basis.inverted_safe() @ previous_world_basis
            _set_matrix_property(obj, _PIVOT_COMPENSATION_KEY, updated_compensation)
            if pivot_mode == _PIVOT_MODE_BLENDER:
                _set_matrix_property(obj, _PIVOT_PIVOT_BASIS_KEY, current_basis)
            return True
        if not local_changed and not world_same:
            if transform_mode == _PIVOT_MODE_BLENDER:
                updated_transform_basis = current_basis @ current_compensation
                _set_matrix_property(obj, _PIVOT_TRANSFORM_BASIS_KEY, updated_transform_basis)
            return True
        return False

    def __pivot_resolve_pending_state(self, obj, current_snapshot=None, scene=None):
        try:
            obj_ptr = obj.as_pointer()
        except Exception:
            return False
        pending_snapshot = self._pivot_pending_snapshot.get(obj_ptr)
        if pending_snapshot is None:
            return False
        if current_snapshot is None:
            current_snapshot = self.__pivot_snapshot(obj)
        if (
            _matrices_close(pending_snapshot.get("basis"), current_snapshot.get("basis"))
            and _points_close(pending_snapshot.get("local_corners"), current_snapshot.get("local_corners"))
            and _points_close(pending_snapshot.get("world_corners"), current_snapshot.get("world_corners"))
        ):
            self._pivot_pending_snapshot.pop(obj_ptr, None)
            return False
        if self.__pivot_apply_snapshot_delta(obj, pending_snapshot, current_snapshot=current_snapshot, scene=scene):
            self._pivot_pending_snapshot.pop(obj_ptr, None)
            return True
        return False

    def __pivot_scene_modes(self, scene=None):
        if scene is None:
            scene = getattr(bpy.context, "scene", None)
        mode = getattr(scene, "prop_plasticity_object_transform_control_mode", _PIVOT_MODE_PLASTICITY)
        return mode, mode

    def __pivot_current_basis(self, obj):
        return obj.matrix_basis.copy()

    def __pivot_current_local_compensation(self, obj):
        compensation = _get_matrix_property(obj, _PIVOT_COMPENSATION_KEY)
        if compensation is None:
            return mathutils.Matrix.Identity(4)
        return compensation

    def __pivot_capture_current_state(self, obj, capture_pivot=False, capture_transform=False):
        if not _is_plasticity_mesh_object(obj):
            return None
        import_basis, _, _, current_compensation = self.__pivot_ensure_state(obj)
        if import_basis is None:
            return None
        current_basis = self.__pivot_current_basis(obj)
        current_world_basis = current_basis @ current_compensation
        if capture_pivot:
            target_world_basis = current_world_basis if capture_transform else import_basis
            compensation = current_basis.inverted_safe() @ target_world_basis
            _set_matrix_property(obj, _PIVOT_IMPORT_BASIS_KEY, import_basis)
            _set_matrix_property(obj, _PIVOT_PIVOT_BASIS_KEY, current_basis)
            _set_matrix_property(obj, _PIVOT_COMPENSATION_KEY, compensation)
        if capture_transform:
            _set_matrix_property(obj, _PIVOT_TRANSFORM_BASIS_KEY, current_basis)
        self._pivot_pending_snapshot.pop(obj.as_pointer(), None)
        return import_basis

    def __pivot_capture_scene_state(self, scene=None, capture_pivot=False, capture_transform=False):
        if scene is None:
            scene = getattr(bpy.context, "scene", None)
        if scene is None:
            return
        for obj in scene.objects:
            if not _is_plasticity_mesh_object(obj):
                continue
            import_basis = self.__pivot_capture_current_state(
                obj,
                capture_pivot=capture_pivot,
                capture_transform=capture_transform,
            )
            if import_basis is None:
                continue
            self.__pivot_track_object(obj)

    def __pivot_ensure_state(self, obj):
        if not _is_plasticity_mesh_object(obj):
            return None, None, None, None
        import_basis = _get_matrix_property(obj, _PIVOT_IMPORT_BASIS_KEY)
        if import_basis is None:
            import_basis = _scale_only_basis(obj)
            _set_matrix_property(obj, _PIVOT_IMPORT_BASIS_KEY, import_basis)
        pivot_basis = _get_matrix_property(obj, _PIVOT_PIVOT_BASIS_KEY)
        if pivot_basis is None:
            pivot_basis = self.__pivot_current_basis(obj)
            _set_matrix_property(obj, _PIVOT_PIVOT_BASIS_KEY, pivot_basis)
        transform_basis = _get_matrix_property(obj, _PIVOT_TRANSFORM_BASIS_KEY)
        if transform_basis is None:
            transform_basis = import_basis.copy()
            _set_matrix_property(obj, _PIVOT_TRANSFORM_BASIS_KEY, transform_basis)
        compensation = _get_matrix_property(obj, _PIVOT_COMPENSATION_KEY)
        if compensation is None:
            compensation = mathutils.Matrix.Identity(4)
            _set_matrix_property(obj, _PIVOT_COMPENSATION_KEY, compensation)
        return import_basis, pivot_basis, transform_basis, compensation

    def __pivot_effective_state(self, obj, scene=None):
        import_basis, pivot_basis, transform_basis, current_compensation = self.__pivot_ensure_state(obj)
        if import_basis is None:
            identity = mathutils.Matrix.Identity(4)
            return identity, identity, identity, identity, current_compensation
        pivot_mode, transform_mode = self.__pivot_scene_modes(scene)
        effective_world_basis = transform_basis if transform_mode == _PIVOT_MODE_BLENDER else import_basis
        effective_object_basis = pivot_basis if pivot_mode == _PIVOT_MODE_BLENDER else import_basis
        if pivot_mode == _PIVOT_MODE_BLENDER and transform_mode == _PIVOT_MODE_BLENDER:
            effective_object_basis = transform_basis
            effective_local_compensation = current_compensation
            effective_world_basis = effective_object_basis
        elif pivot_mode == _PIVOT_MODE_BLENDER:
            effective_local_compensation = effective_object_basis.inverted_safe() @ effective_world_basis
        else:
            effective_local_compensation = import_basis.inverted_safe() @ effective_world_basis
        return (
            import_basis,
            effective_world_basis,
            effective_object_basis,
            effective_local_compensation,
            current_compensation,
        )

    def __pivot_prepare_import_geometry(self, obj, verts, normals, scene=None):
        _, _, _, compensation, _ = self.__pivot_effective_state(obj, scene)
        pivot_mode, transform_mode = self.__pivot_scene_modes(scene)
        if pivot_mode == _PIVOT_MODE_BLENDER and transform_mode == _PIVOT_MODE_BLENDER:
            current_local_center = _bbox_center_from_object(obj)
            import_local_center = _bbox_center_from_flat_verts(verts)
            rotation_only = compensation.to_quaternion().to_matrix()
            rotated_import_center = rotation_only @ import_local_center
            compensation = compensation.copy()
            compensation[0][3] = float(current_local_center.x - rotated_import_center.x)
            compensation[1][3] = float(current_local_center.y - rotated_import_center.y)
            compensation[2][3] = float(current_local_center.z - rotated_import_center.z)
        transformed_verts = _transform_vertices(verts, compensation)
        transformed_normals = _transform_normals(normals, compensation)
        return transformed_verts, transformed_normals, compensation

    def __pivot_apply_rebuild_state(self, obj, scene=None, compensation=None):
        _, _, effective_object_basis, effective_local_compensation, _ = self.__pivot_effective_state(obj, scene)
        if compensation is None:
            compensation = effective_local_compensation
        obj.matrix_basis = effective_object_basis
        _set_matrix_property(obj, _PIVOT_COMPENSATION_KEY, compensation)

    def capture_current_pivot_state(self, scene=None):
        self.__pivot_capture_scene_state(scene=scene, capture_pivot=True, capture_transform=False)

    def capture_current_transform_state(self, scene=None):
        self.__pivot_capture_scene_state(scene=scene, capture_pivot=False, capture_transform=True)

    def capture_current_transform_control_state(self, scene=None):
        self.__pivot_capture_scene_state(scene=scene, capture_pivot=True, capture_transform=True)

    def bootstrap_pivot_state(self, scene=None):
        if scene is None:
            scene = getattr(bpy.context, "scene", None)
        self.__pivot_clear_runtime()
        if scene is None:
            return
        pivot_mode, transform_mode = self.__pivot_scene_modes(scene)
        capture_pivot = pivot_mode == _PIVOT_MODE_BLENDER
        capture_transform = transform_mode == _PIVOT_MODE_BLENDER
        for obj in scene.objects:
            if not _is_plasticity_mesh_object(obj):
                continue
            self.__pivot_ensure_state(obj)
            if capture_pivot or capture_transform:
                import_basis = self.__pivot_capture_current_state(
                    obj,
                    capture_pivot=capture_pivot,
                    capture_transform=capture_transform,
                )
                if import_basis is None:
                    continue
            self.__pivot_track_object(obj)

    def process_pivot_depsgraph_updates(self, depsgraph):
        updates = getattr(depsgraph, "updates", None)
        if not updates:
            return

        changed_objects = {}

        for update in updates:
            id_data = getattr(update, "id", None)
            if isinstance(id_data, bpy.types.Object):
                obj = id_data
                if not _is_plasticity_mesh_object(obj):
                    continue
                obj_ptr = obj.as_pointer()
                changed_objects[obj_ptr] = obj
            elif isinstance(id_data, bpy.types.Mesh):
                mesh_ptr = id_data.as_pointer()
                for obj_ptr in tuple(self._pivot_mesh_users.get(mesh_ptr, ())):
                    obj = self._pivot_objects.get(obj_ptr)
                    if obj is None:
                        self.__pivot_untrack_object(obj_ptr)
                        continue
                    try:
                        if not _is_plasticity_mesh_object(obj):
                            self.__pivot_untrack_object(obj_ptr)
                            continue
                        if obj.data != id_data:
                            self.__pivot_track_object(obj)
                            if obj.data != id_data:
                                continue
                    except ReferenceError:
                        self.__pivot_untrack_object(obj_ptr)
                        continue
                    changed_objects[obj_ptr] = obj

        allow_capture = getattr(bpy.context, "mode", None) == 'OBJECT'
        scene = getattr(bpy.context, "scene", None)
        for obj_ptr, obj in changed_objects.items():
            try:
                import_basis, _, _, current_compensation = self.__pivot_ensure_state(obj)
                current_snapshot = self.__pivot_snapshot(obj)
            except ReferenceError:
                self.__pivot_untrack_object(obj_ptr)
                continue

            previous_snapshot = self._pivot_last_snapshot.get(obj_ptr)
            if obj_ptr in self._pivot_suppressed:
                self._pivot_suppressed.discard(obj_ptr)
                if previous_snapshot is not None:
                    suppressed_unchanged = (
                        _matrices_close(previous_snapshot.get("basis"), current_snapshot.get("basis"))
                        and _points_close(previous_snapshot.get("local_corners"), current_snapshot.get("local_corners"))
                        and _points_close(previous_snapshot.get("world_corners"), current_snapshot.get("world_corners"))
                    )
                    if suppressed_unchanged:
                        self.__pivot_track_object(obj, snapshot=current_snapshot)
                        continue

            if allow_capture and self.__pivot_resolve_pending_state(obj, current_snapshot=current_snapshot, scene=scene):
                self.__pivot_track_object(obj, snapshot=current_snapshot)
                continue

            basis_changed = False
            local_changed = False
            world_same = False
            if previous_snapshot is not None:
                basis_changed = not _matrices_close(previous_snapshot.get("basis"), current_snapshot.get("basis"))
                local_changed = not _points_close(
                    previous_snapshot.get("local_corners"),
                    current_snapshot.get("local_corners"),
                )
                world_same = _points_close(
                    previous_snapshot.get("world_corners"),
                    current_snapshot.get("world_corners"),
                )

            if allow_capture and previous_snapshot is not None and import_basis is not None and basis_changed:
                if local_changed and world_same:
                    self.__pivot_apply_snapshot_delta(obj, previous_snapshot, current_snapshot=current_snapshot, scene=scene)
                    self._pivot_pending_snapshot.pop(obj_ptr, None)
                elif not local_changed and not world_same:
                    self._pivot_pending_snapshot.setdefault(obj_ptr, previous_snapshot)

            self.__pivot_track_object(obj, snapshot=current_snapshot)

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
        scene = getattr(bpy.context, "scene", None)
        pivot_mode, transform_mode = self.__pivot_scene_modes(scene)
        capture_pivot = pivot_mode == _PIVOT_MODE_BLENDER
        capture_transform = transform_mode == _PIVOT_MODE_BLENDER
        if capture_pivot and capture_transform:
            self.__pivot_resolve_pending_state(obj, scene=scene)
            self.__pivot_capture_current_state(
                obj,
                capture_pivot=False,
                capture_transform=True,
            )
        elif capture_pivot or capture_transform:
            self.__pivot_capture_current_state(
                obj,
                capture_pivot=capture_pivot,
                capture_transform=capture_transform,
            )
        else:
            self.__pivot_resolve_pending_state(obj, scene=scene)
        self.__pivot_suppress_object(obj)
        verts, normals, compensation = self.__pivot_prepare_import_geometry(obj, verts, normals, scene=scene)

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

        self.__pivot_apply_rebuild_state(obj, compensation=compensation)
        self.update_pivot(obj)
        self.__pivot_track_object(obj)

    def __update_mesh_ngons(self, obj, version, faces, verts, indices, normals, groups, face_ids):
        if obj.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')

        scene = getattr(bpy.context, "scene", None)
        pivot_mode, transform_mode = self.__pivot_scene_modes(scene)
        capture_pivot = pivot_mode == _PIVOT_MODE_BLENDER
        capture_transform = transform_mode == _PIVOT_MODE_BLENDER
        if capture_pivot and capture_transform:
            self.__pivot_resolve_pending_state(obj, scene=scene)
            self.__pivot_capture_current_state(
                obj,
                capture_pivot=False,
                capture_transform=True,
            )
        elif capture_pivot or capture_transform:
            self.__pivot_capture_current_state(
                obj,
                capture_pivot=capture_pivot,
                capture_transform=capture_transform,
            )
        else:
            self.__pivot_resolve_pending_state(obj, scene=scene)
        self.__pivot_suppress_object(obj)
        verts, normals, compensation = self.__pivot_prepare_import_geometry(obj, verts, normals, scene=scene)
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

        self.__pivot_apply_rebuild_state(obj, compensation=compensation)
        self.update_pivot(obj)
        self.__pivot_track_object(obj)

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
        self.__pivot_suppress_object(mesh_obj)
        return mesh_obj

    def __delete_object(self, filename, version, plasticity_id):
        obj = self.files[filename][PlasticityIdUniquenessScope.ITEM].pop(
            plasticity_id, None)
        if obj:
            self.__pivot_untrack_object(obj)
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
                    self.__pivot_ensure_state(obj)
                    self.__pivot_track_object(obj)
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
        changed_ids = self.__mesh_item_ids(transaction.get("add", []))
        changed_ids.update(self.__mesh_item_ids(transaction.get("update", [])))
        # Mark incoming Live Link data so Live Refacet can react to real updates.
        try:
            from . import operators
            operators.note_live_link_update(filename, changed_ids=changed_ids)
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

        try:
            from . import operators
            operators.reset_live_uv_runtime_state(scene=bpy.context.scene, filename=filename)
            operators.apply_live_paint_faces(
                scene=bpy.context.scene,
                filename=filename,
                force=True,
                target_ids=changed_ids,
            )
        except Exception:
            pass

        bpy.ops.ed.undo_push(message="/Plasticity update")

    def on_list(self, message):
        bpy.context.window_manager.plasticity_busy = False
        try:
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

            if self.list_only_new:
                filtered_items, changed_ids = self.__filter_list_items_only_new(
                    filename,
                    add_items,
                    update_items,
                )
                try:
                    from . import operators
                    operators.note_live_link_update(filename, changed_ids=changed_ids)
                except Exception:
                    pass

                if filtered_items:
                    self.__replace_objects(filename, inbox_collection,
                                           version, filtered_items)
            else:
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

                changed_ids = self.__mesh_item_ids(filtered_add)
                changed_ids.update(self.__mesh_item_ids(filtered_update))
                try:
                    from . import operators
                    operators.note_live_link_update(filename, changed_ids=changed_ids)
                except Exception:
                    pass

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

            try:
                from . import operators
                operators.reset_live_uv_runtime_state(scene=bpy.context.scene, filename=filename)
                operators.apply_live_paint_faces(
                    scene=bpy.context.scene,
                    filename=filename,
                    force=True,
                    target_ids=changed_ids,
                )
            except Exception:
                pass

            bpy.ops.ed.undo_push(message="/Plasticity update")
        finally:
            self.list_filter_ids = None
            self.list_only_new = False

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

        changed_ids = self.__coerce_plasticity_id_set(plasticity_ids)
        try:
            from . import operators
            operators.reset_live_uv_runtime_state(scene=bpy.context.scene, filename=filename)
            operators.apply_live_paint_faces(
                scene=bpy.context.scene,
                filename=filename,
                force=True,
                target_ids=changed_ids,
            )
        except Exception:
            pass

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
        self.list_filter_ids = None
        self.list_only_new = False
        self.bootstrap_pivot_state(getattr(bpy.context, "scene", None))

    def on_disconnect(self):
        bpy.context.window_manager.plasticity_busy = False
        self.files = {}
        self.list_filter_ids = None
        self.list_only_new = False

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
