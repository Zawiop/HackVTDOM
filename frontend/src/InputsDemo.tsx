import { useCallback, useState } from 'react';
import { PhotoInput } from './components/PhotoInput';
import { WorldStateSelector } from './components/WorldStateSelector';
import { resolveWorldStatePrompt, submitSourcePhotos } from './lib/api';
import type { SourcePhoto, WorldStateSelection } from './types/api';

/**
 * Manual harness for the step 03 and step 04 inputs against the live backend.
 * Not the app shell — that's steps 12/13.
 */
export function InputsDemo() {
  // Burruss Hall. Verified Mapillary coverage; see markdown_files/03-photo-input.md.
  const [coords] = useState({ lat: 37.2284, lng: -80.4234 });
  const [files, setFiles] = useState<File[]>([]);
  const [mapillaryPick, setMapillaryPick] = useState<SourcePhoto | null>(null);
  const [selection, setSelection] = useState<WorldStateSelection>({
    worldState: 'reclaimed',
    freeformOverride: null,
  });
  const [result, setResult] = useState<string>('');
  const [busy, setBusy] = useState(false);

  const onPhotos = useCallback(
    (s: { files: File[]; mapillary: SourcePhoto | null }) => {
      setFiles(s.files);
      setMapillaryPick(s.mapillary);
    },
    [],
  );

  async function submit() {
    setBusy(true);
    try {
      const [photos, prompt] = await Promise.all([
        submitSourcePhotos({ files, ...coords }),
        resolveWorldStatePrompt(selection),
      ]);
      setResult(JSON.stringify({ photos, prompt, mapillaryPick }, null, 2));
    } catch (err) {
      setResult(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="app">
      <header>
        <h1>Scorched Nebraska</h1>
        <p>Steps 03 + 04 — source photograph and world state.</p>
      </header>

      <PhotoInput lat={coords.lat} lng={coords.lng} onChange={onPhotos} />
      <WorldStateSelector onChange={setSelection} />

      <button type="button" onClick={submit} disabled={busy}>
        {busy ? 'Working…' : 'Resolve inputs'}
      </button>

      {result && <pre className="app__result">{result}</pre>}

      <footer>© OpenStreetMap contributors · Imagery © Mapillary contributors</footer>
    </main>
  );
}
