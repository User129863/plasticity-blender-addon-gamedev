# plasticity-blender-addon-gamedev


<a href="https://buymeacoffee.com/User129863">
  <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" width="200">
</a>

<p>
  <a href="https://www.youtube.com/watch?v=Bk0S0jZEzRM">
    <img src="https://img.youtube.com/vi/Bk0S0jZEzRM/hqdefault.jpg" alt="Watch on YouTube">
  </a><br>
  Gamepad Model by: <a href="https://www.youtube.com/@Kuechmeister">Kuechmeister Swagger</a>
</p>


## GameDev-focused fork of the Plasticity Blender Bridge.
Unofficial fork that regularly incorporates the latest improvements from the official Plasticity Blender add-on, and adds workflow tools for fast real-time asset prep: topology/edge control, UV workflow utilities, and export-oriented helpers.

## Upstreamed into the official add-on workflow

The following features were first developed in this fork and have since been upstreamed, so they’re part of the official Plasticity Blender add-on:
- AutoMarkEdgesOperator: consolidates “Mark Sharp” and “Mark Sharp at boundaries” into a single operator, with modes for marking Hard Edges (Sharp) or UV Seams (Seam).
- Smart edge marking (Sharp/Seam): operates on whole-mesh selections (rather than per-polygon selection inside a Plasticity group) and applies the same boundary logic as MarkSharpEdgesForPlasticityGroupsWithSplitNormalsOperator.
- Arbitrary group-boundary marking (Sharp/Seam): allows selecting polygons within Plasticity surface groups and marking the selection boundary (not only per-surface boundaries).
- UV seam merge from arbitrary group selections: merges existing UV seams based on an arbitrary polygon selection inside Plasticity groups.
- Plasticity group edge selection: utilities to select edges corresponding to Plasticity group boundaries.

This fork continues beyond what has been upstreamed, adding additional game-dev workflow improvements aimed at real-time asset preparation (game-ready topology/edge control, UV workflow, and export tooling).

## Version 1.0 features

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
- Merge Non-overlapping Meshes: supports selection-only vs visible objects, with threshold exposed in the redo panel; optimized overlap checks (AABB fast reject + KDTree distance checks, name-based resolution to avoid stale refs); useful for batching and for baking workflows that use bevel-shader techniques, decreases bake times in Blender.
- UV workflow tools: open/close UV editor, select meshes without UVs, remove UVs, and material/texture cleanup grouped together.
- Import/export utilities: FBX and OBJ import/export with modern operator support and legacy fallback.

## Version 1.1 updates

Latest workflow updates focused on multi-object UV tools, improved overlays, and a more streamlined checker texture workflow.

- Live Expand Selection (multi-object): this is a live paint-select workflow for Plasticity faces. While Live Expand is enabled, you can circle-select faces and the tool continuously expands the selection to full Plasticity face groups (with optional adjacent-fillet expansion) across all selected edit-mode objects. When Live Unwrap 3D is on, the UV unwrap updates immediately as you paint, so selection, seam changes (Auto Merge + Auto Cylinder if enabled), and UV layout become a single continuous pass instead of separate steps.
- Merge UV Seams (multi-object): merge operations now run across all selected edit-mode objects instead of only the active object.
- Plasticity Edge Highlight: optional overlay highlighting for Plasticity edges with active-view-only, occlusion, thickness, and color controls.
- Relax UVs (multi-object): relax now operates on any selected faces across multiple edit-mode objects (requires Blender 4.3+).
- UV editor open/close: opening the UV editor no longer forces a select-all pass, so selections are preserved and auto-merge seams will not be unintentionally triggered.
- Checker textures workflow: bundled checker library with preview grid and default selection (UVChecker-color-1024x1024), plus custom file selection via path picker.

## Version 1.2 updates

Major UI refactor: Replaced the previous dense single-panel layout with a tabbed workflow to reduce visual overload and make operator groups easier to navigate:
- Pinned
- Main
- Refacet
- Utilities
- UV / Material / Texture Tools
- Mesh Tools
- Preferences

New: Pinned workflow: Added a dedicated Pinned tab for quick access to frequently used controls/operators, with:
- Improved default pinned set for common workflows
- Expanded pin coverage across key tools

Auto Merge / Reset Seams on Selection: Renamed for clarity and updated behavior/tooltip:
- Single click: resets seams on the targeted Plasticity face
- Click + drag: continuously merges/resets as selection changes

Selection-driven seam automation: Auto seam merge/reset no longer depends on Live Expand or Auto Circle and now works reliably with standard selection workflows.

Multi-object seam reliability: Merge seams and auto create seam modes (including cylinder and sphere paths) now behave consistently across multiple selected Edit Mode objects.

Multi-object Relax UVs reliability: Relax now applies correctly across selected faces on multiple selected Edit Mode objects and is more stable after repeated seam + unwrap operations.

New: Pack UV Islands operator: Added under UV / Material / Texture Tools -> Unwrap for pack-only workflows (no unwrap). Defaults:
- Average Islands Scale: ON
- Rotate Islands: OFF

Preferences tab: Added a dedicated place for global behavior options, including Auto Assign Checker on Selection.

Add-on metadata update: Updated bl_info for the fork:
- Plasticity Blender Addon Gamedev
- Version: 1.2.0
- Updated fork description
- Minimum Blender: 4.3+

## Version 1.2.2 Updates

- Improved Live Refacet behavior with Live Link workflows.
- Live Refacet now supports Live Link-aware targeting logic.
- Live Link updates target updated Plasticity objects.
- Reduced unnecessary repaint/refacet work in larger Live Link scenes.
- Live Paint / Paint Plasticity Faces: Added new Live Paint mode controls for Paint Plasticity Faces.
- Live Paint / Paint Plasticity Faces: Live Paint options for Paint Plasticity Faces.
- Live Paint / Paint Plasticity Faces: Paint mode (Material + Attribute / Attribute Only).
- Live Paint / Paint Plasticity Faces: Custom color attribute name.
- Live Paint / Paint Plasticity Faces: Live Paint toggle to auto-refresh Plasticity face colors.
- Live Paint / Paint Plasticity Faces: Face color attribute creation now uses BYTE_COLOR.
- Live Paint / Paint Plasticity Faces: Face painting colors aren't random anymore.
- Multiple UV workflow stability fixes for Blender 5.x.
- Fixed UV seam/unwrap/relax interactions causing texel density drift in Blender 5.x workflows.
- Fixed cases where relaxed UV changes contaminated adjacent non-target surfaces.
- Blender 5.x behavior handling improved in UV and Live Refacet paths.

## Version 1.2.3 updates

- New (Experimental): Live Expand `Auto Select Cylinders` for faster cylindrical surface selection workflows.
- New (Experimental): `Cylinder Min Wrap Angle` setting to tune cylinder auto-selection sensitivity.
- Live Expand Selection: when Live Expand mode is ON, hold Ctrl while using Circle Select, Auto Circle Select Mode, or Box/Rectangle selection to unselect Plasticity surfaces.
- General bug fixes and stability improvements.

https://github.com/user-attachments/assets/2dd4efb0-cb47-4379-9c01-1dccc4edc275

## Version 1.2.4 updates

- Added a new FBX option in Preferences: users with the Better FBX add-on can select it for both FBX import and export.
- Merge Seams fixes when multiple objects are selected.
- General bug fixes and stability improvements.


