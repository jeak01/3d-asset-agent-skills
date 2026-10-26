# Adapting a downloaded SimReady asset

## Inputs and inspection

Use `download-manifest.json` for the pinned source, declared license, file integrity results and entry USD paths. Read `ATTRIBUTION.md` as a draft: fill in any supplied creator or attribution notices and retain the original license file. The script does not prove that copyright, trademark or other rights are cleared.

Determine the output: rendered illustration, editable model, game asset, printable solid or simulation asset. These have different requirements. A visually similar asset can be useful without being suitable for fabrication or physics.

In the selected application, inspect:

- Actual dimensions and stage units; up axis and transforms.
- Hierarchy, instances, linked data and whether parts can be edited separately.
- Mesh quality, normals, UVs, polygon count and material/texture resolution.
- Missing layers, references, payloads and textures, including paths outside the package.
- Collision meshes, rigid-body settings, joints and semantic labels when simulation matters.

## Blender path

For Scenario resources, read [scenario.md](scenario.md). Select the actual GLB/Blender/other entry format instead of assuming USD. Open `.blend` with automatic script execution disabled. Preserve the required Scenario attribution and visually check style; these examples do not declare SimReady physics readiness.

Use an existing Blender MCP connection when available, otherwise a locally installed executable. Discover its version instead of guessing paths or claiming a tool exists. Do not install Blender just to complete a handoff.

Blender's USD importer can convert supported USD Preview Surface materials to Principled BSDF, but conversion is lossy. Omniverse MDL graphs and simulation schemas may need reconstruction or an Omniverse/Isaac workflow. Check the imported appearance before editing.

Work in a derivative `.blend` project outside the immutable downloaded folder. Import, inspect the actual hierarchy and render before issuing object-specific edits. Do not assume mesh names, material slots or wheel hierarchies exist.

For “make it sci-fi,” specify concrete edits such as panels, wheel guards, lighting, tool racks or new materials, and identify retained parts. Rebuild only what the request calls for. Preserve useful UVs and make copied mesh/material data single-user before changing an instance independently.

## Verification and delivery

Render before and after views from comparable cameras. Inspect changes, silhouette, shading and missing textures. Open or re-import the export to check scale, orientation, materials and target-format support.

For simulation, use the intended runtime and relevant SimReady profile to revalidate physics and metadata after editing. Do not call an untested derivative certified or simulation-ready.

Deliver the working project, requested export, preview renders, source/version attribution, and a short description of changes and limitations. If only a handoff was created, say so explicitly.

References:

- https://docs.blender.org/manual/en/latest/files/import_export/usd.html
- https://docs.omniverse.nvidia.com/simready/latest/simready-central.html
- https://github.com/NVIDIA/simready-foundation
- https://creativecommons.org/licenses/by/4.0/
