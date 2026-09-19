import { useEffect, useId, useState } from 'react';
import { fetchWorldStates } from '../api/client';
import type {
  WorldState,
  WorldStateListResponse,
  WorldStateOption,
  WorldStateSelection,
} from '../types/contract';

/**
 * World State selector (spec 04).
 *
 * Framed as a Present <-> Collapsed spectrum rather than a filter picker, per
 * the spec's framing note: same five backend strings, same code path, but it
 * reads as world-building instead of image-filtering.
 *
 * The component never holds a prompt string. It sends an enum, or — if the user
 * writes their own description — it sends that text, which REPLACES the locked
 * string on the server rather than appending to it.
 */

export interface WorldStateSelectorProps {
  onChange?: (selection: WorldStateSelection) => void;
  /** Injected in tests so the component doesn't need the network. */
  loadStates?: () => Promise<Pick<WorldStateListResponse, 'states' | 'spectrum'>>;
}

export function WorldStateSelector({ onChange, loadStates }: WorldStateSelectorProps) {
  const groupId = useId();
  const [options, setOptions] = useState<WorldStateOption[]>([]);
  const [spectrum, setSpectrum] = useState({ from: 'Present', to: 'Collapsed' });
  const [selected, setSelected] = useState<WorldState | null>(null);
  const [override, setOverride] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    (loadStates ?? fetchWorldStates)()
      .then((res) => {
        if (!live) return;
        const sorted = [...res.states].sort((a, b) => a.spectrumPosition - b.spectrumPosition);
        setOptions(sorted);
        setSpectrum(res.spectrum);
        setSelected((cur) => cur ?? sorted[0]?.id ?? null);
      })
      .catch((err: Error) => live && setLoadError(err.message));
    return () => {
      live = false;
    };
  }, [loadStates]);

  const trimmedOverride = override.trim();
  const usingOverride = trimmedOverride.length > 0;

  useEffect(() => {
    onChange?.({
      worldState: selected,
      freeformOverride: usingOverride ? trimmedOverride : null,
    });
  }, [selected, trimmedOverride, usingOverride, onChange]);

  if (loadError) {
    return <p role="alert">Couldn’t load world states: {loadError}</p>;
  }

  return (
    <section className="world-state" aria-labelledby={`${groupId}-heading`}>
      <h2 id={`${groupId}-heading`}>World State</h2>

      <div className="world-state__spectrum" aria-hidden="true">
        <span>{spectrum.from}</span>
        <span className="world-state__rule" />
        <span>{spectrum.to}</span>
      </div>

      <div
        className="world-state__options"
        role="radiogroup"
        aria-label={`${spectrum.from} to ${spectrum.to}`}
        data-testid="world-state-options"
      >
        {options.map((option) => (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={selected === option.id}
            // The locked preset is still what gets sent if the box is empty; when
            // an override is typed, these are visibly superseded rather than gone.
            className={usingOverride ? 'is-superseded' : undefined}
            onClick={() => setSelected(option.id)}
            data-testid={`world-state-${option.id}`}
          >
            <strong>{option.label}</strong>
            <span>{option.blurb}</span>
          </button>
        ))}
      </div>

      <label className="world-state__override" htmlFor={`${groupId}-override`}>
        <span>Or describe it yourself</span>
        <textarea
          id={`${groupId}-override`}
          rows={3}
          value={override}
          placeholder="Describe the transformation in your own words…"
          onChange={(e) => setOverride(e.target.value)}
          data-testid="world-state-override"
        />
      </label>

      <p className="world-state__note" data-testid="world-state-note">
        {usingOverride
          ? 'Your description replaces the preset for this generation.'
          : 'Using the preset description for the selected world state.'}
      </p>
    </section>
  );
}

export default WorldStateSelector;
