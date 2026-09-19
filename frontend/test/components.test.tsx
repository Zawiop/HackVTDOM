import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PhotoInput } from '../src/components/PhotoInput';
import { WorldStateSelector } from '../src/components/WorldStateSelector';
import type { WorldStateOption } from '../src/types/api';

const png = (name: string) =>
  new File([new Uint8Array([137, 80, 78, 71])], name, { type: 'image/png' });

beforeEach(() => {
  // No component under test should need the network unless it says so.
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ photos: [] }))));
});

describe('PhotoInput — spec 03 path A', () => {
  it('renders a MULTI-file input, not a single-file one', () => {
    render(<PhotoInput />);
    const input = screen.getByTestId('photo-file-input') as HTMLInputElement;
    expect(input.multiple).toBe(true);
    expect(input.type).toBe('file');
  });

  it('accepts several photos at once and keeps them all', async () => {
    const onChange = vi.fn();
    render(<PhotoInput onChange={onChange} />);

    await userEvent.upload(screen.getByTestId('photo-file-input'), [
      png('front.png'),
      png('side.png'),
      png('rear.png'),
    ]);

    const previews = within(screen.getByTestId('photo-previews')).getAllByRole('listitem');
    expect(previews).toHaveLength(3);

    await waitFor(() => {
      const last = onChange.mock.calls.at(-1)![0];
      expect(last.files.map((f: File) => f.name)).toEqual(['front.png', 'side.png', 'rear.png']);
    });
  });

  it('accumulates across separate picks rather than replacing', async () => {
    render(<PhotoInput />);
    const input = screen.getByTestId('photo-file-input');
    await userEvent.upload(input, [png('a.png')]);
    await userEvent.upload(input, [png('b.png')]);
    expect(within(screen.getByTestId('photo-previews')).getAllByRole('listitem')).toHaveLength(2);
  });

  it('lets a photo be removed again', async () => {
    render(<PhotoInput />);
    await userEvent.upload(screen.getByTestId('photo-file-input'), [png('a.png'), png('b.png')]);
    await userEvent.click(screen.getByLabelText('Remove a.png'));
    expect(within(screen.getByTestId('photo-previews')).getAllByRole('listitem')).toHaveLength(1);
  });

  it('filters unsupported types at the input via accept', () => {
    render(<PhotoInput />);
    const input = screen.getByTestId('photo-file-input') as HTMLInputElement;
    expect(input.accept).toContain('image/jpeg');
    expect(input.accept).toContain('image/png');
    expect(input.accept).not.toContain('text/plain');
  });

  it('rejects an unsupported type dropped in, with a visible reason', async () => {
    // `accept` only filters the file picker. Drag-and-drop bypasses it entirely,
    // so this is the path where junk can actually arrive.
    render(<PhotoInput />);
    const drop = screen.getByText(/drop photos here/i).closest('label')!;

    fireEvent.drop(drop, {
      dataTransfer: { files: [new File(['x'], 'notes.txt', { type: 'text/plain' })] },
    });

    expect(await screen.findByRole('alert')).toHaveTextContent(/unsupported type/i);
    expect(screen.queryByTestId('photo-previews')).toBeNull();
  });

  it('accepts valid photos dropped in', async () => {
    render(<PhotoInput />);
    const drop = screen.getByText(/drop photos here/i).closest('label')!;

    fireEvent.drop(drop, { dataTransfer: { files: [png('dropped.png'), png('dropped2.png')] } });

    const previews = await screen.findByTestId('photo-previews');
    expect(within(previews).getAllByRole('listitem')).toHaveLength(2);
  });

  it('says a photo is still required until one is supplied', async () => {
    render(<PhotoInput />);
    expect(screen.getByTestId('upload-required')).toBeTruthy();
    await userEvent.upload(screen.getByTestId('photo-file-input'), [png('a.png')]);
    expect(screen.queryByTestId('upload-required')).toBeNull();
  });
});

describe('PhotoInput — spec 03 path B (convenience layer)', () => {
  it('shows nearby imagery as optional suggestions when coverage exists', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            photos: [
              {
                source: 'mapillary',
                id: '1137417950117930',
                url: 'https://example.test/a.jpg',
                distanceMeters: 23.1,
                capturedAt: '2024-10-11T00:00:00.000Z',
              },
            ],
          }),
        ),
      ),
    );

    render(<PhotoInput lat={37.2284} lng={-80.4234} />);
    const strip = await screen.findByTestId('mapillary-suggestions');
    expect(within(strip).getByText(/23 m away/)).toBeTruthy();
  });

  it('renders NO error state when there is no coverage — it just shows nothing', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ photos: [] }))));

    render(<PhotoInput lat={47.7} lng={-87.5} />);
    await waitFor(() => expect(screen.queryByText(/checking for/i)).toBeNull());

    expect(screen.queryByTestId('mapillary-suggestions')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
    // The required path is what the user is left with — as the spec intends.
    expect(screen.getByTestId('upload-required')).toBeTruthy();
  });

  it('stays silent when the lookup itself fails, too', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new Error('network down'))));
    render(<PhotoInput lat={37.2284} lng={-80.4234} />);
    await waitFor(() => expect(screen.queryByText(/checking for/i)).toBeNull());
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('does not look anything up without a coordinate', () => {
    const spy = vi.fn();
    vi.stubGlobal('fetch', spy);
    render(<PhotoInput />);
    expect(spy).not.toHaveBeenCalled();
  });
});

describe('WorldStateSelector — spec 04', () => {
  const STATES: WorldStateOption[] = [
    { id: 'reclaimed', label: 'Reclaimed', blurb: 'Nature takes it back.', spectrumPosition: 0.2 },
    { id: 'flooded', label: 'Flooded', blurb: 'Permanent water.', spectrumPosition: 0.4 },
    { id: 'scorched', label: 'Scorched', blurb: 'Long after the burn.', spectrumPosition: 0.6 },
    { id: 'buried', label: 'Buried', blurb: 'Swallowed by silt.', spectrumPosition: 0.8 },
    { id: 'petrified', label: 'Petrified', blurb: 'Turned to stone.', spectrumPosition: 1.0 },
  ];
  const loadStates = async () => ({ states: STATES, spectrum: { from: 'Present', to: 'Collapsed' } });

  it('renders the five states as a Present -> Collapsed spectrum', async () => {
    render(<WorldStateSelector loadStates={loadStates} />);
    const group = await screen.findByTestId('world-state-options');
    const buttons = within(group).getAllByRole('radio');

    expect(buttons.map((b) => b.textContent)).toEqual([
      'ReclaimedNature takes it back.',
      'FloodedPermanent water.',
      'ScorchedLong after the burn.',
      'BuriedSwallowed by silt.',
      'PetrifiedTurned to stone.',
    ]);
    expect(screen.getByText('Present')).toBeTruthy();
    expect(screen.getByText('Collapsed')).toBeTruthy();
  });

  it('emits the enum only — never prompt text', async () => {
    const onChange = vi.fn();
    render(<WorldStateSelector loadStates={loadStates} onChange={onChange} />);
    await screen.findByTestId('world-state-options');

    await userEvent.click(screen.getByTestId('world-state-scorched'));

    await waitFor(() =>
      expect(onChange.mock.calls.at(-1)![0]).toEqual({
        worldState: 'scorched',
        freeformOverride: null,
      }),
    );
  });

  it('a freeform override REPLACES the preset rather than adding to it', async () => {
    const onChange = vi.fn();
    render(<WorldStateSelector loadStates={loadStates} onChange={onChange} />);
    await screen.findByTestId('world-state-options');

    await userEvent.click(screen.getByTestId('world-state-flooded'));
    await userEvent.type(screen.getByTestId('world-state-override'), 'Overgrown with black roses.');

    await waitFor(() => {
      const last = onChange.mock.calls.at(-1)![0];
      expect(last.freeformOverride).toBe('Overgrown with black roses.');
      // The preset id is retained for the history record, but the server will
      // send the override text — never a concatenation of the two.
      expect(last.worldState).toBe('flooded');
    });

    expect(screen.getByTestId('world-state-note')).toHaveTextContent(/replaces the preset/i);
  });

  it('falls back to the preset when the override is cleared or whitespace', async () => {
    const onChange = vi.fn();
    render(<WorldStateSelector loadStates={loadStates} onChange={onChange} />);
    await screen.findByTestId('world-state-options');

    const box = screen.getByTestId('world-state-override');
    await userEvent.type(box, '   ');

    await waitFor(() => expect(onChange.mock.calls.at(-1)![0].freeformOverride).toBeNull());
    expect(screen.getByTestId('world-state-note')).toHaveTextContent(/using the preset/i);
  });

  it('never holds a locked prompt string in the DOM', async () => {
    render(<WorldStateSelector loadStates={loadStates} />);
    await screen.findByTestId('world-state-options');
    expect(document.body.textContent).not.toMatch(/god rays/i);
  });
});
