"""Public build_asset entry point and JSON CLI. Run from backend with python -m."""
import argparse
import io
import json
from pathlib import Path
import struct
import time

import numpy as np
from PIL import Image
import trimesh
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .geometry import prepare_footprint, select_facade, estimate_height, extrude
from .textures import rectify, atlas, regions


def glb_document(data):
    if data[:4] != b"glTF" or struct.unpack_from("<I", data, 8)[0] != len(data):
        raise ValueError("Invalid GLB header/length")
    length, kind = struct.unpack_from("<II", data, 12)
    if kind != 0x4e4f534a:
        raise ValueError("Missing GLB JSON chunk")
    return json.loads(data[20:20+length]), data[28+length:]


def export_glb(mesh):
    def samplers(tree):
        tree["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071}]
        for texture in tree.get("textures", []):
            texture["sampler"] = 0
    return trimesh.exchange.gltf.export_glb(trimesh.Scene(mesh), include_normals=True,
                                            tree_postprocessor=samplers)


def validate(data, fp, rotation, center, expected_height, max_bytes, require_closed=True):
    """Validate the serialized artifact, including roof coverage, not only memory."""
    doc, binary = glb_document(data)
    scene = trimesh.load(io.BytesIO(data), file_type="glb", force="scene", process=False)
    mesh = scene.to_geometry()
    vertices = np.asarray(mesh.vertices)
    failures = []
    def check(ok, label):
        if not ok:
            failures.append(label)
    check(np.isfinite(vertices).all(), "NaN/Inf vertices")
    check(0 < len(mesh.faces) <= 30000, "triangle count outside 1–30000")
    check(np.all(mesh.area_faces > 1e-10), "degenerate triangles")
    check(np.isfinite(mesh.vertex_normals).all() and np.allclose(np.linalg.norm(mesh.vertex_normals, axis=1), 1, atol=1e-3), "invalid normals")
    check(abs(mesh.bounds[0, 1]) < 1e-4, "base Y != 0")
    check(np.max(abs(mesh.bounds.mean(axis=0)[[0, 2]])) < 1e-4, "pivot not base-center")
    check(abs(mesh.extents[1]-expected_height) < .001, "height mismatch")
    from .preserve import topology_report
    topology = topology_report(mesh)
    if require_closed:
        check(topology['watertight'], f"incomplete solid: {topology}")
    canonical = trimesh.transform_points(vertices+center, np.linalg.inv(rotation))
    horizontal = canonical[:, [0, 2]]
    actual = np.ptp(horizontal, axis=0)
    error = abs(actual-fp.target)/fp.target
    check(max(error) < .001, "footprint dimension error >0.1%")
    roof_faces = mesh.faces[np.all(abs(vertices[mesh.faces, 1]-expected_height) < .001, axis=1)]
    coverage = unary_union([Polygon(horizontal[f]) for f in roof_faces])
    iou = coverage.intersection(fp.polygon).area/coverage.union(fp.polygon).area
    check(iou > .999, "roof/footprint silhouette IoU <0.999")
    for m in doc["meshes"]:
        for primitive in m["primitives"]:
            attrs = primitive["attributes"]
            check("NORMAL" in attrs and "TEXCOORD_0" in attrs, "missing exported NORMAL/UV")
    for geom in scene.geometry.values():
        uv = getattr(geom.visual, "uv", None)
        check(uv is not None and np.isfinite(uv).all() and np.min(uv) >= 0 and np.max(uv) <= 1, "invalid UVs")
    texture_sizes = []
    for image in doc.get("images", []):
        view = doc["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        with Image.open(io.BytesIO(binary[start:start+view["byteLength"]])) as im:
            texture_sizes.append(list(im.size))
            check(im.width == im.height and im.width in (512, 1024, 2048), "unexpected texture dimensions")
    check(len(texture_sizes) == 3, "expected three packed PBR images")
    check(len(doc.get("materials", [])) == 1, "expected one material")
    check(len(data) <= max_bytes, "GLB exceeds configured size budget")
    if failures:
        raise ValueError("Asset validation FAILED: " + "; ".join(failures))
    return {"validation": "PASS", "footprint_target_m": fp.target.tolist(),
            "final_footprint_frame_m": [*actual.tolist(), float(mesh.extents[1])],
            "model_xyz_bounds_m": mesh.bounds.tolist(), "dimension_error_percent": (error*100).tolist(),
            "footprint_iou": float(iou), "topology": topology, "triangles": len(mesh.faces),
            "materials": len(doc["materials"]), "texture_dimensions": texture_sizes,
            "glb_bytes": len(data), "base_y_m": float(mesh.bounds[0, 1]), "pivot": "base-center"}


def build_asset(image_path, footprint, footprint_crs_or_latlon="EPSG:4326",
                longest_edge_bearing=None, output_path="building.glb", *,
                footprint_dimensions=None, osm_tags=None, height_m=None,
                default_levels=3, level_height=3.2, facade_corners=None,
                facade_edge_index=None, camera_bearing=None, world_state="scorched",
                texture_size=2048, max_size_mb=3., delight_strength=.35, include_floor=True):
    """Build one standalone GLB; return validation + placement report.

    facade_corners: EXIF-oriented source pixels in TL,TR,BR,BL order.
    camera_bearing: building-to-camera bearing (clockwise from north).
    footprint_dimensions: (width along supplied bearing, perpendicular depth).
    Local meter inputs return no geographic anchor; caller supplies its origin.
    Existing image editing/rembg may feed this function directly. No network use.
    """
    start = time.perf_counter()
    timings = {}
    max_bytes = int(max_size_mb*1_000_000)
    if max_bytes <= 0 or texture_size not in (512, 1024, 2048):
        raise ValueError("Positive size budget and 512/1024/2048 texture_size required")
    output = Path(output_path)
    if output.suffix.lower() != ".glb":
        raise ValueError("output_path must end in .glb")
    fp = prepare_footprint(footprint, footprint_crs_or_latlon, longest_edge_bearing, footprint_dimensions)
    edge, edges, angle, edge_source = select_facade(fp, facade_edge_index, camera_bearing)
    height, height_source, height_warnings = estimate_height(osm_tags, height_m, default_levels, level_height)
    timings["footprint_and_height"] = time.perf_counter()-start
    t = time.perf_counter()
    facade, overlay, photo = rectify(image_path, facade_corners, texture_size, delight_strength)
    timings["rectification_and_delighting"] = time.perf_counter()-t
    t = time.perf_counter()
    # Drop resolution until BOTH the requested file budget and dimensions pass.
    attempts = []
    for size in (s for s in (2048, 1024, 512) if s <= texture_size):
        material, uv_regions, images = atlas(facade, world_state, size)
        mesh, rotation, center, anchor_offset, facade_length = extrude(fp, height, edge, angle, uv_regions, include_floor)
        mesh.visual.material = material
        data = export_glb(mesh)
        attempts.append({"size": size, "bytes": len(data)})
        if len(data) <= max_bytes:
            break
    else:
        raise ValueError(f"Cannot fit GLB into {max_size_mb} MB: {attempts}")
    timings["materials_geometry_export"] = time.perf_counter()-t
    t = time.perf_counter()
    report = validate(data, fp, rotation, center, height, max_bytes, require_closed=include_floor)
    timings["validation"] = time.perf_counter()-t
    facade_bearing = (fp.bearing+90-np.degrees(angle)) % 360
    lonlat = fp.position(anchor_offset)
    position = [lonlat[1], lonlat[0], 0] if lonlat else None
    x0, y0, x1, y1 = regions(size)["facade"]
    warnings = fp.warnings+height_warnings
    warnings.append("Footprint-only massing approximates architecture; use --source-mesh with a complete original to preserve towers and roof shapes")
    if photo["confidence"] == "low":
        warnings.append("Low-confidence facade rectification; inspect facade-corners.png before presenting")
    if photo["alpha_coverage"] < .92:
        warnings.append("Facade contains masked background; neutral fill used")
    if len(attempts) > 1:
        warnings.append("Atlas resolution reduced to meet GLB byte budget")
    report.update({"height_source": height_source, "facade": photo,
                   "facade_edge_index": edge, "facade_edge_source": edge_source,
                   "exterior_edges_xz_m": [[a.tolist(), b.tolist()] for a, b in edges],
                   "facade_length_m": facade_length, "facade_bearing_degrees": float(facade_bearing),
                   "placement": {"position": position, "rotationDegrees": float((180-facade_bearing) % 360),
                                 "scale": 1., "scaleXYZ": [1., 1., 1.]},
                   "deck_orientation": [0, float((180-facade_bearing) % 360), 90],
                   "local_anchor_offset_xz_m": anchor_offset.tolist(),
                   "longitude_latitude": lonlat,
                   "footprint_frame_bearing": fp.bearing,
                   "facade_texels_per_meter": [(x1-x0)/facade_length, (y1-y0)/height],
                   "effective_source_texels_per_meter": [photo["source_facade_pixels"][0]/facade_length,
                                                         photo["source_facade_pixels"][1]/height],
                   "atlas_size": size, "size_attempts": attempts,
                   "warnings": warnings, "timings_seconds": timings})
    output.parent.mkdir(parents=True, exist_ok=True)
    debug = output.with_suffix(".debug")
    debug.mkdir(exist_ok=True)
    overlay.save(debug/"facade-corners.png")
    facade.save(debug/"facade-rectified.png")
    for name, im in images.items():
        im.save(debug/f"{name}.png")
    # No output GLB is written until serialized validation succeeds.
    output.write_bytes(data)
    timings["total"] = time.perf_counter()-start
    output.with_suffix(".report.json").write_text(json.dumps(report, indent=2)+"\n")
    print("=== Scorched Nebraska Asset Report ===")
    print(f"Footprint target: {fp.target[0]:.2f} x {fp.target[1]:.2f} m")
    print("Final footprint-frame W/D/H: " + " x ".join(f"{v:.2f}" for v in report["final_footprint_frame_m"]) + " m")
    print(f"Dimension error: {report['dimension_error_percent']} %; silhouette IoU: {report['footprint_iou']:.6f}")
    print(f"Triangles: {report['triangles']:,}; materials: 1; PBR atlas: {size} x {size}")
    print(f"GLB: {len(data)/1e6:.2f} MB; base Y: {report['base_y_m']:.6f}; pivot: base-center")
    print(f"Validation: PASS; total: {timings['total']:.2f}s")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="JSON object of build_asset keyword arguments")
    args = parser.parse_args()
    build_asset(**json.loads(Path(args.config).read_text()))


if __name__ == "__main__":
    main()
