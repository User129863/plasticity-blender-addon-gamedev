<div align="center">

# Plasticity Blender Add-on for Game Development

**A production-focused Plasticity-to-Blender bridge for turning CAD models into game-ready assets.**

[![Version](https://img.shields.io/badge/version-1.3.2-2ea44f)](#release-notes)
[![Blender](https://img.shields.io/badge/Blender-4.3%2B-E87D0D?logo=blender&logoColor=white)](#requirements)
[![License](https://img.shields.io/badge/license-MIT-0969da)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/User129863/plasticity-blender-addon-gamedev?logo=github)](https://github.com/User129863/plasticity-blender-addon-gamedev/stargazers)

[Features](#features) | [Installation](#installation) | [Quick workflow](#quick-workflow) | [Release notes](#release-notes) | [Support](#support)

<a href="https://www.youtube.com/watch?v=Bk0S0jZEzRM">
  <img src="https://img.youtube.com/vi/Bk0S0jZEzRM/hqdefault.jpg" width="720" alt="Plasticity Blender GameDev add-on workflow demonstration">
</a>

<sub>Click the image to watch the workflow. Gamepad model by <a href="https://www.youtube.com/@Kuechmeister">Kuechmeister Swagger</a>.</sub>

</div>

> [!IMPORTANT]
> This is an unofficial, community-maintained fork of the [Plasticity Blender add-on](https://github.com/nkallen/plasticity-blender-addon). It is not affiliated with or supported by Plasticity. Disable other builds of the Plasticity Blender add-on before enabling this fork to avoid duplicate operators and panels.

Keep Plasticity as the source of truth for your CAD model while Blender handles topology decisions, UVs, scene assembly, and export. This fork follows improvements from the official bridge and adds tools designed for rapid iteration on real-time assets.

## Features

| Workflow | Highlights |
| --- | --- |
| **Live Plasticity bridge** | Connect, refresh, subscribe, and refacet without rebuilding the Blender scene by hand. Filter refreshes by selected Blender objects, visible Plasticity objects, or newly created Plasticity objects. |
| **Game-ready refacet control** | Store per-object refacet presets, tune silhouette and mesh density, choose Tri/Ngon output, and use Live Refacet during active bridge sessions. |
| **Surface-aware selection** | Expand selections to complete Plasticity face groups, include adjacent fillets, detect cylindrical surfaces, and paint selections across multiple edit-mode objects. |
| **Hard edges and UV seams** | Mark Plasticity group boundaries as sharp edges or seams, merge/reset seams from arbitrary face selections, and highlight Plasticity edges in the viewport. |
| **Multi-object UV workflow** | Live unwrap while selecting, automatic cylinder and sphere seam modes, multi-object seam merging and relaxing, pack-only tools, UV diagnostics, and bundled checker textures. |
| **Mesh preparation** | Find similar geometry or ngon meshes, join/unjoin loose parts, mirror objects, manage modifiers and vertex groups, and merge non-overlapping meshes for faster baking workflows. |
| **Interchange** | Import and export FBX/OBJ, optionally use Better FBX, and send SubD cage meshes from Blender back to Plasticity through the PolySpline workflow. |
| **Production-friendly UI** | A tabbed sidebar with Pinned, Main, Refacet, Utilities, UV Tools, Mesh Tools, and Preferences views. Frequently used controls can be pinned for faster access. |

## Installation

1. Download the repository using **Code > Download ZIP**, or use the [direct ZIP download](https://github.com/User129863/plasticity-blender-addon-gamedev/archive/refs/heads/main.zip).
2. In Blender, open **Edit > Preferences > Add-ons**.
3. Open the Add-ons menu, choose **Install from Disk**, and select the downloaded ZIP file.
4. Search for **Plasticity Blender Addon Gamedev** and enable it.
5. Open the 3D Viewport sidebar with `N`, then select the **Plasticity GameDev** tab.

> [!NOTE]
> Blender does not automatically enable a legacy add-on after installation. If the panel is missing, confirm that the add-on is enabled and restart Blender once.

## Requirements

| Requirement | Details |
| --- | --- |
| **Blender** | 4.3 or newer |
| **Plasticity** | A Plasticity edition with Blender Bridge access |
| **Bridge address** | `localhost:8980` by default |
| **Optional** | Better FBX Importer & Exporter for Blender |

## Quick workflow

1. Open your model in Plasticity and start its Blender Bridge server.
2. In Blender, open **3D Viewport > Sidebar > Plasticity GameDev**.
3. Keep the default `localhost:8980` address and click **Connect**.
4. Use **Refresh** to bring Plasticity objects into Blender, then enable subscriptions or Live Refacet when you want continuing updates.
5. Prepare the asset with surface selection, edge marking, UV, mesh, and export tools from the workflow tabs.

## See it in action

### Live surface selection

Live Expand turns ordinary circle and box selection into a multi-object Plasticity surface workflow. Automatic cylinder detection can expand across cylindrical side surfaces while excluding caps and fillets.

https://github.com/user-attachments/assets/2dd4efb0-cb47-4379-9c01-1dccc4edc275

### Preserve Blender transforms during refresh

Plasticity Object Transform Control can preserve Blender-edited pivots, positions, and rotations through refacet and refresh operations, making assembly work practical directly in Blender.

https://github.com/user-attachments/assets/bed96ba8-e440-4f40-ba1c-5b3c95cbf68b

### Send SubD cages back to Plasticity

Version 1.3.2 adds a Blender-to-Plasticity PolySpline workflow with multi-object sending, optional automatic Subdivision Surface modifiers, loose-parts separation, and exposed PolySpline options.

https://github.com/user-attachments/assets/6e29f8ec-b462-414b-9091-e373f7d5f232

## What this fork contributed upstream

Several workflows were developed here first and later incorporated into the official Plasticity Blender add-on:

- A unified **Auto Mark Edges** operator for hard edges and UV seams.
- Surface-group boundary detection across arbitrary polygon selections.
- Smart sharp/seam marking for selections spanning complete meshes.
- UV seam merging from arbitrary Plasticity group selections.
- Utilities for selecting Plasticity group boundary edges.

This fork continues beyond those upstream contributions with game-development-specific refacet, UV, mesh preparation, and interchange tools.

## Release notes

<details open>
<summary><strong>Version 1.3.2</strong> - Blender-to-Plasticity PolySpline workflow</summary>

- Added **Send to Plasticity** for meshes with a Subdivision Surface modifier.
- Added optional automatic SubD modifier creation.
- Added Rounded Corners, Merge Patches, and Interpolate Boundary Exactly options.
- Added multi-object sending and automatic loose-parts separation.

</details>

<details>
<summary><strong>Version 1.3.1</strong> - New-object refresh filtering</summary>

- Added **Only new objects in Plasticity** to Refresh.
- Existing imported objects can now remain untouched while new Plasticity objects are brought into Blender.

</details>

<details>
<summary><strong>Version 1.3</strong> - Transform preservation</summary>

- Added Plasticity Object Transform Control under Mesh Tools.
- Blender can preserve locally edited pivots, positions, and rotations through refacet and refresh operations.
- Included general bug fixes and stability improvements.

</details>

<details>
<summary><strong>Version 1.2.4</strong> - FBX and seam reliability</summary>

- Added optional Better FBX support for import and export.
- Fixed Merge Seams behavior when multiple objects are selected.
- Included general bug fixes and stability improvements.

</details>

<details>
<summary><strong>Version 1.2.3</strong> - Cylinder-aware live selection</summary>

- Added experimental automatic cylinder selection to Live Expand.
- Added Cylinder Min Wrap Angle for selection sensitivity.
- Added `Ctrl`-drag deselection for circle, automatic circle, and box selection workflows.

</details>

<details>
<summary><strong>Version 1.2.2</strong> - Live Refacet and Blender 5.x stability</summary>

- Improved Live Refacet targeting and reduced unnecessary work in larger Live Link scenes.
- Added face-painting modes, custom color attributes, and live face-color refresh.
- Improved UV seam, unwrap, and relax behavior in Blender 5.x.

</details>

<details>
<summary><strong>Version 1.2</strong> - Tabbed workflow UI</summary>

- Reorganized the add-on into focused workflow tabs with pinnable tools.
- Decoupled automatic seam merge/reset from Live Expand and Auto Circle.
- Improved multi-object seam creation and UV relaxation.
- Added Pack UV Islands and checker-assignment preferences.
- Raised the minimum supported Blender version to 4.3.

</details>

<details>
<summary><strong>Version 1.1</strong> - Multi-object UV tools</summary>

- Added Live Expand Selection with optional adjacent-fillet selection.
- Added live 3D unwrap updates while painting selections.
- Added multi-object seam merging and UV relaxation.
- Added Plasticity edge highlighting and a checker-texture library.

</details>

<details>
<summary><strong>Version 1.0</strong> - GameDev toolset</summary>

- Added fillet-aware Plasticity face selection and refacet presets.
- Added selected/visible refresh filters and a compact production UI.
- Added geometry selection, join/unjoin, ngon detection, mirroring, modifier, vertex-group, and merge utilities.
- Added UV cleanup plus FBX and OBJ import/export helpers.

</details>

## Support

- Use [GitHub Issues](https://github.com/User129863/plasticity-blender-addon-gamedev/issues) for reproducible bugs and feature requests.
- Include your Blender version, Plasticity version, add-on version, and exact reproduction steps.

<a href="https://buymeacoffee.com/User129863">
  <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" width="180">
</a>

## Credits

- Original Plasticity Blender bridge by [Nick Kallen](https://github.com/nkallen).
- GameDev fork maintained by [User129863](https://github.com/User129863).
- Demo gamepad model by [Kuechmeister Swagger](https://www.youtube.com/@Kuechmeister).
- Transform workflow demo model by Yann Goument.

## License

Licensed under the [MIT License](LICENSE).
