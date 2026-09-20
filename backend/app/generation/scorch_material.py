"""Surface-only soot and ash. No resampling, masking or geometry modification."""
import numpy as np
from PIL import Image, ImageFilter


def scorch_surface(image: Image.Image, strength: float = .65) -> Image.Image:
    """Keep source detail/alpha; add neutral, irregular material-local weathering.

    This deterministic approximation is not semantic burn simulation. Apply to
    material textures, not to geometry or an alpha mask defining missing faces.
    """
    if not 0 <= strength <= 1:
        raise ValueError("strength must be between zero and one")
    rgba = np.array(image.convert("RGBA"))
    h, w = rgba.shape[:2]
    rgb = rgba[:, :, :3].astype(np.float32)/255
    gray = rgb @ np.array([.2126, .7152, .0722], np.float32)
    # Fixed seed and smooth fields avoid a uniform grade and repeated stripes.
    rng = np.random.default_rng(1945)
    def field(width, height):
        noise = Image.fromarray(rng.integers(0, 256, (height, width), dtype=np.uint8))
        return np.array(noise.resize((w, h), Image.Resampling.BICUBIC).filter(
            ImageFilter.GaussianBlur(max(1, min(w, h)/150))), dtype=np.float32)/255
    patches = field(13, 13)
    streaks = field(39, 5)
    soot = np.clip((patches*.7+streaks*.3-.35)*1.8, 0, .8)*strength
    ash = np.clip((field(23, 19)-.63)*1.5, 0, .3)*strength
    # Preserve high-frequency masonry and window detail beneath neutral soot.
    desaturated = rgb*(1-.35*soot[:, :, None])+gray[:, :, None]*(.35*soot[:, :, None])
    weathered = desaturated*(1-.8*soot[:, :, None])
    weathered = weathered*(1-ash[:, :, None])+np.array([.55, .55, .53])*ash[:, :, None]
    rgba[:, :, :3] = np.uint8(np.clip(weathered*255, 0, 255))
    return Image.fromarray(rgba)
