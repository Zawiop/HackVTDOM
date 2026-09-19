import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(cleanup);

// jsdom has no object-URL implementation; previews only need a unique string.
if (!URL.createObjectURL) {
  let n = 0;
  URL.createObjectURL = () => `blob:mock/${n++}`;
  URL.revokeObjectURL = () => {};
}
