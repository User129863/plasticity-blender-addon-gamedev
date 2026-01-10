# plasticity-blender-addon-gamedev

GameDev-focused fork of the Plasticity Blender bridge. Builds on upstream and adds workflow tools for fast real-time asset prep (topology/edge control, UV workflow, and export-oriented utilities).

## Upstreamed into the official add-on workflow

These features were developed in this fork first and were later upstreamed, so they are part of the official Plasticity Blender add-on workflow:

- AutoMarkEdgesOperator: consolidates "Mark Sharp" and "Mark Sharp at boundaries" into a single operator with modes to mark selection as Hard Edges (Sharp) or UV Seams (Seam).
- Smart edge marking (Sharp/Seam): operates on entire-mesh selections (not individually selected polygons inside a Plasticity group) and applies edge marking using the same boundary logic as MarkSharpEdgesForPlasticityGroupsWithSplitNormalsOperator.
- Arbitrary group-polygon boundary marking (Sharp/Seam): allows selecting polygons belonging to Plasticity surface groups and marking their selection boundary (instead of only marking boundaries of individual Plasticity surfaces).
- UV seam merge from arbitrary group selections: merges existing UV seams based on an arbitrary polygon selection within Plasticity groups.
- Plasticity group edge selection: utilities to select edges corresponding to Plasticity group boundaries.

This fork continues beyond upstream and adds additional GameDev-focused workflow changes, targeting real-time asset preparation (game-ready topology/edge control, UV workflow, and export-oriented tooling).

## New features in this fork

- Fillet-aware selection in Select Plasticity Face(s): optional adjacent-fillet mode expands selection by curvature/area thresholds; vertex adjacency helps bridge tight corners; setting Min Curvature Angle to 0 includes chamfers.
- Refacet presets for game-ready topology control: save per-object remesh parameters to control mesh density and edge/silhouette fidelity, useful for consistent edge control and poly-budget management on CAD-derived meshes.
- Refacet UI quality of life: Tri/Ngon stored in presets; simple Tolerance/Angle fields always visible; Advanced is a pure toggle for extra settings.
- Refresh filtering: new toggles for "Only selected objects in Blender" and "Only visible in Plasticity"; enable either or both to constrain refresh to selected Blender objects, visible Plasticity items, or their intersection.
- UI reorganization: compact, collapsible sections to reduce panel height and speed scanning during production.
- Select Similar Geometry: fuzzy match by vertex/poly counts and total surface area relative to the active object; ignores transforms/materials. Useful for quickly grabbing similar meshes; approximate and may include false positives.
- Join Selected: join selected objects into the active object. Destructive.
- Unjoin Selected: separate selected meshes by loose parts; creates new objects and may change names.
- Select Meshes with Ngons: scan the scene and select meshes that contain ngons (>4 vertices).
- Mirror Selected: duplicate and mirror selected objects around the chosen axis and center; uses the 3D cursor pivot temporarily.
- Remove Modifiers: remove all modifiers from selected objects. Destructive.
- Apply Modifiers: apply all modifiers on selected objects; destructive and may change topology.
- Remove Vertex Groups: remove all vertex groups from selected mesh objects. Destructive.
- Merge Non-overlapping Meshes: supports selection-only vs visible objects, with threshold exposed in the redo panel; optimized overlap checks (AABB fast reject + KDTree distance checks, name-based resolution to avoid stale refs); useful for batching and for baking workflows that use bevel-shader techniques, but can increase bake times in Blender.
- UV workflow tools: open/close UV editor, select meshes without UVs, remove UVs, and material/texture cleanup grouped together.
- Import/export utilities: FBX and OBJ import/export with modern operator support and legacy fallback.







