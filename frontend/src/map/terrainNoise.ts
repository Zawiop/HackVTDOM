/**
 * Deterministic noise and colour helpers for the terrain.
 *
 * Everything here is a pure function of its seed. Terrain that re-randomised
 * per frame would boil and shimmer while the map pans, so no Math.random()
 * appears anywhere in the terrain pipeline.
 */

export type Rgba = [number, number, number, number];

/** 32-bit hash of a string — the entry point for every seeded value below. */
export function hashString(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** A stateful 0..1 generator, for scattering features. */
export function seededRandom(seed: string): () => number {
  let h = hashString(seed) || 1;
  return () => {
    h ^= h << 13;
    h ^= h >>> 17;
    h ^= h << 5;
    h >>>= 0;
    return (h % 1000000) / 1000000;
  };
}

/** Stable pseudo-random in -1..1 for an integer lattice point. */
function latticeValue(ix: number, iy: number, salt: number): number {
  let h = Math.imul(ix, 374761393) ^ Math.imul(iy, 668265263) ^ salt;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  h ^= h >>> 16;
  return ((h >>> 0) % 2000000) / 1000000 - 1;
}

const smooth = (t: number) => t * t * (3 - 2 * t);
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/** Value noise in -1..1, smooth between lattice points. */
export function valueNoise2D(x: number, y: number, salt: number): number {
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const fx = smooth(x - x0);
  const fy = smooth(y - y0);
  const top = lerp(latticeValue(x0, y0, salt), latticeValue(x0 + 1, y0, salt), fx);
  const bot = lerp(
    latticeValue(x0, y0 + 1, salt),
    latticeValue(x0 + 1, y0 + 1, salt),
    fx,
  );
  return lerp(top, bot, fy);
}

/**
 * Several octaves of value noise.
 *
 * One octave alone gives smooth rolling blobs that read as a gradient rather
 * than ground; the finer octaves are what make it look like terrain.
 */
export function fractalNoise2D(
  x: number,
  y: number,
  salt: number,
  octaves = 3,
): number {
  let total = 0;
  let amplitude = 1;
  let frequency = 1;
  let norm = 0;
  for (let i = 0; i < octaves; i++) {
    total += valueNoise2D(x * frequency, y * frequency, salt + i * 1013) * amplitude;
    norm += amplitude;
    amplitude *= 0.5;
    frequency *= 2.07; // not exactly 2, to avoid visible lattice repetition
  }
  return total / norm;
}

export function mixColor(a: Rgba, b: Rgba, t: number): Rgba {
  const k = Math.max(0, Math.min(1, t));
  return [
    Math.round(lerp(a[0], b[0], k)),
    Math.round(lerp(a[1], b[1], k)),
    Math.round(lerp(a[2], b[2], k)),
    Math.round(lerp(a[3], b[3], k)),
  ];
}

/** Scale only the alpha channel, for fading ground out at the patch edge. */
export function withAlpha(color: Rgba, factor: number): Rgba {
  return [color[0], color[1], color[2], Math.round(color[3] * Math.max(0, Math.min(1, factor)))];
}

/** Smooth 0..1 ramp, used for the falloff at the edge of a patch. */
export function smoothstep(edge0: number, edge1: number, x: number): number {
  if (edge1 === edge0) return x < edge0 ? 0 : 1;
  const t = Math.max(0, Math.min(1, (x - edge0) / (edge1 - edge0)));
  return smooth(t);
}
