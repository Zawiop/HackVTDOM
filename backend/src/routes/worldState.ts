import { Router } from 'express';
import {
  getWorldStatePrompt,
  InvalidWorldStateError,
  WORLD_STATES,
  WORLD_STATE_OPTIONS,
} from '../services/worldState.js';

/**
 * Step 04 routes.
 *
 * Note what is NOT here: any endpoint that returns the five locked prompt
 * strings to the browser, and any endpoint that accepts prompt text for the
 * preset path. Spec 04 requires those strings stay server-side so output is
 * consistent regardless of which building or user triggers them.
 */
export const worldStateRouter = Router();

/** GET /api/world-states — spectrum options for the UI. Labels and blurbs only. */
worldStateRouter.get('/', (_req, res) => {
  res.json({
    states: WORLD_STATE_OPTIONS,
    order: WORLD_STATES,
    spectrum: { from: 'Present', to: 'Collapsed' },
  });
});

/**
 * POST /api/world-states/resolve
 * body: { worldState?: WorldState, freeformOverride?: string }
 *
 * Returns the single string step 05 sends to the image model. A freeform
 * override replaces the preset outright — it is never appended to it.
 */
worldStateRouter.post('/resolve', (req, res, next) => {
  try {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const result = getWorldStatePrompt({
      worldState: typeof body.worldState === 'string' ? body.worldState : null,
      freeformOverride:
        typeof body.freeformOverride === 'string' ? body.freeformOverride : null,
    });
    res.json(result);
  } catch (err) {
    if (err instanceof InvalidWorldStateError) {
      res.status(400).json({ error: err.message, accepted: WORLD_STATES });
      return;
    }
    next(err);
  }
});
