"""Bounded homography, conservative illumination flattening, one padded PBR atlas."""
import io
import cv2
import numpy as np
from PIL import Image, ImageFilter, ImageOps
from trimesh.visual.material import PBRMaterial


def ordered_quad(points):
    points = np.asarray(points, np.float32)
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError("facade_corners must be four finite pixel points: TL, TR, BR, BL")
    if not cv2.isContourConvex(points) or abs(cv2.contourArea(points)) < 64:
        raise ValueError("Facade quad must be convex, noncrossing and at least 64 pixels")
    return points


def automatic_quad(rgb, alpha):
    """Best effort, NOT semantic detection. Prefer masked contour quadrilateral.

    Opaque input uses edge-contour candidates; low confidence falls back to an
    inset crop. Diagnostics always expose the selected polygon and confidence.
    """
    h, w = alpha.shape
    masked = np.mean(alpha < 250) > .02 and np.mean(alpha > 127) > .02
    if masked:
        mask = (alpha > 127).astype(np.uint8)*255
    else:
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        mask = cv2.morphologyEx(cv2.Canny(gray, 50, 130), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:12]:
        hull = cv2.convexHull(c)
        q = cv2.approxPolyDP(hull, .025*cv2.arcLength(hull, True), True).reshape(-1, 2)
        if len(q) != 4 or cv2.contourArea(q) < w*h*.12:
            continue
        # Screen-space upper pair, then lower pair; suitable for upright street photos.
        upper, lower = np.array_split(q[np.argsort(q[:, 1])], 2)
        upper, lower = upper[np.argsort(upper[:, 0])], lower[np.argsort(lower[:, 0])]
        quad = np.array([upper[0], upper[1], lower[1], lower[0]], np.float32)
        if cv2.isContourConvex(quad):
            return quad, "medium" if masked else "low", "alpha contour" if masked else "edge contour"
    # Prefer an observable wall band between long eave/base lines over a crop
    # containing sky and foreground. This deliberately excludes tower silhouettes.
    lines = cv2.HoughLinesP(cv2.Canny(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), 40, 100),
                            1, np.pi/720, 50, minLineLength=w*.2, maxLineGap=w*.08)
    if lines is not None:
        horizontal = []
        for x0, y0, x1, y1 in lines[:, 0]:
            if x1 < x0:
                x0, y0, x1, y1 = x1, y1, x0, y0
            if x1-x0 > w*.25 and abs(y1-y0)/(x1-x0) < .3:
                horizontal.append((x0, y0, x1, y1))
        top = [l for l in horizontal if .25*h < (l[1]+l[3])/2 < .6*h]
        bottom = [l for l in horizontal if .65*h < (l[1]+l[3])/2 < .88*h]
        if top and bottom:
            a = max(top, key=lambda l: l[2]-l[0])
            b = max(bottom, key=lambda l: l[2]-l[0])
            left, right = max(a[0], b[0]), min(a[2], b[2])
            def line_y(line, x):
                return line[1]+(x-line[0])*(line[3]-line[1])/(line[2]-line[0])
            quad = np.float32([[left, line_y(a, left)], [right, line_y(a, right)],
                               [right, line_y(b, right)], [left, line_y(b, left)]])
            if right-left > w*.25 and cv2.isContourConvex(quad) and abs(cv2.contourArea(quad)) > w*h*.06:
                return quad, "low", "eave/base line band"
    if masked:
        y, x = np.where(alpha > 127)
        x0, x1, y0, y1 = x.min(), x.max(), y.min(), y.max()
    else:
        x0, x1, y0, y1 = .1*w, .9*w, .12*h, .88*h
    return np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]), "low", "bounding crop fallback"


def rectify(image_path, corners=None, size=2048, delight_strength=.35):
    if not 0 <= delight_strength <= 1:
        raise ValueError("delight_strength must be between 0 and 1")
    with Image.open(image_path) as im:
        im = ImageOps.exif_transpose(im).convert("RGBA")
        if max(im.size) > 12000:
            raise ValueError("Input image too large; resize to <=12000 pixels per side")
        rgba = np.array(im)
    rgb, alpha = rgba[:, :, :3], rgba[:, :, 3]
    if corners is None:
        q, confidence, method = automatic_quad(rgb, alpha)
    else:
        q, confidence, method = ordered_quad(corners), "user-supplied", "four-point override"
    q = ordered_quad(q)
    h, w = alpha.shape
    if (q < 0).any() or (q[:, 0] > w-1).any() or (q[:, 1] > h-1).any():
        raise ValueError("Facade corners must lie inside EXIF-oriented image")
    width = max(np.linalg.norm(q[1]-q[0]), np.linalg.norm(q[2]-q[3]))
    height = max(np.linalg.norm(q[3]-q[0]), np.linalg.norm(q[2]-q[1]))
    width_px = min(size, max(64, round(width)))
    height_px = min(size, max(64, round(height)))
    dest = np.float32([[0, 0], [width_px-1, 0], [width_px-1, height_px-1], [0, height_px-1]])
    homography = cv2.getPerspectiveTransform(q, dest)
    warped = cv2.warpPerspective(rgb, homography, (width_px, height_px))
    coverage = cv2.warpPerspective(alpha, homography, (width_px, height_px))
    valid = coverage > 127
    if valid.mean() < .1:
        raise ValueError("Facade is mostly transparent; provide corrected corners")
    color = np.median(warped[valid], axis=0)
    warped[~valid] = color
    # Small mask holes can be inpainted. Large background regions stay neutral.
    if .001 < 1-valid.mean() < .08:
        warped = cv2.inpaint(warped, (~valid).astype(np.uint8)*255, 3, cv2.INPAINT_TELEA)
    # Work in linear light; flatten only a bounded low-frequency luminance field.
    s = warped.astype(np.float32)/255
    linear = np.where(s <= .04045, s/12.92, ((s+.055)/1.055)**2.4)
    lum = linear @ np.array([.2126, .7152, .0722], np.float32)
    small = cv2.resize(np.log(np.maximum(lum, .02)), (64, 64), interpolation=cv2.INTER_AREA)
    field = cv2.resize(cv2.GaussianBlur(small, (0, 0), 6), (width_px, height_px))
    gain = np.clip(np.exp((np.median(field)-field)*delight_strength), .8, 1.25)
    linear = np.clip(linear*gain[:, :, None], 0, 1)
    srgb = np.where(linear <= .0031308, linear*12.92, 1.055*linear**(1/2.4)-.055)
    result = Image.fromarray(np.uint8(np.clip(srgb*255, 0, 255)))
    result = result.filter(ImageFilter.UnsharpMask(radius=1, percent=45, threshold=4))
    overlay = rgb.copy()
    cv2.polylines(overlay, [q.astype(np.int32)], True, (255, 60, 30), 4)
    return result, Image.fromarray(overlay), {
        "corners_tl_tr_br_bl": q.tolist(), "confidence": confidence, "method": method,
        "homography": homography.tolist(), "source_facade_pixels": [width_px, height_px],
        "alpha_coverage": float(valid.mean()), "delight_strength": delight_strength,
    }


def procedural(size, color, state, roof=False):
    """Periodic, non-semantic masonry/roof pattern; no copied facade windows."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)/size
    stone = .035*np.sin(x*2*np.pi*16)*np.sin(y*2*np.pi*12)
    stone += .015*np.cos((x*31+y*23)*2*np.pi)
    color = np.asarray(color, np.float32)/255
    if roof:
        color *= .65
    base = np.broadcast_to(color, (size, size, 3)).copy()+stone[:, :, None]
    if not roof:
        rows = np.floor(y*16)
        mortar = (np.mod(y*16, 1) < .055) | (np.mod(x*8+np.mod(rows, 2)*.5, 1) < .035)
        base[mortar] *= .78
    else:
        seams = (np.mod(x*8, 1) < .025) | (np.mod(y*8, 1) < .025)
        base[seams] *= .85
    patches = (np.sin(x*2*np.pi*3)+np.cos(y*2*np.pi*2)+np.sin((x+y)*2*np.pi*5))/3
    palettes = {"reclaimed": [.22, .29, .13], "flooded": [.22, .29, .29],
                "scorched": [.15, .13, .12], "buried": [.58, .46, .3],
                "petrified": [.45, .46, .44]}
    blend = np.clip(patches+.2, 0, 1)*.45
    base = base*(1-blend[:, :, None])+np.array(palettes[state])*blend[:, :, None]
    return Image.fromarray(np.uint8(np.clip(base*255, 0, 255)))


def regions(size):
    # Pixel rectangles: front occupies 3/4 atlas height, bottom split wall/roof.
    # 16px gutters at 2048, scaled for lower resolution size tiers.
    pad = max(4, size//128)
    return {"facade": (pad, pad, size-pad, 3*size//4-pad),
            "wall": (pad, 3*size//4+pad, size//2-pad, size-pad),
            "roof": (size//2+pad, 3*size//4+pad, size-pad, size-pad)}


def atlas(facade, state="scorched", size=2048):
    if state not in {"reclaimed", "flooded", "scorched", "buried", "petrified"}:
        raise ValueError("Unknown world state")
    if size not in (512, 1024, 2048):
        raise ValueError("Atlas size must be 512, 1024 or 2048")
    color = np.median(np.array(facade.resize((64, 64))).reshape(-1, 3), axis=0)
    tiles = {"facade": facade, "wall": procedural(512, color, state),
             "roof": procedural(512, color, state, roof=True)}
    images = {"baseColor": np.zeros((size, size, 3), np.uint8),
              "normal": np.full((size, size, 3), [128, 128, 255], np.uint8),
              "roughness": np.full((size, size, 3), [255, 220, 0], np.uint8)}
    uv_regions = {}
    pad = max(4, size//128)
    for name, (x0, y0, x1, y1) in regions(size).items():
        rgb = np.array(tiles[name].resize((x1-x0, y1-y0), Image.Resampling.LANCZOS))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)/255
        # High-pass only, gentle relief: not a recovered geometry/depth map.
        bump = gray-cv2.GaussianBlur(gray, (0, 0), 3)
        du = cv2.Sobel(bump, cv2.CV_32F, 1, 0, ksize=3)*.15
        dv = cv2.Sobel(bump, cv2.CV_32F, 0, 1, ksize=3)*.15
        # glTF normal +Y points toward UV +V, opposite image row direction.
        n = np.dstack([-du, dv, np.ones_like(du)])
        n /= np.linalg.norm(n, axis=2, keepdims=True)
        normal = np.uint8(np.clip((n*.5+.5)*255, 0, 255))
        orm = np.empty_like(rgb)
        orm[:, :, 0], orm[:, :, 2] = 255, 0
        orm[:, :, 1] = np.uint8(np.clip(.85+.12*np.abs(bump), .8, .98)*255)
        for key, tile in [("baseColor", rgb), ("normal", normal), ("roughness", orm)]:
            # Extend each island into its gutter to protect lower mip levels.
            padded = np.pad(tile, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
            images[key][y0-pad:y1+pad, x0-pad:x1+pad] = padded
        uv_regions[name] = [(x0+.5)/size, 1-(y1-.5)/size, (x1-.5)/size, 1-(y0+.5)/size]
    images = {k: Image.fromarray(v) for k, v in images.items()}
    # JPEG for albedo only. Normal/ORM remain lossless PNG in the GLB.
    buffer = io.BytesIO()
    images["baseColor"].save(buffer, format="JPEG", quality=88, subsampling=0)
    buffer.seek(0)
    images["baseColor"] = Image.open(buffer)
    material = PBRMaterial(name="ScorchedNebraska", baseColorTexture=images["baseColor"],
                           normalTexture=images["normal"], metallicRoughnessTexture=images["roughness"],
                           metallicFactor=0., roughnessFactor=1., doubleSided=False)
    return material, uv_regions, images
