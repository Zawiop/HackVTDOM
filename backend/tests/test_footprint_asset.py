"""Real geometry/GLB regression tests; no model downloads or external services."""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import pytest
from shapely.geometry import Polygon, MultiPolygon

from app.generation.footprint_asset import build_asset
from app.generation.footprint_asset.geometry import prepare_footprint, estimate_height, select_facade
from app.generation.footprint_asset.pipeline import glb_document


@pytest.fixture
def photo(tmp_path):
    image = Image.new("RGB", (640, 400), (160, 145, 128))
    draw = ImageDraw.Draw(image)
    for x in range(30, 600, 70):
        for y in range(40, 350, 80):
            draw.rectangle((x, y, x+30, y+45), fill=(45, 65, 75))
    image.save(tmp_path/"photo.png")
    return str(tmp_path/"photo.png")


def build(tmp_path, photo, footprint, **kwargs):
    return build_asset(photo, footprint, "meters", 90, str(tmp_path/"asset.glb"),
                       facade_corners=[[0, 0], [639, 0], [639, 399], [0, 399]],
                       texture_size=512, **kwargs)


def test_real_dimensions_and_serialized_pbr(tmp_path, photo):
    report = build(tmp_path, photo, [[0, 0], [101.88, 0], [101.88, 37.57], [0, 37.57]],
                   footprint_dimensions=[101.88, 70.79], osm_tags={"height": "20.7"})
    assert report["validation"] == "PASS"
    assert report["topology"]["watertight"]
    assert report["topology"]["boundary_edges"] == 0
    assert np.allclose(report["final_footprint_frame_m"], [101.88, 70.79, 20.7], atol=1e-4)
    doc, _ = glb_document((tmp_path/"asset.glb").read_bytes())
    assert doc["samplers"][0]["minFilter"] == 9987
    material = doc["materials"][0]
    assert material["pbrMetallicRoughness"]["metallicFactor"] == 0
    assert "normalTexture" in material
    assert report["glb_bytes"] < 3_000_000


def test_concave_courtyard_and_multipart(tmp_path, photo):
    p = Polygon([(0, 0), (25, 0), (25, 15), (15, 15), (15, 25), (0, 25)],
                holes=[[(3, 3), (3, 8), (8, 8), (8, 3)]])
    other = Polygon([(30, 0), (35, 0), (35, 5), (30, 5)])
    report = build(tmp_path, photo, MultiPolygon([p, other]), include_floor=True)
    assert report["footprint_iou"] > .99999
    assert report["topology"]["watertight"]
    assert report["base_y_m"] == 0


def test_bearing_anchor_and_front(tmp_path, photo):
    # Geographic footprint with arbitrary facade: anchor+orientation must recover
    # the actual input polygon, including base-center offset after rotation.
    footprint = [[-80, 37], [-79.9998, 37], [-79.9998, 37.0001], [-80, 37.0001]]
    report = build_asset(photo, footprint, longest_edge_bearing=67,
                         output_path=tmp_path/"geo.glb", camera_bearing=180, texture_size=512)
    assert abs(report["facade_bearing_degrees"]-180) < .01
    assert report["longitude_latitude"] is not None
    assert abs(report["longitude_latitude"][0]+79.9999) < 1e-6
    assert report["placement"]["scaleXYZ"] == [1, 1, 1]


@pytest.mark.parametrize("tags,expected", [({"height": "100 ft"}, 30.48),
    ({"building:levels": "6"}, 19.2), ({"height": "NaN", "building:levels": "4"}, 12.8),
    ({}, 9.6), ({"building:levels": "nan"}, 9.6)])
def test_height_hierarchy(tags, expected):
    assert estimate_height(tags)[0] == pytest.approx(expected)
    assert estimate_height(tags, height_m=25)[0] == 25


def test_invalid_geometry_rejected():
    with pytest.raises(ValueError):
        prepare_footprint([[0, 0], [10, 10], [0, 10], [10, 0]], "meters")
    with pytest.raises(ValueError):
        prepare_footprint([[0, 0], [10, 0], [0, 10]], "meters", dimensions=[0, 1])


def test_facade_camera_selection():
    fp = prepare_footprint([[0, 0], [20, 0], [20, 10], [0, 10]], "meters", 90)
    for bearing in (0, 90, 180, 270):
        _, _, angle, _ = select_facade(fp, camera_bearing=bearing)
        result = (fp.bearing+90-np.degrees(angle)) % 360
        assert result == pytest.approx(bearing)


def test_invalid_corners_and_byte_budget(tmp_path, photo):
    args = dict(image_path=photo, footprint=[[0, 0], [20, 0], [20, 10], [0, 10]],
                footprint_crs_or_latlon="meters", output_path=tmp_path/"bad.glb", texture_size=512)
    with pytest.raises(ValueError, match="convex"):
        build_asset(**args, facade_corners=[[0, 0], [639, 399], [639, 0], [0, 399]])
    with pytest.raises(ValueError, match="Cannot fit"):
        build_asset(**args, max_size_mb=.001)
    assert not (tmp_path/"bad.glb").exists()


def test_front_normals_uv_not_mirrored_and_sharp_roof():
    from app.generation.footprint_asset.geometry import extrude
    fp = prepare_footprint([[0, 0], [20, 0], [20, 10], [0, 10]], "meters", 90)
    edge, _, angle, _ = select_facade(fp, camera_bearing=180)
    regions = {"facade": [0, .5, 1, 1], "wall": [0, 0, .5, .4], "roof": [.5, 0, 1, .4]}
    mesh, *_ = extrude(fp, 10, edge, angle, regions)
    front = np.where(mesh.visual.uv[:, 1] >= .5)[0]
    assert np.allclose(mesh.vertex_normals[front], [0, 0, 1])
    assert np.corrcoef(mesh.vertices[front, 0], mesh.visual.uv[front, 0])[0, 1] > .999
    roof = np.all(mesh.vertices[mesh.faces, 1] == 10, axis=1)
    assert np.allclose(mesh.face_normals[roof], [0, 1, 0])


def test_projected_crs_matches_geographic():
    from pyproj import Transformer
    from shapely.ops import transform
    polygon = Polygon([(-80, 37), (-79.9998, 37), (-79.9998, 37.0001), (-80, 37.0001)])
    projected = transform(Transformer.from_crs(4326, 32617, always_xy=True).transform, polygon)
    a = prepare_footprint(polygon, "EPSG:4326", 42)
    b = prepare_footprint(projected, "EPSG:32617", 42)
    assert np.allclose(a.target, b.target, atol=.001)
    assert np.allclose(a.position([0, 0]), b.position([0, 0]), atol=1e-8)
