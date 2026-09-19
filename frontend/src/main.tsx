import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { InputsDemo } from './InputsDemo';
import './styles.css';

// Thin entry only. The real app shell (map, pipeline steps, skin) belongs to
// steps 12/13 — this mounts the step 03 + 04 inputs so they can be driven by
// hand against the live backend until that shell exists.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <InputsDemo />
  </StrictMode>,
);
