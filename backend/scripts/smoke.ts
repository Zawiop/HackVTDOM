/**
 * Production-runtime smoke check.
 *
 * Vitest runs through Vite, which resolves CommonJS dependencies differently
 * from plain Node ESM — a difference that once let every IoU silently return 0
 * under `npm start` while the whole test suite stayed green. This runs the real
 * pipeline the way the server does, under tsx/Node, and fails loudly on values
 * that could only come from that class of bug.
 */
import { computePlacementTransform } from '../src/services/placement.js';
import { getWorldStatePrompt, WORLD_STATES } from '../src/services/worldState.js';
import { iou } from '../src/geo/polygon.js';
import { buildingNamed, neighborsOf } from '../test/helpers/fixtures.js';
import { extrudePolygonToObj } from '../test/helpers/meshFixtures.js';

const failures: string[] = [];
const check = (name: string, ok: boolean, detail = '') => {
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`);
  if (!ok) failures.push(name);
};

// The exact shape of the bug this script exists for.
const square = [[0, 0], [10, 0], [10, 10], [0, 10]] as [number, number][];
check('polygon clipper is live under plain Node', iou(square, square) > 0.999, `iou=${iou(square, square)}`);

const building = buildingNamed('Derring Hall');
const { obj } = extrudePolygonToObj(building.geometry, { heightMeters: 22 });
const transform = await computePlacementTransform({
  footprint: { polygon: building, neighbors: neighborsOf(building) },
  mesh: { bytes: Buffer.from(obj, 'utf8'), path: 'smoke.obj' },
});

check('placement reaches its fit ceiling', transform.diagnostics.fitQuality > 0.95,
  `quality=${transform.diagnostics.fitQuality.toFixed(3)}`);
check('scale is ~1 for a mesh built from the footprint', Math.abs(transform.scale - 1) < 0.05,
  `scale=${transform.scale.toFixed(4)}`);
check('mesh sits on the ground', Math.abs(transform.position[2]) < 0.01,
  `z=${transform.position[2].toFixed(4)}`);
check('four rotation candidates kept', transform.scoredRotationCandidates.length === 4);
check('neighbours checked without re-fetching', transform.collision.neighborsChecked > 10,
  `${transform.collision.neighborsChecked} neighbours`);
check('every output number is finite',
  [transform.rotationDegrees, transform.scale, ...transform.position, ...transform.scaleXYZ].every(Number.isFinite));

for (const state of WORLD_STATES) {
  const { prompt } = getWorldStatePrompt({ worldState: state });
  check(`world state "${state}" resolves to a full paragraph`, prompt.length > 400, `${prompt.length} chars`);
}
check('freeform override replaces the preset',
  getWorldStatePrompt({ worldState: 'flooded', freeformOverride: 'A glass tower.' }).prompt === 'A glass tower.');

console.log(failures.length === 0 ? '\nAll smoke checks passed.' : `\n${failures.length} FAILED: ${failures.join(', ')}`);
process.exit(failures.length === 0 ? 0 : 1);
