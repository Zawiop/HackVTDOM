import { Router } from 'express';
import {
  computePlacementTransform,
  PlacementInputError,
} from '../services/placement.js';
import { MeshParseError } from '../geo/mesh.js';
import type { FootprintPolygon, MeshInput } from '../types/placement.js';
import { BadRequestError } from '../lib/http.js';

/**
 * Step 08 route.
 *
 * Takes step 02's footprint result (including the neighbours it already
 * fetched) and step 07's normalized mesh, and returns the transform record.
 * Nothing here calls Overpass — spec 08 requires the neighbours be reused, not
 * re-fetched.
 */
export const placementRouter = Router();

interface PlacementRequestBody {
  footprint?: {
    polygon?: FootprintPolygon;
    /** Accepted as an alias: step 02 may hand back a bare geometry array. */
    geometry?: FootprintPolygon['geometry'];
    neighbors?: FootprintPolygon[];
    footprintWidthMeters?: number;
    footprintDepthMeters?: number;
    longestEdgeBearingDegrees?: number;
    confidence?: 'high' | 'low';
  };
  mesh?: MeshInput & { bytesBase64?: string };
  options?: Record<string, number>;
}

placementRouter.post('/', async (req, res, next) => {
  try {
    const body = (req.body ?? {}) as PlacementRequestBody;

    const footprintInput = body.footprint;
    if (!footprintInput) throw new BadRequestError('Body needs a "footprint" object.');

    const polygon =
      footprintInput.polygon ??
      (footprintInput.geometry ? { geometry: footprintInput.geometry } : undefined);
    if (!polygon?.geometry?.length) {
      throw new BadRequestError('Body needs "footprint.polygon.geometry" — a lat/lng ring.');
    }

    const mesh = body.mesh;
    if (!mesh) throw new BadRequestError('Body needs a "mesh" object.');

    let decoded: Buffer | undefined;
    if (mesh.bytesBase64 !== undefined) {
      decoded = Buffer.from(mesh.bytesBase64, 'base64');
      // Buffer.from silently yields an empty buffer for junk base64, which
      // would otherwise fall through to the (probably absent) path and surface
      // as a confusing file-not-found.
      if (decoded.byteLength === 0) {
        throw new BadRequestError('"mesh.bytesBase64" decoded to zero bytes.');
      }
    }

    const meshInput: MeshInput = { ...mesh, ...(decoded ? { bytes: decoded } : {}) };

    const transform = await computePlacementTransform({
      footprint: {
        polygon,
        ...(footprintInput.neighbors ? { neighbors: footprintInput.neighbors } : {}),
        ...(footprintInput.footprintWidthMeters !== undefined
          ? { footprintWidthMeters: footprintInput.footprintWidthMeters }
          : {}),
        ...(footprintInput.footprintDepthMeters !== undefined
          ? { footprintDepthMeters: footprintInput.footprintDepthMeters }
          : {}),
        ...(footprintInput.longestEdgeBearingDegrees !== undefined
          ? { longestEdgeBearingDegrees: footprintInput.longestEdgeBearingDegrees }
          : {}),
        ...(footprintInput.confidence ? { confidence: footprintInput.confidence } : {}),
      },
      mesh: meshInput,
      ...(body.options ? { options: body.options } : {}),
    });

    res.json(transform);
  } catch (err) {
    if (err instanceof PlacementInputError || err instanceof MeshParseError) {
      res.status(422).json({ error: err.message, kind: err.name });
      return;
    }
    next(err);
  }
});
