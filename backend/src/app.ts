import express, { type ErrorRequestHandler } from 'express';
import cors from 'cors';
import multer from 'multer';
import { photosRouter } from './routes/photos.js';
import { worldStateRouter } from './routes/worldState.js';
import { placementRouter } from './routes/placement.js';
import { UnsupportedPhotoTypeError } from './services/photoInput.js';
import { BadRequestError } from './lib/http.js';
import { PUBLIC_UPLOAD_PATH, UPLOAD_DIR } from './services/photoStore.js';

/**
 * Route registry.
 *
 * Four people are building routes into this one API. Each module owns exactly
 * one file under src/routes/ and adds exactly one line here, so two teammates
 * adding routes the same afternoon touch one line each instead of fighting over
 * an app.ts full of app.use() calls.
 *
 *   steps 01/02  -> geocode + footprint   (teammate)
 *   step  03     -> photosRouter          (this module)
 *   step  04     -> worldStateRouter      (this module)
 *   steps 05-07  -> image edit + mesh     (teammate)
 *   step  08     -> placementRouter       (this module)
 */
const ROUTES: Array<[path: string, router: express.Router]> = [
  ['/api/photos', photosRouter],
  ['/api/world-states', worldStateRouter],
  ['/api/placement', placementRouter],
];

export function createApp(): express.Express {
  const app = express();

  app.use(cors());
  app.use(express.json({ limit: '2mb' }));
  app.use(express.urlencoded({ extended: true }));

  // Uploaded source photos, until step 11 moves storage to Supabase.
  app.use(PUBLIC_UPLOAD_PATH, express.static(UPLOAD_DIR));

  app.get('/api/health', (_req, res) => {
    res.json({ ok: true, service: 'scorched-nebraska-api' });
  });

  for (const [path, router] of ROUTES) app.use(path, router);

  app.use(errorHandler);
  return app;
}

const errorHandler: ErrorRequestHandler = (err, _req, res, _next) => {
  if (err instanceof UnsupportedPhotoTypeError) {
    res.status(415).json({ error: err.message });
    return;
  }
  if (err instanceof BadRequestError) {
    res.status(400).json({ error: err.message });
    return;
  }
  if (err instanceof multer.MulterError) {
    res.status(400).json({ error: `Upload rejected: ${err.message}`, code: err.code });
    return;
  }
  console.error('[api] unhandled error', err);
  res.status(500).json({ error: 'Internal server error' });
};
