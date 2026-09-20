import { NEUTRAL, PROFILES } from "../map/terrainProfiles";

/**
 * The colour the map will actually paint the ground for a World State.
 *
 * Read off the same `PROFILES` the terrain layer uses, rather than a second
 * hand-picked set of swatches: retune the flooded palette for the map and the
 * picker follows it. A picker whose colours have quietly drifted from the
 * thing it picks is worse than one with no colours at all.
 */
function css([r, g, b]: readonly number[], alpha = 1): string {
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function swatchFor(worldState: string | null | undefined): {
  core: string;
  mid: string;
  gradient: string;
} {
  const profile = (worldState && PROFILES[worldState]) || NEUTRAL;
  const core = css(profile.core);
  const mid = css(profile.mid);
  return { core, mid, gradient: `linear-gradient(145deg, ${mid}, ${core})` };
}

/** Present → collapsed, the order the spectrum reads in. */
export const SPECTRUM_ORDER = ["reclaimed", "flooded", "scorched", "buried", "petrified"];

export function spectrumIndex(worldState: string | null | undefined): number {
  const at = SPECTRUM_ORDER.indexOf(String(worldState));
  return at === -1 ? SPECTRUM_ORDER.length : at;
}
