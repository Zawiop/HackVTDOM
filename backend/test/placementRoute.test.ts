import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { startTestServer, type TestServer } from './helpers/server.js';
import { buildingNamed, neighborsOf } from './helpers/fixtures.js';
import { extrudePolygonToObj } from './helpers/meshFixtures.js';

const readJson = (res: Response): Promise<any> => res.json() as Promise<any>;

let server: TestServer;
beforeAll(async () => {
  server = await startTestServer();
});
afterAll(async () => {
  await server.close();
});

async function post(body: unknown): Promise<{ status: number; body: any }> {
  const res = await fetch(`${server.baseUrl}/api/placement`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return { status: res.status, body: await readJson(res) };
}

describe('POST /api/placement', () => {
  it('returns the full transform record spec 08 specifies', async () => {
    const building = buildingNamed('Derring Hall');
    const { obj } = extrudePolygonToObj(building.geometry, { heightMeters: 22 });

    const { status, body } = await post({
      footprint: { polygon: building, neighbors: neighborsOf(building) },
      mesh: { bytesBase64: Buffer.from(obj, 'utf8').toString('base64'), path: 'mesh.obj' },
    });

    expect(status).toBe(200);

    // The five fields spec 08 names, by name and by type.
    expect(typeof body.rotationDegrees).toBe('number');
    expect(typeof body.scale).toBe('number');
    expect(body.position).toHaveLength(3);
    expect(['auto-high', 'auto-low']).toContain(body.confidence);
    expect(Array.isArray(body.scoredRotationCandidates)).toBe(true);
    expect(body.scoredRotationCandidates).toHaveLength(4);

    // Values a renderer can actually use.
    expect(body.rotationDegrees).toBeGreaterThanOrEqual(0);
    expect(body.rotationDegrees).toBeLessThan(360);
    expect(body.scale).toBeGreaterThan(0);
    expect(body.position[0]).toBeCloseTo(37.23, 1);
    expect(body.position[1]).toBeCloseTo(-80.42, 1);
    expect(body.scaleXYZ).toHaveLength(3);
    expect(body.collision.neighborsChecked).toBeGreaterThan(0);

    // Survives a JSON round trip with no NaN or Infinity anywhere.
    for (const value of JSON.stringify(body).match(/-?\d+(\.\d+)?([eE][-+]?\d+)?/g) ?? []) {
      expect(Number.isFinite(Number(value))).toBe(true);
    }
  });

  it('accepts a bare geometry array, the way step 02 may hand it over', async () => {
    const building = buildingNamed('Norris Hall');
    const { obj } = extrudePolygonToObj(building.geometry);

    const { status, body } = await post({
      footprint: { geometry: building.geometry },
      mesh: { bytesBase64: Buffer.from(obj, 'utf8').toString('base64'), path: 'mesh.obj' },
    });

    expect(status).toBe(200);
    expect(body.diagnostics.fitQuality).toBeGreaterThan(0.95);
  });

  it('rejects a missing footprint with a useful message', async () => {
    const { status, body } = await post({ mesh: { path: 'x.obj' } });
    expect(status).toBe(400);
    expect(body.error).toMatch(/footprint/i);
  });

  it('reports an unusable mesh as 422, not a 500', async () => {
    const building = buildingNamed('Norris Hall');
    const { status, body } = await post({
      footprint: { polygon: building },
      mesh: { bytesBase64: Buffer.from('not a mesh at all').toString('base64'), path: 'bad.glb' },
    });

    expect(status).toBe(422);
    expect(body.kind).toBe('MeshParseError');
  });

  it('does not re-fetch neighbours — it works with none supplied', async () => {
    const building = buildingNamed('Sandy Hall');
    const { obj } = extrudePolygonToObj(building.geometry);

    const { status, body } = await post({
      footprint: { polygon: building },
      mesh: { bytesBase64: Buffer.from(obj, 'utf8').toString('base64'), path: 'mesh.obj' },
    });

    expect(status).toBe(200);
    expect(body.collision.neighborsChecked).toBe(0);
    expect(body.collision.overlaps).toEqual([]);
  });
});

describe('mesh input errors are reported as bad input, not server faults', () => {
  it('rejects empty base64 rather than falling through to a missing file', async () => {
    const building = buildingNamed('Norris Hall');
    const { status, body } = await post({
      footprint: { polygon: building },
      mesh: { bytesBase64: '', path: 'nowhere.obj' },
    });

    expect(status).toBe(400);
    expect(body.error).toMatch(/zero bytes/i);
  });

  it('reports a missing mesh file as 422 with the path it tried', async () => {
    const building = buildingNamed('Norris Hall');
    const { status, body } = await post({
      footprint: { polygon: building },
      mesh: { path: '/definitely/not/here.glb' },
    });

    expect(status).toBe(422);
    expect(body.error).toMatch(/not\/here\.glb/);
  });
});
