import type { Request } from 'express';

/** Absolute origin for this request, used to build public upload URLs. */
export function baseUrlFor(req: Request): string {
  const proto = (req.headers['x-forwarded-proto'] as string | undefined) ?? req.protocol;
  const host = req.get('host') ?? `localhost`;
  return `${proto}://${host}`;
}

/** Parse a required finite number from a query/body value. */
export function parseNumber(value: unknown, field: string): number {
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) throw new BadRequestError(`"${field}" must be a finite number.`);
  return n;
}

export function parseLatLng(source: Record<string, unknown>): { lat: number; lng: number } {
  const lat = parseNumber(source.lat, 'lat');
  const lng = parseNumber(source.lng, 'lng');
  if (lat < -90 || lat > 90) throw new BadRequestError('"lat" must be between -90 and 90.');
  if (lng < -180 || lng > 180) throw new BadRequestError('"lng" must be between -180 and 180.');
  return { lat, lng };
}

export class BadRequestError extends Error {
  readonly status = 400;
  constructor(message: string) {
    super(message);
    this.name = 'BadRequestError';
  }
}
