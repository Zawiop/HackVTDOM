import 'dotenv/config';

/**
 * Central env access. Nothing else in the codebase should read process.env
 * directly, so a missing key surfaces here with a useful message instead of
 * as `undefined` three layers down inside an HTTP call.
 */

function optional(key: string): string | undefined {
  const raw = process.env[key];
  if (raw === undefined) return undefined;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

export const env = {
  port: Number(optional('PORT') ?? 8787),

  /** Mapillary is a convenience layer (spec 03 path B) — absent token just disables it. */
  mapillaryAccessToken: optional('MAPILLARY_ACCESS_TOKEN'),

  /** Nominatim's usage policy rejects generic library user agents (spec 01). */
  nominatimUserAgent:
    optional('NOMINATIM_USER_AGENT') ?? 'ScorchedNebraskaVTHacks/1.0',
} as const;

export function hasMapillary(): boolean {
  return Boolean(env.mapillaryAccessToken);
}
