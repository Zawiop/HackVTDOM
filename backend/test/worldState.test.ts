import { describe, expect, it } from 'vitest';
import {
  getPresetPrompt,
  getWorldStatePrompt,
  InvalidWorldStateError,
  isWorldState,
  WORLD_STATES,
  WORLD_STATE_OPTIONS,
} from '../src/services/worldState.js';

describe('getWorldStatePrompt — preset path (spec 04)', () => {
  it('exposes exactly the five locked states', () => {
    expect([...WORLD_STATES]).toEqual([
      'reclaimed',
      'flooded',
      'scorched',
      'buried',
      'petrified',
    ]);
  });

  it.each(WORLD_STATES)('returns the locked string for "%s"', (state) => {
    const result = getWorldStatePrompt({ worldState: state });
    expect(result.source).toBe('preset');
    expect(result.worldState).toBe(state);
    expect(result.prompt).toBe(getPresetPrompt(state));
  });

  it('returns full descriptive paragraphs, not short tags', () => {
    for (const state of WORLD_STATES) {
      const prompt = getPresetPrompt(state);
      // Spec 04: "a complete descriptive paragraph, not a short tag".
      expect(prompt.length).toBeGreaterThan(400);
      expect(prompt.split(/[.!?]\s/).length).toBeGreaterThanOrEqual(5);
    }
  });

  it('carries the Scorched Nebraska visual grammar in every preset', () => {
    for (const state of WORLD_STATES) {
      const prompt = getPresetPrompt(state).toLowerCase();
      expect(prompt).toContain('god rays');
      expect(prompt).toContain('amber');
      expect(prompt).toContain('desaturated');
      // Placement in step 08 assumes the same footprint, so the prompt must say so.
      expect(prompt).toContain('footprint');
      expect(prompt).toContain('photorealistic');
    }
  });

  it('gives each state a distinct prompt', () => {
    const prompts = WORLD_STATES.map(getPresetPrompt);
    expect(new Set(prompts).size).toBe(WORLD_STATES.length);
  });

  it('is deterministic — the same enum always yields the same string', () => {
    expect(getWorldStatePrompt({ worldState: 'flooded' }).prompt).toBe(
      getWorldStatePrompt({ worldState: 'flooded' }).prompt,
    );
  });

  it('rejects an unknown state rather than guessing one', () => {
    expect(() => getWorldStatePrompt({ worldState: 'melted' })).toThrow(InvalidWorldStateError);
    expect(() => getWorldStatePrompt({})).toThrow(InvalidWorldStateError);
    expect(() => getWorldStatePrompt({ worldState: '' })).toThrow(InvalidWorldStateError);
  });

  it('isWorldState guards correctly', () => {
    expect(isWorldState('buried')).toBe(true);
    expect(isWorldState('BURIED')).toBe(false);
    expect(isWorldState(null)).toBe(false);
  });
});

describe('getWorldStatePrompt — override path (spec 04)', () => {
  const custom = 'A building made entirely of stacked vintage televisions, all switched on.';

  it('REPLACES the locked string rather than appending to it', () => {
    const result = getWorldStatePrompt({ worldState: 'scorched', freeformOverride: custom });

    expect(result.source).toBe('override');
    expect(result.prompt).toBe(custom);
    // The critical assertion: no trace of the preset survives.
    expect(result.prompt).not.toContain(getPresetPrompt('scorched'));
    expect(result.prompt.length).toBe(custom.length);
  });

  it('works with no preset selected at all', () => {
    const result = getWorldStatePrompt({ freeformOverride: custom });
    expect(result.prompt).toBe(custom);
    expect(result.worldState).toBeNull();
  });

  it('remembers which preset was displaced, for the history record', () => {
    expect(getWorldStatePrompt({ worldState: 'buried', freeformOverride: custom }).worldState)
      .toBe('buried');
  });

  it('treats whitespace-only override as absent and falls back to the preset', () => {
    const result = getWorldStatePrompt({ worldState: 'flooded', freeformOverride: '   \n  ' });
    expect(result.source).toBe('preset');
    expect(result.prompt).toBe(getPresetPrompt('flooded'));
  });

  it('trims the override before sending it downstream', () => {
    expect(getWorldStatePrompt({ freeformOverride: `  ${custom}  ` }).prompt).toBe(custom);
  });

  it('does not require a valid preset when an override is present', () => {
    expect(() => getWorldStatePrompt({ worldState: 'nonsense', freeformOverride: custom })).not.toThrow();
  });
});

describe('UI options never leak the locked prompt text', () => {
  it('exposes one option per state with display copy only', () => {
    expect(WORLD_STATE_OPTIONS).toHaveLength(WORLD_STATES.length);
    for (const option of WORLD_STATE_OPTIONS) {
      const serialised = JSON.stringify(option);
      expect(serialised).not.toContain('god rays');
      expect(option.blurb.length).toBeLessThan(120);
      expect(option.blurb).not.toBe(getPresetPrompt(option.id));
    }
  });

  it('orders the spectrum Present -> Collapsed', () => {
    const positions = WORLD_STATE_OPTIONS.map((o) => o.spectrumPosition);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
  });
});
