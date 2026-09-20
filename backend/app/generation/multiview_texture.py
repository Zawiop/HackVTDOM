"""CPU photo projection for shape-only multiview meshes, with a bounded GLB.

The labelled photos are approximate orthographic cameras, not calibrated views.
Visible walls receive actual image detail; missing views receive neutral material
patches, never another side's windows. No cloud texturing/model call is needed.
"""
import io

import numpy as np
from PIL import Image, ImageOps
import trimesh

# (outward camera direction, image right, image up) in raw Hunyuan +Y-up space.
_CAMERAS = {
    'front': ([0, 0, 1], [1, 0, 0], [0, 1, 0]),
    'back': ([0, 0, -1], [-1, 0, 0], [0, 1, 0]),
    'left': ([-1, 0, 0], [0, 0, 1], [0, 1, 0]),
    'right': ([1, 0, 0], [0, 0, -1], [0, 1, 0]),
    'roof': ([0, 1, 0], [1, 0, 0], [0, 0, -1]),
    'base': ([0, -1, 0], [1, 0, 0], [0, 0, 1]),
}


def _photo(data):
    with Image.open(io.BytesIO(data)) as image:
        rgba = ImageOps.exif_transpose(image).convert('RGBA')
    alpha = np.asarray(rgba)[:, :, 3]
    ys, xs = np.where(alpha > 127)
    if len(xs) < 64:
        raise ValueError('View contains too little foreground to texture')
    rgba = rgba.crop((int(xs.min()), int(ys.min()), int(xs.max())+1, int(ys.max())+1))
    arr = np.asarray(rgba)
    color = np.median(arr[:, :, :3][arr[:, :, 3] > 127], axis=0).astype(np.uint8)
    background = Image.new('RGBA', rgba.size, (*color.tolist(), 255))
    background.alpha_composite(rgba)
    return background.convert('RGB'), color


def _material_tile(color, roof=False):
    # Low-frequency, neutral surface variation; no arbitrary window hallucination.
    y, x = np.mgrid[0:256, 0:256]/256
    variation = .97+.025*np.sin(x*2*np.pi*11)*np.cos(y*2*np.pi*9)
    rgb = np.asarray(color)*(.65 if roof else .9)
    return Image.fromarray(np.uint8(np.clip(variation[:, :, None]*rgb, 0, 255)))


def texture_multiview_mesh(glb, views, *, camera_transform=None, max_faces=28000, atlas_size=2048):
    """Return (textured GLB, diagnostics), retaining mesh shape and source frame.

    camera_transform maps mesh positions BACK to the raw multiview camera frame
    when repairing an already normalized mesh. Normal generation uses identity.
    Input is body geometry only; callers append entrance overlays afterwards.
    """
    if not views.get('front'):
        raise ValueError('Front photo is required for photo texturing')
    if not 12 <= max_faces <= 29000 or atlas_size not in (1024, 2048):
        raise ValueError('Invalid texture/triangle budget')
    scene = trimesh.load(io.BytesIO(glb), file_type='glb', force='scene', process=False)
    mesh = scene.to_geometry()
    if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
        raise ValueError('Cannot texture empty/nonfinite geometry')
    input_faces = len(mesh.faces)
    bounds = mesh.bounds.copy()
    if input_faces > max_faces:
        mesh = mesh.simplify_quadric_decimation(face_count=max_faces, aggression=5)
        mesh.remove_unreferenced_vertices()
        # Reject excessive simplification drift instead of silently changing scale.
        if np.max(np.abs(mesh.bounds-bounds)/np.maximum(bounds[1]-bounds[0], 1e-6)) > .015:
            raise ValueError('Simplification moved mesh bounds by more than 1.5%')
        # Restore the pre-simplification bounds, especially Y=0 for assets that
        # already have map placement. This is only the small residual above.
        reduced_bounds = mesh.bounds.copy()
        residual_scale = (bounds[1]-bounds[0])/np.maximum(mesh.extents, 1e-12)
        mesh.apply_scale(residual_scale)
        mesh.apply_translation(bounds[0]-reduced_bounds[0]*residual_scale)
    if len(mesh.faces) > max_faces:
        raise ValueError('Simplifier did not meet triangle budget')
    photos, colors = {}, []
    for name, data in views.items():
        if name in ('front', 'back', 'left', 'right') and data:
            photo, color = _photo(data)
            photos[name] = photo
            colors.append(color)
    color = np.median(colors, axis=0)
    keys = list(_CAMERAS)
    tile_size = atlas_size//3
    gutter = 8
    canvas = Image.new('RGB', (atlas_size, atlas_size), tuple(np.uint8(color)))
    rectangles = {}
    for i, name in enumerate(keys):
        col, row = i % 3, i//3
        x0, y0 = col*tile_size+gutter, row*tile_size+gutter
        side = tile_size-2*gutter
        tile = photos.get(name)
        if tile is None:
            tile = _material_tile(color, roof=name in ('roof', 'base'))
        tile = tile.resize((side, side), Image.Resampling.LANCZOS)
        # Extend island edges into gutters; request mipmaps during GLB export.
        padded = np.pad(np.asarray(tile), ((gutter, gutter), (gutter, gutter), (0, 0)), mode='edge')
        canvas.paste(Image.fromarray(padded), (col*tile_size, row*tile_size))
        rectangles[name] = (x0+.5, y0+.5, x0+side-.5, y0+side-.5)
    transform = np.eye(4) if camera_transform is None else np.asarray(camera_transform, float)
    if transform.shape != (4, 4) or not np.isfinite(transform).all():
        raise ValueError('camera_transform must be finite 4x4')
    camera_vertices = trimesh.transform_points(mesh.vertices, transform)
    triangles = camera_vertices[mesh.faces]
    face_normals = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
    directions = np.array([_CAMERAS[name][0] for name in keys])
    labels = np.argmax(face_normals @ directions.T, axis=1)
    # A corner photo sees more than one wall. When a side slot is missing,
    # still use an available camera that actually faces that surface; never
    # wrap front windows onto rear-facing surfaces.
    supplied = np.array([keys.index(name) for name in photos])
    unit_normals = face_normals/np.maximum(np.linalg.norm(face_normals, axis=1, keepdims=True), 1e-12)
    scores = unit_normals @ directions[supplied].T
    best = np.argmax(scores, axis=1)
    missing_wall = (labels < 4) & ~np.isin(labels, supplied)
    visible = scores[np.arange(len(scores)), best] > .3
    labels[missing_wall & visible] = supplied[best[missing_wall & visible]]
    # Split only view seams, not every triangle: keep vertex/UV overhead small.
    pairs, inverse = np.unique(np.column_stack([mesh.faces.ravel(), np.repeat(labels, 3)]),
                               axis=0, return_inverse=True)
    uv = np.zeros((len(pairs), 2))
    for i, name in enumerate(keys):
        selected = pairs[:, 1] == i
        basis = np.array([_CAMERAS[name][1], _CAMERAS[name][2]]).T
        projected = camera_vertices @ basis
        lo, hi = projected.min(axis=0), projected.max(axis=0)
        coord = np.clip((projected[pairs[selected, 0]]-lo)/np.maximum(hi-lo, 1e-8), 0, 1)
        x0, y0, x1, y1 = rectangles[name]
        uv[selected, 0] = (x0+coord[:, 0]*(x1-x0))/atlas_size
        uv[selected, 1] = 1-(y1-coord[:, 1]*(y1-y0))/atlas_size
    normals = np.asarray(mesh.vertex_normals)[pairs[:, 0]]
    result = trimesh.Trimesh(vertices=mesh.vertices[pairs[:, 0]], faces=inverse.reshape(-1, 3),
                             vertex_normals=normals, process=False)
    encoded = io.BytesIO()
    canvas.save(encoded, 'JPEG', quality=90, subsampling=0)
    encoded.seek(0)
    material = trimesh.visual.material.PBRMaterial(
        name='multiview-photo-atlas', baseColorTexture=Image.open(encoded),
        baseColorFactor=[1., 1., 1., 1.], metallicFactor=0., roughnessFactor=.9,
        alphaMode='OPAQUE', doubleSided=False)
    result.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    def sampler(tree):
        tree['samplers'] = [{'minFilter': 9987, 'magFilter': 9729, 'wrapS': 33071, 'wrapT': 33071}]
        for texture in tree.get('textures', []):
            texture['sampler'] = 0
    output = trimesh.exchange.gltf.export_glb(trimesh.Scene(result), include_normals=True, tree_postprocessor=sampler)
    if len(output) > 3_000_000:
        if atlas_size == 2048:
            return texture_multiview_mesh(glb, views, camera_transform=camera_transform,
                                          max_faces=max_faces, atlas_size=1024)
        raise ValueError('Photo-textured mesh exceeds 3 MB budget')
    return output, {
        'method': 'labelled-photo projection', 'photoViews': sorted(photos),
        'materialOnlyViews': [name for name in keys if name not in photos],
        'inputFaces': input_faces, 'faces': len(result.faces), 'atlasSize': atlas_size,
        'bytes': len(output),
        'warning': 'Photo projection uses approximate cameras; missing views use neutral materials.',
    }
