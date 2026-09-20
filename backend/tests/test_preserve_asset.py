import io
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
from PIL import Image
import pytest
import trimesh

from app.generation.footprint_asset import restyle_existing_asset
from app.generation.scorch_material import scorch_surface
from app.services.worldstate import prompt_for


def source_mesh(tmp_path, hole=False):
    body = trimesh.creation.box(extents=[20, 10, 12])
    # A real roof/tower silhouette rather than replacing it with a prism.
    tower = trimesh.creation.box(extents=[4, 15, 4])
    tower.apply_translation([0, 10, 0])
    if hole:
        body.update_faces(np.arange(len(body.faces)) != 0)
    scene = trimesh.Scene()
    for name, mesh in [('body', body), ('tower', tower)]:
        mesh.visual = trimesh.visual.TextureVisuals(
            uv=np.zeros((len(mesh.vertices), 2)),
            material=trimesh.visual.material.PBRMaterial(
                baseColorTexture=Image.new('RGB', (128, 128), (150, 145, 130))))
        scene.add_geometry(mesh, geom_name=name, node_name=name)
    path = tmp_path/'original.glb'
    path.write_bytes(scene.export(file_type='glb'))
    return path


def test_tower_faces_vertices_and_transforms_survive(tmp_path):
    original = source_mesh(tmp_path)
    report = restyle_existing_asset(original, tmp_path/'scorched.glb')
    assert report['geometry_unchanged']
    a = trimesh.load(original, force='scene', process=False)
    b = trimesh.load(tmp_path/'scorched.glb', force='scene', process=False)
    for key in a.geometry:
        assert np.array_equal(a.geometry[key].vertices, b.geometry[key].vertices)
        assert np.array_equal(a.geometry[key].faces, b.geometry[key].faces)
    assert np.array_equal(a.bounds, b.bounds)


def test_open_mesh_fails_instead_of_passing_as_complete(tmp_path):
    original = source_mesh(tmp_path, hole=True)
    with pytest.raises(ValueError, match='Incomplete source geometry'):
        restyle_existing_asset(original, tmp_path/'scorched.glb')
    assert not (tmp_path/'scorched.glb').exists()


def test_scorch_is_spatial_neutral_and_preserves_alpha():
    source = np.full((128, 128, 4), [160, 160, 160, 255], dtype=np.uint8)
    source[0, :, 3] = 0
    result = np.array(scorch_surface(Image.fromarray(source)))
    assert np.array_equal(result[:, :, 3], source[:, :, 3])
    assert np.std(result[:, :, 0]) > 3
    assert np.max(abs(result[:, :, 0].astype(float)-result[:, :, 2])) < 5
    assert np.array_equal(np.array(scorch_surface(Image.fromarray(source), 0)), source)


def test_scorched_prompt_preserves_structure():
    prompt = prompt_for('scorched')
    assert 'Keep roofs and floors intact' in prompt
    assert 'whole sections of roof and floor have fallen' not in prompt


def test_optional_osm_fit_keeps_topology_and_roof_relief(tmp_path):
    original = source_mesh(tmp_path)
    report = restyle_existing_asset(original, tmp_path/'fitted.glb',
                                   dimensions_m=[101.88, 70.79], height_m=20.7,
                                   allow_height_distortion=True)
    fitted = trimesh.load(tmp_path/'fitted.glb', force='scene', process=False)
    assert np.allclose(fitted.extents, [101.88, 20.7, 70.79], atol=1e-4)
    assert report['topology_and_local_vertices_unchanged']
    assert set(fitted.geometry) == {'body', 'tower'}
    assert abs(fitted.bounds[0, 1]) < 1e-4


def test_footprint_fit_preserves_facade_aspect_with_conflicting_height(tmp_path):
    original = source_mesh(tmp_path)
    before = trimesh.load(original, force='scene', process=False)
    report = restyle_existing_asset(original, tmp_path/'fitted.glb',
                                   dimensions_m=[40, 30], metadata_height_m=10)
    after = trimesh.load(tmp_path/'fitted.glb', force='scene', process=False)
    assert np.allclose(after.extents[[0, 2]], [40, 30])
    assert after.extents[1]/after.extents[0] == pytest.approx(before.extents[1]/before.extents[0])
    assert report['scale_xyz'][0] == pytest.approx(report['scale_xyz'][1])
    assert report['facade_aspect_change_percent'] == pytest.approx(0)
    assert any('Height conflict' in w for w in report['warnings'])
    assert abs(after.bounds[0, 1]) < 1e-5


def test_extreme_explicit_height_rejected_before_writing(tmp_path):
    original = source_mesh(tmp_path)
    with pytest.raises(ValueError, match='squash/stretch'):
        restyle_existing_asset(original, tmp_path/'flat.glb', dimensions_m=[40, 30], height_m=5)
    assert not (tmp_path/'flat.glb').exists()


def test_cli_does_not_apply_osm_height_to_source_mesh(tmp_path):
    original = source_mesh(tmp_path)
    metadata = tmp_path/'footprint.json'
    metadata.write_text(json.dumps({'selected': {
        'footprintWidthMeters': 40, 'footprintDepthMeters': 30,
        'tags': {'height': '5', 'building:levels': '1'},
    }}))
    output = tmp_path/'cli.glb'
    subprocess.run([sys.executable, str(Path(__file__).parents[1]/'scripts/build_footprint_asset.py'),
                    '--source-mesh', str(original), '--footprint', str(metadata),
                    '--output', str(output)], check=True, capture_output=True, text=True)
    report = json.loads(output.with_suffix('.report.json').read_text())
    assert report['metadata_height_m'] == 5
    assert report['final_extents_xyz_m'][1] == pytest.approx(45)
    assert report['facade_aspect_change_percent'] == pytest.approx(0)
