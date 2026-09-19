import { Router } from 'express';
import multer from 'multer';
import { fetchMapillaryPhotos } from '../services/mapillary.js';
import {
  getSourcePhoto,
  UnsupportedPhotoTypeError,
  type UploadedFile,
} from '../services/photoInput.js';
import { ACCEPTED_MIME_TYPES } from '../services/photoStore.js';
import { BadRequestError, baseUrlFor, parseLatLng, parseNumber } from '../lib/http.js';

/**
 * Step 03 routes.
 *
 * The upload field is `multer.array`, not `multer.single` — spec 03 is explicit
 * that the input must accept "one or more photographs", and a single-file input
 * falls short of that line even if nobody uploads two.
 */

const MAX_FILES = 10;
const MAX_FILE_BYTES = 20 * 1024 * 1024;

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { files: MAX_FILES, fileSize: MAX_FILE_BYTES },
  fileFilter: (_req, file, cb) => {
    if (ACCEPTED_MIME_TYPES.includes(file.mimetype)) return cb(null, true);
    cb(new UnsupportedPhotoTypeError(file.mimetype));
  },
});

export const photosRouter = Router();

/**
 * POST /api/photos/source
 * multipart/form-data: photos[] (0..N files), lat?, lng?, radiusMeters?
 *
 * Runs both paths and returns everything usable. Zero photos back is a valid,
 * non-error response meaning "the user still needs to upload one".
 */
photosRouter.post('/source', upload.array('photos', MAX_FILES), async (req, res, next) => {
  try {
    const files = (req.files as Express.Multer.File[] | undefined) ?? [];
    const uploads: UploadedFile[] = files.map((f) => ({
      buffer: f.buffer,
      mimetype: f.mimetype,
      originalname: f.originalname,
      size: f.size,
    }));

    const body = req.body as Record<string, unknown>;
    const hasCoords = body.lat !== undefined && body.lng !== undefined;
    const coords = hasCoords ? parseLatLng(body) : undefined;

    const result = await getSourcePhoto({
      uploads,
      ...(coords ?? {}),
      baseUrl: baseUrlFor(req),
      ...(body.radiusMeters !== undefined
        ? { radiusMeters: parseNumber(body.radiusMeters, 'radiusMeters') }
        : {}),
    });

    res.json(result);
  } catch (err) {
    next(err);
  }
});

/**
 * GET /api/photos/mapillary?lat=&lng=&radiusMeters=
 * The convenience layer on its own, for a "look for a photo first" UI affordance.
 */
photosRouter.get('/mapillary', async (req, res, next) => {
  try {
    const { lat, lng } = parseLatLng(req.query as Record<string, unknown>);
    const radiusMeters =
      req.query.radiusMeters !== undefined
        ? parseNumber(req.query.radiusMeters, 'radiusMeters')
        : undefined;

    const result = await fetchMapillaryPhotos(lat, lng, { ...(radiusMeters ? { radiusMeters } : {}) });

    res.json({
      attempted: result.attempted,
      photos: result.photos,
      attempts: result.attempts,
      bbox: result.bbox,
      // Zero photos is the expected common case, never an error state.
      requiresManualUpload: result.photos.length === 0,
    });
  } catch (err) {
    next(err);
  }
});

/** Upload limits, so the frontend input can mirror them without hardcoding. */
photosRouter.get('/constraints', (_req, res) => {
  res.json({
    maxFiles: MAX_FILES,
    maxFileBytes: MAX_FILE_BYTES,
    acceptedMimeTypes: ACCEPTED_MIME_TYPES,
    multiple: true,
  });
});

export { BadRequestError };
