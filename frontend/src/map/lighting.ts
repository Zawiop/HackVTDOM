import { AmbientLight, DirectionalLight, LightingEffect } from "@deck.gl/core";

/**
 * Scene lighting for the building meshes.
 *
 * These meshes arrive from the image-to-3D step with lighting already baked
 * into their texture, so they want *shaping*, not illumination. Strong
 * directional light blows the texture out to white, and deck.gl's shadow pass
 * on an overlaid MapboxOverlay leaves hard artifacts across the mesh itself —
 * both were tried and looked considerably worse than the flat default.
 *
 * So: ambient carries almost all of it, with two weak directionals that only
 * separate the facades enough to read the roofline. `direction` points *from*
 * the light *towards* the scene, so a negative Z shines downward.
 */

const ambient = new AmbientLight({
  color: [255, 251, 244],
  intensity: 1.05,
});

// Gentle key from the south-west, just enough to tell two facades apart.
const key = new DirectionalLight({
  color: [255, 247, 232],
  intensity: 0.55,
  direction: [-0.7, -0.6, -1.1],
});

// Cool sky fill so the away-facing side does not read as a flat black mass.
const fill = new DirectionalLight({
  color: [214, 226, 242],
  intensity: 0.3,
  direction: [0.9, 0.7, -0.45],
});

export function createBuildingLighting(): LightingEffect {
  return new LightingEffect({ ambient, key, fill });
}
