/**
 * Renders placed mesh outlines over their real OSM footprints, as one SVG per
 * building. A numeric IoU can be right while something is visibly wrong, so
 * this is the eyeball check — and it doubles as the debug view for step 09.
 *
 *   npx tsx scripts/placement-preview.ts [outfile.html]
 */
import { writeFileSync } from 'node:fs';
import { computePlacementTransform } from '../src/services/placement.js';
import { LocalProjection } from '../src/geo/latlng.js';
import { bounds, openRing, rotateRing, scaleRing, translateRing, type Ring } from '../src/geo/polygon.js';
import { meshBaseFootprint, parseObj } from '../src/geo/mesh.js';
import { allBuildings, neighborsOf } from '../test/helpers/fixtures.js';
import { extrudePolygonToObj } from '../test/helpers/meshFixtures.js';

const OUT = process.argv[2] ?? 'placement-preview.html';
const PRE_ROTATIONS = [0, 37, 145, 213];

const path = (ring: Ring) => ring.map(([x, y]) => `${x.toFixed(2)},${(-y).toFixed(2)}`).join(' ');

const cards: string[] = [];

for (const [i, building] of allBuildings().slice(0, 12).entries()) {
  const preRotate = PRE_ROTATIONS[i % PRE_ROTATIONS.length]!;
  const { obj } = extrudePolygonToObj(building.geometry, { heightMeters: 20, preRotateDegrees: preRotate });

  const transform = await computePlacementTransform({
    footprint: { polygon: building, neighbors: neighborsOf(building) },
    mesh: { bytes: Buffer.from(obj, 'utf8'), path: 'preview.obj' },
  });

  // Re-derive the placed outline from the returned transform alone — if the
  // record is wrong, this drawing is wrong, which is the point.
  const proj = new LocalProjection(building.geometry[0]!);
  const footprint = openRing(proj.ringToMeters(building.geometry));
  const meshOutline = meshBaseFootprint(parseObj(obj)).outline;
  const origin = proj.toMeters({ lat: transform.position[0], lng: transform.position[1] });
  const placed = translateRing(
    rotateRing(scaleRing(meshOutline, [transform.scaleXYZ[0], transform.scaleXYZ[2]]), transform.rotationDegrees),
    origin,
  );

  const neighbors = neighborsOf(building)
    .map((n) => openRing(proj.ringToMeters(n.geometry)))
    .filter((r) => r.length >= 3);

  // Frame on the target building, not the whole block — neighbours are context
  // and get clipped. The overlay is unreadable at block scale.
  const b = bounds([...footprint, ...placed]);
  const pad = Math.max(b.width, b.depth) * 0.25;
  const vb = `${(b.minX - pad).toFixed(1)} ${(-b.maxY - pad).toFixed(1)} ${(b.width + 2 * pad).toFixed(1)} ${(b.depth + 2 * pad).toFixed(1)}`;

  const d = transform.diagnostics;
  cards.push(`
  <figure>
    <svg viewBox="${vb}" preserveAspectRatio="xMidYMid meet">
      ${neighbors.map((n) => `<polygon class="nbr" points="${path(n)}"/>`).join('')}
      <polygon class="fp" points="${path(footprint)}"/>
      <polygon class="mesh" points="${path(placed)}"/>
      <circle class="org" cx="${origin[0].toFixed(2)}" cy="${(-origin[1]).toFixed(2)}" r="1.2"/>
    </svg>
    <figcaption>
      <strong>${building.tags?.name ?? building.id}</strong>
      <span class="${transform.confidence === 'auto-high' ? 'ok' : 'warn'}">${transform.confidence}</span>
      <dl>
        <div><dt>mesh pre-rotated</dt><dd>${preRotate}&deg;</dd></div>
        <div><dt>recovered rotation</dt><dd>${transform.rotationDegrees.toFixed(1)}&deg;</dd></div>
        <div><dt>scale</dt><dd>${transform.scale.toFixed(3)} (${transform.scaleMode})</dd></div>
        <div><dt>ground z</dt><dd>${transform.position[2].toFixed(3)} m</dd></div>
        <div><dt>IoU / ceiling</dt><dd>${d.iou.toFixed(3)} / ${d.maxAchievableIou.toFixed(3)}</dd></div>
        <div><dt>fit quality</dt><dd>${(d.fitQuality * 100).toFixed(1)}%</dd></div>
        <div><dt>neighbours</dt><dd>${transform.collision.neighborsChecked} checked, worst ${(transform.collision.worstOverlapRatio * 100).toFixed(1)}%</dd></div>
      </dl>
      ${transform.flags.length ? `<ul class="flags">${transform.flags.map((f) => `<li>${f.subStep}: ${f.code}</li>`).join('')}</ul>` : ''}
    </figcaption>
  </figure>`);
}

writeFileSync(
  OUT,
  `<!doctype html><meta charset="utf-8"><title>Placement preview</title>
<style>
:root{color-scheme:dark;--bg:#14150f;--panel:#1d1f16;--ink:#e8e3d2;--dim:#9a977f;--amber:#c99a3f;--moss:#6f8355;--line:#33362a}
body{margin:0;padding:1.5rem;background:var(--bg);color:var(--ink);font:14px/1.5 ui-sans-serif,system-ui,sans-serif}
h1{font-size:1.2rem;margin:0 0 .25rem}p.lede{color:var(--dim);margin:0 0 1.5rem;max-width:60ch}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(20rem,1fr));gap:1rem}
figure{margin:0;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:.9rem}
svg{width:100%;height:14rem;background:#101208;border-radius:6px}
.nbr{fill:#2a2d20;stroke:#3d4130;stroke-width:.4}
.fp{fill:rgba(111,131,85,.28);stroke:var(--moss);stroke-width:.7}
.mesh{fill:rgba(201,154,63,.22);stroke:var(--amber);stroke-width:.7;stroke-dasharray:2 1.5}
.org{fill:var(--amber)}
figcaption strong{display:inline-block;margin:.6rem .5rem 0 0}
.ok{color:var(--moss)}.warn{color:var(--amber)}
dl{margin:.5rem 0 0;font-size:.76rem;color:var(--dim)}
dl div{display:flex;justify-content:space-between;gap:1rem;border-bottom:1px dotted var(--line);padding:.12rem 0}
dt,dd{margin:0}dd{color:var(--ink)}
.flags{margin:.5rem 0 0;padding-left:1.1rem;font-size:.74rem;color:var(--amber)}
.key{color:var(--dim);font-size:.8rem;margin-bottom:1rem}
.key b{font-weight:600}.key .m{color:var(--amber)}.key .f{color:var(--moss)}
</style>
<h1>Placement preview — real OSM footprints, meshes pre-rotated by a known angle</h1>
<p class="lede">Each mesh was built from its building's own footprint and then turned by the angle
shown, so a correct placement puts the dashed outline back exactly on the solid one. Outlines are
re-derived from the returned transform record, not from the internal working.</p>
<p class="key"><b class="f">&#9646; solid green</b> = real OSM footprint &nbsp;&nbsp;
<b class="m">&#9647; dashed amber</b> = placed mesh base outline &nbsp;&nbsp;
<b>&#9679;</b> = model origin (the returned lat/lng) &nbsp;&nbsp;
grey = neighbouring buildings</p>
<div class="grid">${cards.join('')}</div>`,
);

console.log(`wrote ${OUT} (${cards.length} buildings)`);
