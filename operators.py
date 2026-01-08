import math
import mathutils
import random

import bmesh
import bpy


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
        default=True,
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

        # Collect group IDs of all selected faces
        selected_group_ids = get_selected_group_ids(groups, bm)

        if self.select_adjacent_fillets and selected_group_ids:
            group_faces, face_to_group, group_areas, group_max_angles = build_group_data(
                groups, mesh, bm)
            edge_adjacency = build_group_adjacency(
                bm, face_to_group, len(group_faces))
            if self.include_vertex_adjacency:
                vertex_adjacency = build_group_vertex_adjacency(
                    bm, face_to_group, len(group_faces))
                adjacency = [
                    edge_adjacency[i] | vertex_adjacency[i]
                    for i in range(len(edge_adjacency))
                ]
            else:
                adjacency = edge_adjacency

            base_group_indices = {group_id // 2 for group_id in selected_group_ids}
            candidate_group_indices = set()
            for group_idx in base_group_indices:
                if group_idx < len(adjacency):
                    candidate_group_indices.update(adjacency[group_idx])
            candidate_group_indices.difference_update(base_group_indices)

            fillet_group_ids = set()
            for group_idx in candidate_group_indices:
                if is_fillet_group(
                    group_idx,
                    group_areas,
                    group_max_angles,
                    adjacency,
                    self.fillet_min_curvature_angle,
                    self.fillet_max_area_ratio,
                    self.fillet_min_adjacent_groups,
                ):
                    fillet_group_ids.add(group_idx * 2)

            selected_group_ids.update(fillet_group_ids)

        # Select all faces belonging to any of the selected group IDs
        for face in bm.faces:
            loop_start = face.loops[0].index
            for group_id in selected_group_ids:
                group_start = groups[group_id + 0]
                group_count = groups[group_id + 1]
                if loop_start >= group_start and loop_start < group_start + group_count:
                    face.select = True
                    break

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

        selected_group_ids = get_selected_group_ids(groups, bm)
        boundary_edges = get_boundary_edges_for_group_ids(
            groups, bm, selected_group_ids)

        # Unselect the faces in selected_group_ids
        for face in bm.faces:
            loop_start = face.loops[0].index
            for group_id in selected_group_ids:
                group_start = groups[group_id + 0]
                group_count = groups[group_id + 1]
                if loop_start >= group_start and loop_start < group_start + group_count:
                    face.select = False
                    break

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
        bpy.ops.mesh.select_linked(delimit={'SEAM'})
        bpy.ops.mesh.mark_seam(clear=True)
        bpy.ops.mesh.region_to_loop()
        bpy.ops.mesh.mark_seam(clear=False)
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.mesh.select_mode(
            use_extend=False, use_expand=False, type='FACE')

        return {'FINISHED'}


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
            selected_group_ids = get_selected_group_ids(groups, bm)
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
            mesh["groups"], bm, selected_group_ids)

        for edge in boundary_edges:
            if self.mark_sharp:
                edge.smooth = False
            if self.mark_seam:
                edge.seam = True

        bmesh.update_edit_mesh(mesh)

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


def face_boundary_edges(groups, mesh, bm):
    all_face_boundary_edges = set()
    face_boundary_edges = set()

    group_idx = 0
    group_start = groups[group_idx * 2 + 0]
    group_count = groups[group_idx * 2 + 1]
    face_boundary_edges = set()

    for poly in mesh.polygons:
        loop_start = poly.loop_start
        if loop_start >= group_start + group_count:
            all_face_boundary_edges.update(face_boundary_edges)
            group_idx += 1
            group_start = groups[group_idx * 2 + 0]
            group_count = groups[group_idx * 2 + 1]
            face_boundary_edges = set()

        face = bm.faces[poly.index]
        for edge in face.edges:
            if edge in face_boundary_edges:
                face_boundary_edges.remove(edge)
            else:
                face_boundary_edges.add(edge)
    all_face_boundary_edges.update(face_boundary_edges)

    return all_face_boundary_edges


def get_boundary_edges_for_group_ids(groups, bm, selected_group_ids):
    boundary_edges = set()
    for face in bm.faces:
        loop_start = face.loops[0].index
        for group_id in selected_group_ids:
            group_start = groups[group_id + 0]
            group_count = groups[group_id + 1]
            if loop_start >= group_start and loop_start < group_start + group_count:
                for edge in face.edges:
                    if edge in boundary_edges:
                        boundary_edges.remove(edge)
                    else:
                        boundary_edges.add(edge)
                break
    return boundary_edges


def get_selected_group_ids(groups, bm):
    selected_group_ids = set()
    for face in bm.faces:
        if face.select:
            loop_idx = face.loops[0].index
            for i in range(0, len(groups), 2):
                group_start = groups[i + 0]
                group_count = groups[i + 1]
                if loop_idx >= group_start and loop_idx < group_start + group_count:
                    selected_group_ids.add(i)
                    break
    return selected_group_ids


def build_group_data(groups, mesh, bm):
    group_count = len(groups) // 2
    group_faces = [[] for _ in range(group_count)]
    face_to_group = {}
    group_areas = [0.0 for _ in range(group_count)]
    group_normal_sums = [
        mathutils.Vector((0.0, 0.0, 0.0)) for _ in range(group_count)
    ]

    bm.faces.ensure_lookup_table()
    bm.normal_update()

    group_idx = 0
    group_start = groups[group_idx * 2 + 0]
    group_loop_count = groups[group_idx * 2 + 1]

    for poly in mesh.polygons:
        loop_start = poly.loop_start
        while loop_start >= group_start + group_loop_count and group_idx < group_count - 1:
            group_idx += 1
            group_start = groups[group_idx * 2 + 0]
            group_loop_count = groups[group_idx * 2 + 1]

        face = bm.faces[poly.index]
        group_faces[group_idx].append(face)
        face_to_group[face.index] = group_idx
        group_areas[group_idx] += face.calc_area()
        group_normal_sums[group_idx] += face.normal

    group_max_angles = [0.0 for _ in range(group_count)]
    for group_idx, faces in enumerate(group_faces):
        normal_sum = group_normal_sums[group_idx]
        if normal_sum.length_squared > 0.0:
            avg_normal = normal_sum.normalized()
        else:
            avg_normal = mathutils.Vector((0.0, 0.0, 1.0))

        max_angle = 0.0
        for face in faces:
            dot = max(-1.0, min(1.0, avg_normal.dot(face.normal)))
            angle = math.degrees(math.acos(dot))
            if angle > max_angle:
                max_angle = angle
        group_max_angles[group_idx] = max_angle

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

        if context.selected_objects:
            for obj in context.selected_objects:
                if obj.type == 'MESH':
                    context.view_layer.objects.active = obj
                    bpy.ops.object.mode_set(mode='EDIT')
                    bpy.ops.mesh.select_all(action='SELECT')

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
