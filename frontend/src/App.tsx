import EntryPanel from "./entry/EntryPanel";
import MapShell from "./MapShell";

/**
 * Composition root. The map (steps 09-12) is the whole surface; the address
 * entry pipeline (steps 01-02) mounts inside its left panel so the two read as
 * one app rather than two stacked ones.
 */
export default function App() {
  return <MapShell entrySlot={<EntryPanel />} />;
}
