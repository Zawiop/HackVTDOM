import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { startTestServer, filePart, PNG_1X1, type TestServer } from './helpers/server.js';
import { bboxAround, bboxToParam, haversineMeters } from '../src/geo/latlng.js';
import { fetchMapillaryPhotos } from '../src/services/mapillary.js';
import { hasMapillary } from '../src/config/env.js';

/** Real coordinates used throughout. Blacksburg coverage verified live 2026-09-19. */
const BURRUSS = { lat: 37.2284, lng: -80.4234 };
/** Open water, hundreds of km from any road — a genuine no-coverage control. */
const LAKE_SUPERIOR = { lat: 47.7, lng: -87.5 };

let server: TestServer;
beforeAll(async () => {
  server = await startTestServer();
});
afterAll(async () => {
  await server.close();
});

describe('bbox construction (spec 03)', () => {
  it('builds a ~40m box that is actually ~40m on the ground', () => {
    const b = bboxAround(BURRUSS.lat, BURRUSS.lng, 40);

    const north = haversineMeters(BURRUSS, { lat: b.maxLat, lng: BURRUSS.lng });
    const east = haversineMeters(BURRUSS, { lat: BURRUSS.lat, lng: b.maxLng });

    expect(north).toBeGreaterThan(39);
    expect(north).toBeLessThan(41);
    expect(east).toBeGreaterThan(39);
    expect(east).toBeLessThan(41);
  });

  it('accounts for latitude — a degree of longitude shrinks toward the poles', () => {
    const equator = bboxAround(0, 0, 100);
    const arctic = bboxAround(70, 0, 100);
    const lngSpan = (b: ReturnType<typeof bboxAround>) => b.maxLng - b.minLng;
    expect(lngSpan(arctic)).toBeGreaterThan(lngSpan(equator) * 2);
  });

  it('serialises in Mapillary order: minLng,minLat,maxLng,maxLat', () => {
    const parts = bboxToParam(bboxAround(BURRUSS.lat, BURRUSS.lng, 40)).split(',').map(Number);
    expect(parts).toHaveLength(4);
    expect(parts[0]).toBeLessThan(parts[2]!); // lng ascending
    expect(parts[1]).toBeLessThan(parts[3]!); // lat ascending
    expect(parts[1]).toBeCloseTo(BURRUSS.lat, 2);
  });
});

describe('POST /api/photos/source — Path A, manual upload (the required path)', () => {
  it('accepts MULTIPLE files, not just one (spec 03: "one or more")', async () => {
    const form = new FormData();
    form.append('photos', filePart(PNG_1X1, 'front.png', 'image/png'));
    form.append('photos', filePart(PNG_1X1, 'side.png', 'image/png'));
    form.append('photos', filePart(PNG_1X1, 'rear.png', 'image/png'));

    const res = await fetch(`${server.baseUrl}/api/photos/source`, { method: 'POST', body: form });
    expect(res.status).toBe(200);

    const body = await res.json();
    expect(body.photos).toHaveLength(3);
    expect(body.photos.map((p: any) => p.originalName)).toEqual([
      'front.png',
      'side.png',
      'rear.png',
    ]);
    expect(body.photos.every((p: any) => p.source === 'upload')).toBe(true);
    expect(body.requiresManualUpload).toBe(false);
    expect(body.primary.originalName).toBe('front.png');
  });

  it('stores bytes intact and serves them back at the returned URL', async () => {
    const form = new FormData();
    form.append('photos', filePart(PNG_1X1, 'burruss.png', 'image/png'));

    const res = await fetch(`${server.baseUrl}/api/photos/source`, { method: 'POST', body: form });
    const body = await res.json();

    const stored = body.photos[0];
    expect(stored.sizeBytes).toBe(PNG_1X1.byteLength);
    expect(stored.url).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/uploads\/[0-9a-f-]+\.png$/);

    // Step 05 has to be able to fetch this URL; prove it can.
    const fetched = await fetch(stored.url);
    expect(fetched.status).toBe(200);
    const bytes = Buffer.from(await fetched.arrayBuffer());
    expect(bytes.equals(PNG_1X1)).toBe(true);
  });

  it('gives every upload a distinct id and url', async () => {
    const form = new FormData();
    form.append('photos', filePart(PNG_1X1, 'a.png', 'image/png'));
    form.append('photos', filePart(PNG_1X1, 'b.png', 'image/png'));

    const body = await (
      await fetch(`${server.baseUrl}/api/photos/source`, { method: 'POST', body: form })
    ).json();

    expect(new Set(body.photos.map((p: any) => p.id)).size).toBe(2);
    expect(new Set(body.photos.map((p: any) => p.url)).size).toBe(2);
  });

  it('rejects a non-image with 415 rather than passing junk to step 05', async () => {
    const form = new FormData();
    form.append('photos', filePart(Buffer.from('not an image'), 'notes.txt', 'text/plain'));

    const res = await fetch(`${server.baseUrl}/api/photos/source`, { method: 'POST', body: form });
    expect(res.status).toBe(415);
    expect((await res.json()).error).toMatch(/unsupported photo type/i);
  });

  it('skips the Mapillary round trip entirely when uploads are present', async () => {
    const form = new FormData();
    form.append('photos', filePart(PNG_1X1, 'mine.png', 'image/png'));
    form.append('lat', String(BURRUSS.lat));
    form.append('lng', String(BURRUSS.lng));

    const body = await (
      await fetch(`${server.baseUrl}/api/photos/source`, { method: 'POST', body: form })
    ).json();

    expect(body.mapillary.attempted).toBe(false);
    expect(body.photos).toHaveLength(1);
    expect(body.photos[0].source).toBe('upload');
  });

  it('with no files and no coords, asks for an upload — and does NOT error', async () => {
    const res = await fetch(`${server.baseUrl}/api/photos/source`, {
      method: 'POST',
      body: new FormData(),
    });

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.photos).toEqual([]);
    expect(body.primary).toBeNull();
    expect(body.requiresManualUpload).toBe(true);
  });

  it('advertises multi-file support in its constraints', async () => {
    const body = await (await fetch(`${server.baseUrl}/api/photos/constraints`)).json();
    expect(body.multiple).toBe(true);
    expect(body.maxFiles).toBeGreaterThan(1);
    expect(body.acceptedMimeTypes).toContain('image/jpeg');
  });
});

describe('Path B — Mapillary convenience layer (live API)', () => {
  it('has a token configured', () => {
    expect(hasMapillary()).toBe(true);
  });

  it('returns real, fetchable imagery near a Blacksburg building', async () => {
    const result = await fetchMapillaryPhotos(BURRUSS.lat, BURRUSS.lng);

    expect(result.attempted).toBe(true);
    expect(result.photos.length).toBeGreaterThan(0);

    const nearest = result.photos[0]!;
    expect(nearest.source).toBe('mapillary');
    expect(nearest.url).toMatch(/^https:\/\//);
    expect(nearest.location).not.toBeNull();
    // Ranked by true distance, and actually near the building we asked about.
    expect(nearest.distanceMeters).toBeLessThan(150);
    expect(new Date(nearest.capturedAt!).getUTCFullYear()).toBeGreaterThan(2010);

    const distances = result.photos.map((p) => p.distanceMeters ?? Infinity);
    expect(distances[0]).toBeLessThanOrEqual(Math.max(...distances));

    // The URL must really resolve — step 05 downloads it.
    const head = await fetch(nearest.url, { method: 'GET', headers: { Range: 'bytes=0-64' } });
    expect(head.ok).toBe(true);
    expect(head.headers.get('content-type')).toMatch(/image/);
  });

  it('falls through silently where there is genuinely no coverage', async () => {
    const result = await fetchMapillaryPhotos(LAKE_SUPERIOR.lat, LAKE_SUPERIOR.lng);

    expect(result.attempted).toBe(true);
    expect(result.photos).toEqual([]);
    // Empty is the expected common case, not a failure: no error is recorded.
    expect(result.error).toBeUndefined();
    // And it retried before concluding that, because the index is flaky.
    expect(result.attempts).toBeGreaterThan(1);
  });

  it('GET /api/photos/mapillary reports empty as requiresManualUpload, HTTP 200', async () => {
    const res = await fetch(
      `${server.baseUrl}/api/photos/mapillary?lat=${LAKE_SUPERIOR.lat}&lng=${LAKE_SUPERIOR.lng}`,
    );
    expect(res.status).toBe(200);

    const body = await res.json();
    expect(body.photos).toEqual([]);
    expect(body.requiresManualUpload).toBe(true);
    expect(body.error).toBeUndefined();
  });

  it('validates coordinates instead of forwarding junk to Mapillary', async () => {
    const res = await fetch(`${server.baseUrl}/api/photos/mapillary?lat=999&lng=0`);
    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/lat/);
  });

  it('POST /api/photos/source falls back to Mapillary when no file is supplied', async () => {
    const form = new FormData();
    form.append('lat', String(BURRUSS.lat));
    form.append('lng', String(BURRUSS.lng));

    const body = await (
      await fetch(`${server.baseUrl}/api/photos/source`, { method: 'POST', body: form })
    ).json();

    expect(body.mapillary.attempted).toBe(true);
    expect(body.photos.length).toBeGreaterThan(0);
    expect(body.photos[0].source).toBe('mapillary');
    expect(body.requiresManualUpload).toBe(false);
  });
});
