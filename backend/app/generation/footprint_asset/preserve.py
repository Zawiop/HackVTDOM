"""Restyle existing architectural geometry; never replace it with an extrusion."""
import copy
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
import trimesh

from ..scorch_material import scorch_surface


def topology_report(mesh):
    """Weld UV seams on a COPY so seams are not mistaken for missing faces."""
    welded = trimesh.Trimesh(mesh.vertices.copy(), mesh.faces.copy(), process=False)
    welded.merge_vertices()
    welded.remove_unreferenced_vertices()
    counts = np.bincount(welded.edges_unique_inverse)
    return {"boundary_edges": int(np.sum(counts == 1)),
            "nonmanifold_edges": int(np.sum(counts > 2)),
            "watertight": bool(welded.is_watertight),
            "degenerate_faces": int(np.sum(mesh.area_faces <= 1e-12))}


def restyle_existing_asset(source_mesh_path, output_path, *, strength=.65,
                           require_closed=True, max_size_mb=3., dimensions_m=None, height_m=None,
                           metadata_height_m=None, allow_height_distortion=False):
    """Keep source local vertices, faces and UVs; optionally apply a metric fit.

    Input must already have correct orientation. Without metric dimensions its
    scale and transforms are unchanged. With width/depth dimensions, X and Y use
    the SAME scale to preserve front elevation proportions; depth is fitted
    independently. Metadata height is reported, never silently imposed on a
    source with a conflicting silhouette. An explicit height override that
    changes facade aspect by over 20% requires allow_height_distortion=True.
    A source mesh is
    necessary: a single photo and footprint do not specify original roof/towers.
    Open body meshes fail with diagnostics, rather than being silently called
    complete. Entrance overlays are exempt from closed-solid checks. No holes are
    invented or blindly capped; intentional courtyards are preserved.
    """
    source, output = Path(source_mesh_path), Path(output_path)
    if source.resolve() == output.resolve():
        raise ValueError("Write to a different path to retain the original asset")
    if output.suffix.lower() != '.glb':
        raise ValueError("output_path must end in .glb")
    scene = trimesh.load(source, force='scene', process=False)
    if not scene.geometry:
        raise ValueError("Source contains no geometry")
    source_bounds = scene.bounds.copy()
    source_extents = source_bounds[1]-source_bounds[0]
    if not np.isfinite(source_extents).all() or min(source_extents) <= 0:
        raise ValueError("Source must have finite, positive width, height and depth")
    if metadata_height_m is not None:
        metadata_height_m = float(metadata_height_m)
        if not np.isfinite(metadata_height_m) or metadata_height_m <= 0:
            raise ValueError("metadata_height_m must be finite and positive")
    warnings = []
    # Preserve the elevation silhouette, not just triangle connectivity. Topology
    # can stay unchanged while a nonuniform scale flattens a whole building.
    fit = np.eye(4)
    target = source_extents.copy()
    if dimensions_m is not None or height_m is not None:
        bounds = source_bounds
        extents = source_extents
        if dimensions_m is not None:
            dimensions = np.asarray(dimensions_m, float)
            if dimensions.shape != (2,):
                raise ValueError("dimensions_m must be source-frame (width, depth)")
            target[[0, 2]] = dimensions
            target[1] = extents[1] * dimensions[0]/extents[0]
        if height_m is not None:
            target[1] = float(height_m)
        if not np.isfinite(target).all() or min(target) <= 0 or min(extents) <= 0:
            raise ValueError("Metric dimensions must be finite and positive")
        aspect_ratio_change = (target[1]/target[0])/(extents[1]/extents[0])
        if height_m is not None and abs(aspect_ratio_change-1) > .2:
            if not allow_height_distortion:
                raise ValueError(
                    f"Height {target[1]:.2f} m changes the source facade proportions by "
                    f"{(aspect_ratio_change-1)*100:+.1f}%. This would squash/stretch the building. "
                    "Omit --height to preserve its proportions, or explicitly use "
                    "--allow-height-distortion for a verified height constraint.")
            warnings.append(f"Explicit height changes facade aspect by {(aspect_ratio_change-1)*100:+.1f}%")
        fit[:3, :3] = np.diag(target/extents)
        pivot = bounds.mean(axis=0)
        pivot[1] = bounds[0, 1]
        fit[:3, 3] = -fit[:3, :3] @ pivot
        scene.apply_transform(fit)
    scale = np.diag(fit)[:3]
    if metadata_height_m is not None and abs(target[1]-metadata_height_m)/metadata_height_m > .1:
        warnings.append(
            f"Height conflict: metadata says {metadata_height_m:.2f} m; preserving the source "
            f"facade gives {target[1]:.2f} m. The true height is unresolved; metadata has not "
            "been used to flatten the tower. Supply a verified --height if needed.")
    if abs(scale[2]/scale[0]-1) > .2:
        warnings.append(f"Depth fitted independently by {scale[2]/scale[0]:.3f}x relative to width; side proportions change")
    before = {}
    topology = {}
    for name, mesh in scene.geometry.items():
        if not isinstance(mesh, trimesh.Trimesh):
            raise ValueError("Source must contain triangle meshes")
        before[name] = (mesh.vertices.copy(), mesh.faces.copy(),
                        getattr(mesh.visual, 'uv', None))
        if not np.isfinite(mesh.vertices).all():
            raise ValueError(f"Nonfinite source vertices in {name}")
        topology[name] = topology_report(mesh)
        if str(name).startswith('entrance_'):
            continue
        if require_closed and (not topology[name]['watertight'] or topology[name]['degenerate_faces']):
            raise ValueError(f"Incomplete source geometry {name}: {topology[name]}. "
                             "Supply the complete original mesh; surface weathering cannot recover missing architecture.")
        visual = mesh.visual
        material = getattr(visual, 'material', None)
        texture = getattr(material, 'baseColorTexture', None)
        if texture is None:
            texture = getattr(material, 'image', None)
        if texture is not None:
            # Preserve all PBR maps; change only albedo, without changing alpha.
            material = copy.deepcopy(material)
            if not isinstance(material, trimesh.visual.material.PBRMaterial):
                material = material.to_pbr()
            material.baseColorTexture = scorch_surface(texture, strength)
            material.metallicFactor = 0.
            material.roughnessFactor = .95
            mesh.visual.material = material
        elif visual.kind in ('vertex', 'face'):
            # Genuine source colours are retained beneath the surface effect.
            kind = visual.kind
            colors = np.asarray(visual.vertex_colors if kind == 'vertex' else visual.face_colors)
            shaded = np.array(scorch_surface(Image.fromarray(colors[None].astype(np.uint8)), strength))[0]
            if kind == 'vertex':
                mesh.visual.vertex_colors = shaded
            else:
                mesh.visual.face_colors = shaded
        else:
            raise ValueError(f"{name} has no source texture/colours. Supply a textured original; "
                             "a flat state tint is not architectural detail.")
    data = trimesh.exchange.gltf.export_glb(scene, include_normals=True)
    loaded = trimesh.load(io.BytesIO(data), file_type='glb', force='scene', process=False)
    if set(loaded.geometry) != set(before):
        raise ValueError("Export changed the geometry nodes")
    for name, (vertices, faces, uv) in before.items():
        result = loaded.geometry[name]
        if not np.array_equal(vertices, result.vertices) or not np.array_equal(faces, result.faces):
            raise ValueError(f"Export changed source geometry: {name}")
        if uv is not None and not np.allclose(uv, result.visual.uv, atol=1e-7):
            raise ValueError(f"Export changed source UVs: {name}")
    for node in scene.graph.nodes_geometry:
        if not np.allclose(scene.graph[node][0], loaded.graph[node][0], atol=1e-7):
            raise ValueError(f"Export changed node transform: {node}")
    if not np.allclose(loaded.extents, target, rtol=1e-6, atol=1e-5):
        raise ValueError("Exported dimensions do not match the requested fit")
    if height_m is None and not np.isclose(loaded.extents[1]/loaded.extents[0],
                                         source_extents[1]/source_extents[0], rtol=1e-6):
        raise ValueError("Export distorted the source facade proportions")
    triangles = sum(len(m.faces) for m in loaded.geometry.values())
    if triangles > 30000 or len(data) > max_size_mb*1e6:
        raise ValueError(f"Source exceeds asset budget: {triangles} triangles, {len(data)/1e6:.2f} MB. "
                         "No automatic decimation: preserving source geometry was requested.")
    report = {"validation": "PASS", "mode": "preserve-source-geometry", "source": str(source),
              "geometry_unchanged": bool(np.array_equal(fit, np.eye(4))),
              "topology_and_local_vertices_unchanged": True, "metric_fit_transform": fit.tolist(),
              "source_extents_xyz_m": source_extents.tolist(),
              "final_extents_xyz_m": loaded.extents.tolist(), "scale_xyz": scale.tolist(),
              "height_policy": "explicit override" if height_m is not None else "preserve source facade aspect",
              "metadata_height_m": metadata_height_m,
              "height_verified": False,
              "facade_aspect_change_percent": float(((loaded.extents[1]/loaded.extents[0])/
                                                     (source_extents[1]/source_extents[0])-1)*100),
              "triangles": triangles, "glb_bytes": len(data),
              "source_topology": topology, "bounds_m_if_source_is_meters": loaded.bounds.tolist(),
              "placement": "Reuse source orientation; if metric fit applied, place the new base-center at the building anchor with scale 1",
              "warnings": warnings+["Surface weathering preserves existing damage too; it cannot recover parts already missing in the source.",
                           "Metric fitting enforces width/depth/height extents, not arbitrary OSM polygon silhouette."]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    output.with_suffix('.report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f"Geometry validated; {triangles:,} triangles; {len(data)/1e6:.2f} MB; validation PASS")
    print(f"Width / depth / height: {target[0]:.2f} / {target[2]:.2f} / {target[1]:.2f} m")
    print(f"Facade aspect change: {report['facade_aspect_change_percent']:+.2f}%; height policy: {report['height_policy']}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return report
