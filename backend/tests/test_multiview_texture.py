"""Photo detail must survive the actual mesh route, not just an image preview."""
import asyncio
import io
import json
import struct

import numpy as np
from PIL import Image, ImageDraw
import pytest
import trimesh

from app.generation.multiview_texture import texture_multiview_mesh
from app.generation.mesh_normalize import normalize_glb


def photo(color=(210, 170, 120)):
    image = Image.new('RGBA', (128, 128), (*color, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 20, 40, 90), fill=(10, 30, 70, 255))
    draw.rectangle((85, 50, 110, 95), fill=(40, 60, 30, 255))
    out = io.BytesIO()
    image.save(out, 'PNG')
    return out.getvalue()


def document(data):
    n = struct.unpack_from('<I', data, 12)[0]
    return json.loads(data[20:20+n])


def test_export_contains_actual_photo_texture_and_uvs():
    raw = trimesh.Scene(trimesh.creation.box()).export(file_type='glb')
    output, report = texture_multiview_mesh(raw, {'front': photo(), 'back': photo((50, 180, 70))})
    doc = document(output)
    assert doc['images']
    pbr = doc['materials'][0]['pbrMetallicRoughness']
    assert 'baseColorTexture' in pbr
    assert pbr['baseColorFactor'] == [1, 1, 1, 1]
    assert 'COLOR_0' not in doc['meshes'][0]['primitives'][0]['attributes']
    assert 'TEXCOORD_0' in doc['meshes'][0]['primitives'][0]['attributes']
    assert report['photoViews'] == ['back', 'front']
    mesh = trimesh.load(io.BytesIO(output), file_type='glb', force='scene').to_geometry()
    assert np.array(mesh.visual.material.baseColorTexture).std() > 15
    assert len(mesh.faces) == 12
    assert np.allclose(mesh.extents, [1, 1, 1])
    # Front UVs increase with X and Y, so the photograph is not mirrored/upside-down.
    faces = mesh.faces[mesh.face_normals[:, 2] > .9]
    indices = np.unique(faces)
    assert np.corrcoef(mesh.vertices[indices, 0], mesh.visual.uv[indices, 0])[0, 1] > .99
    assert np.corrcoef(mesh.vertices[indices, 1], mesh.visual.uv[indices, 1])[0, 1] > .99


def test_texture_survives_normalization():
    raw = trimesh.Scene(trimesh.creation.box()).export(file_type='glb')
    painted, _ = texture_multiview_mesh(raw, {'front': photo()})
    output, _ = normalize_glb(painted, 'hunyuan3d-mv', 30, 20)
    assert document(output)['images']
    assert 'baseColorTexture' in document(output)['materials'][0]['pbrMetallicRoughness']


def test_large_mesh_meets_budget_without_flattening():
    mesh = trimesh.creation.icosphere(subdivisions=5)
    raw = trimesh.Scene(mesh).export(file_type='glb')
    output, report = texture_multiview_mesh(raw, {'front': photo()}, max_faces=2000)
    result = trimesh.load(io.BytesIO(output), file_type='glb', force='scene').to_geometry()
    assert len(result.faces) <= 2000
    assert np.allclose(result.bounds, mesh.bounds, atol=1e-6)
    assert len(output) < 3_000_000


def test_missing_or_empty_photo_fails_instead_of_silent_grey():
    raw = trimesh.Scene(trimesh.creation.box()).export(file_type='glb')
    with pytest.raises(ValueError, match='Front photo'):
        texture_multiview_mesh(raw, {})
    with pytest.raises(ValueError, match='Front photo'):
        texture_multiview_mesh(raw, {'front': b''})
    out = io.BytesIO()
    Image.new('RGBA', (128, 128), (0, 0, 0, 0)).save(out, 'PNG')
    with pytest.raises(ValueError, match='foreground'):
        texture_multiview_mesh(raw, {'front': out.getvalue()})


def test_generate_route_returns_photo_atlas_after_entrances(monkeypatch, tmp_path):
    from app.generation import mesh_generate as mg, config, storage
    monkeypatch.setattr(config, 'OUTPUT_DIR', tmp_path)
    monkeypatch.setattr(storage, '_CACHE_FILE', tmp_path/'cache.json')
    raw = trimesh.Scene(trimesh.creation.box()).export(file_type='glb')
    monkeypatch.setattr(mg, 'generate_multiview_mesh', lambda *a, **k: raw)
    monkeypatch.setattr(mg, 'cut_out_building', lambda image: (image.convert('RGBA'), 1.))
    result = asyncio.run(mg.generate_mesh(photo(), 30, 20, extra_views={'back': photo()}, world_state='flooded'))
    assert result['provider'] == 'hunyuan3d-mv'
    path = storage.local_path_for_url(result['meshUrl'])
    assert path is not None
    assert document(path.read_bytes())['images']
    assert result['entrances']
    assert len(document(path.read_bytes())['meshes']) >= 3
    assert result['normalization']['faces'] <= 28000
