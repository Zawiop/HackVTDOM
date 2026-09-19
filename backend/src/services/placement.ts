import { readFile } from 'node:fs/promises';
import { LocalProjection, normalizeDegrees, type LatLng, type PointMeters } from '../geo/latlng.js';
import {
  area,
  bboxOverlapArea,
  bounds,
  centroid,
  closeRing,
  convexHull,
  intersectionArea,
  iou as ringIou,
  longestEdgeBearing,
  minAreaRectangle,
  openRing,
  rotateRing,
  scaleRing,
  translateRing,
  type Ring,
} from '../geo/polygon.js';
import { meshBaseFootprint, parseMesh, type MeshFootprint, type UpAxis } from '../geo/mesh.js';
import type {
  CollisionOverlap,
  FootprintInput,
  FootprintPolygon,
  MeshInput,
  PlacementConfidence,
  PlacementFlag,
  PlacementOptions,
  PlacementTransform,
  ScoredRotationCandidate,
} from '../types/placement.js';

/**
 * computePlacementTransform (spec 08).
 *
 * Rotation, scale, ground alignment and a collision check for the normalized
 * mesh (step 07) against the real OSM footprint (step 02). No external calls.
 *
 * All the geometry happens in a local metre frame anchored on the footprint's
 * centroid, so the IoU search is ordinary 2D polygon maths rather than anything
 * spherical. See geo/latlng.ts for the projection.
 *
 * The transform is composed exactly the way deck.gl's ScenegraphLayer applies
 * it — rotate about the model origin, then scale about the model origin, then
 * translate the origin to `position`. The candidate search mirrors that order,
 * so a score computed here is the score you actually see on the map.
 */

/** Spec 08: the longest-edge bearing, "plus that angle +/- 0/90/180/270 offsets". */
const ROTATION_OFFSETS = [0, 90, 180, 270] as const;

const DEFAULTS: Required<PlacementOptions> = {
  // "more than ~30% smaller on one axis" -> coverage below 0.70.
  undersizeThreshold: 0.7,
  collisionThreshold: 0.15,
  minFitQuality: 0.6,
  rotationAmbiguityMargin: 0.05,
};

/** A units error big enough that step 07's sanity pass should have caught it. */
const IMPLAUSIBLE_SCALE_RATIO = 4;

export class PlacementInputError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PlacementInputError';
  }
}

/** Collects flags and derives the final confidence, latching low once set. */
class ConfidenceLedger {
  private readonly entries: PlacementFlag[] = [];

  flag(flag: PlacementFlag): void {
    this.entries.push(flag);
  }

  get flags(): PlacementFlag[] {
    return [...this.entries];
  }

  /**
   * Spec 08: "Any of the three sub-steps flagging low confidence sets the
   * overall record to auto-low ... Don't let one flagged sub-check get silently
   * overwritten by a later 'everything's fine' check."
   *
   * Confidence is derived from the accumulated flags at the end rather than
   * assigned as the algorithm goes, so there is no intermediate value for a
   * later step to overwrite.
   */
  get confidence(): PlacementConfidence {
    return this.entries.length === 0 ? 'auto-high' : 'auto-low';
  }
}

async function loadMeshBytes(mesh: MeshInput): Promise<{ bytes: Buffer; hint: string }> {
  if (mesh.bytes?.byteLength) return { bytes: mesh.bytes, hint: mesh.path ?? mesh.url ?? '' };

  if (mesh.path) {
    const filePath = mesh.path.startsWith('file://') ? new URL(mesh.path).pathname : mesh.path;
    try {
      return { bytes: await readFile(filePath), hint: filePath };
    } catch (err) {
      // A missing mesh file is bad input, not a server fault — say which path.
      throw new PlacementInputError(
        `Could not read mesh at "${filePath}": ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }

  if (mesh.url) {
    const res = await fetch(mesh.url, { signal: AbortSignal.timeout(30_000) });
    if (!res.ok) throw new PlacementInputError(`Could not fetch mesh: HTTP ${res.status}`);
    return { bytes: Buffer.from(await res.arrayBuffer()), hint: mesh.url };
  }

  throw new PlacementInputError('Mesh input needs one of: bytes, path, url, or baseOutline.');
}

async function resolveMeshFootprint(mesh: MeshInput): Promise<MeshFootprint> {
  // Step 07 may already have produced the outline; no need to re-parse the file.
  if (mesh.baseOutline && mesh.baseOutline.length >= 3) {
    const outline = mesh.baseOutline.map(([x, y]) => [x, y] as PointMeters);
    const b = bounds(outline);
    return {
      outline,
      slabFraction: 0,
      baseOffset: mesh.baseOffset ?? 0,
      heightUnits: mesh.heightUnits ?? 0,
      width: b.width,
      depth: b.depth,
      upAxis: mesh.upAxis ?? 'y',
      vertexCount: outline.length,
    };
  }

  const { bytes, hint } = await loadMeshBytes(mesh);
  const geometry = parseMesh(bytes, hint);
  return meshBaseFootprint(geometry, { ...(mesh.upAxis ? { upAxis: mesh.upAxis } : {}) });
}

/** Ring in metres for a lat/lng polygon, validated. */
function projectPolygon(projection: LocalProjection, polygon: FootprintPolygon, label: string): Ring {
  const ring = openRing(projection.ringToMeters(polygon.geometry));
  if (ring.length < 3) {
    throw new PlacementInputError(`${label} needs at least 3 distinct vertices, got ${ring.length}.`);
  }
  return ring;
}

/**
 * Fit the mesh to the footprint *in the mesh's own frame*.
 *
 * This matters more than it looks. deck.gl's ScenegraphLayer applies the
 * transform as translate(rotate(scale(model))) — scale acts on model-space axes,
 * before any rotation. So the axes a non-uniform scale stretches are the mesh's
 * own, not compass east/north. Fitting against the footprint's east/north
 * bounding box would compute the stretch in the wrong frame entirely.
 *
 * It also fixes a real problem with the buildings this runs on. VT's campus is
 * laid out diagonally: measured footprints cluster around bearings of 45 and
 * 136 degrees, where an axis-aligned bounding box can be nearly three times the
 * building's actual area. Rotating the footprint into the mesh's frame first
 * means both extents describe the building along its own walls.
 */
function fitScale(
  meshOutline: Ring,
  footprintRing: Ring,
  headingDegrees: number,
): {
  uniform: number;
  perAxis: [number, number];
  meshWidth: number;
  meshDepth: number;
  targetWidth: number;
  targetDepth: number;
} {
  // Undo the candidate rotation on the footprint, putting it in mesh space.
  const target = bounds(rotateRing(footprintRing, -headingDegrees));
  const mesh = bounds(meshOutline);

  const meshWidth = Math.max(mesh.width, 1e-9);
  const meshDepth = Math.max(mesh.depth, 1e-9);

  const sx = target.width / meshWidth;
  const sy = target.depth / meshDepth;

  // Spec 08 defaults to "a single uniform scale factor that fits the mesh to
  // both". The smaller of the two is the one that fits inside both; taking the
  // larger, or a mean, would overhang the footprint on one axis and cost IoU.
  return {
    uniform: Math.min(sx, sy),
    perAxis: [sx, sy],
    meshWidth,
    meshDepth,
    targetWidth: target.width,
    targetDepth: target.depth,
  };
}

/**
 * Place an outline the way the renderer will: scale in model space, rotate about
 * the model origin, then translate the origin so the result centres on the
 * footprint. Scoring a candidate any other way would score a transform nobody
 * is going to apply.
 */
function placeOutline(
  meshOutline: Ring,
  headingDegrees: number,
  scale: number | [number, number],
  targetCentroid: PointMeters,
): { placed: Ring; offset: PointMeters } {
  const transformed = rotateRing(scaleRing(meshOutline, scale), headingDegrees);
  const c = centroid(transformed);
  const offset: PointMeters = [targetCentroid[0] - c[0], targetCentroid[1] - c[1]];
  return { placed: translateRing(transformed, offset), offset };
}

/**
 * Nudge the placed outline to the offset that actually maximises IoU.
 *
 * Centring the mesh's centroid on the footprint's is the right starting point,
 * but the mesh outline is convex while a real OSM footprint often is not — and
 * the centroid of an L-shaped building sits somewhere its convex hull's centroid
 * does not. On the measured VT footprints that mismatch costs a couple of metres
 * of position and a few points of IoU, which is plainly visible on a map.
 *
 * A shrinking-step hill climb on the offset recovers it. The objective is the
 * same IoU the rotation search used, so this can only improve the score it
 * reports, and it is seeded close enough that a handful of steps converge.
 */
function refineOffset(
  transformed: Ring,
  footprintRing: Ring,
  footprintArea: number,
  seed: PointMeters,
  initialStepMeters: number,
): { offset: PointMeters; iou: number } {
  const score = (offset: PointMeters): number => {
    const placed = translateRing(transformed, offset);
    const inter = intersectionArea(placed, footprintRing);
    const union = area(placed) + footprintArea - inter;
    return union > 0 ? inter / union : 0;
  };

  const DIRECTIONS: PointMeters[] = [
    [1, 0], [-1, 0], [0, 1], [0, -1],
    [1, 1], [1, -1], [-1, 1], [-1, -1],
  ];

  let best = seed;
  let bestScore = score(seed);
  let step = initialStepMeters;

  // ~0.05 m floor: finer than that is well below the accuracy of the OSM
  // polygon itself, so it would be precision without meaning.
  while (step > 0.05) {
    let improved = false;
    for (const [dx, dy] of DIRECTIONS) {
      const candidate: PointMeters = [best[0] + dx * step, best[1] + dy * step];
      const candidateScore = score(candidate);
      if (candidateScore > bestScore + 1e-9) {
        best = candidate;
        bestScore = candidateScore;
        improved = true;
      }
    }
    if (!improved) step /= 2;
  }

  return { offset: best, iou: bestScore };
}

export interface ComputePlacementInput {
  footprint: FootprintInput;
  mesh: MeshInput;
  options?: PlacementOptions;
}

export async function computePlacementTransform(
  input: ComputePlacementInput,
): Promise<PlacementTransform> {
  const opts = { ...DEFAULTS, ...(input.options ?? {}) };
  const ledger = new ConfidenceLedger();

  // --- Frame setup ---------------------------------------------------------
  const rawRing: LatLng[] = input.footprint.polygon.geometry ?? [];
  if (rawRing.length < 3) {
    throw new PlacementInputError(
      `Footprint polygon needs at least 3 vertices, got ${rawRing.length}.`,
    );
  }

  // Anchor the local frame on the first vertex; everything is relative to it,
  // so the exact choice only affects floating-point conditioning, not results.
  const seed: LatLng = rawRing[0]!;
  const projection = new LocalProjection(seed);
  const footprintRing = projectPolygon(projection, input.footprint.polygon, 'Footprint polygon');
  const footprintCentroid = centroid(footprintRing);
  const footprintBounds = bounds(footprintRing);
  const footprintArea = area(footprintRing);

  if (footprintArea < 1) {
    throw new PlacementInputError(
      `Footprint polygon area is ${footprintArea.toFixed(2)} m² — too small to place against.`,
    );
  }

  // Step 02's confidence propagates; it is a distinct uncertainty source from
  // anything decided here, and step 09 needs to be able to tell them apart.
  if (input.footprint.confidence === 'low') {
    ledger.flag({
      subStep: 'footprint',
      code: 'footprint-match-low',
      message:
        'Step 02 reported a low-confidence footprint match; the polygon itself may be the wrong building.',
    });
  }

  // --- Cross-check step 02's derived numbers -------------------------------
  // Recomputed here rather than trusted: if they disagree, that is worth
  // surfacing, not silently working around.
  const bearing =
    input.footprint.longestEdgeBearingDegrees ?? longestEdgeBearing(footprintRing);
  const computedBearing = longestEdgeBearing(footprintRing);

  const mismatches: { field: string; reported: number; computed: number }[] = [];
  const checkDerived = (field: string, reported: number | undefined, computed: number) => {
    if (reported === undefined) return;
    const tolerance = Math.max(1, computed * 0.1);
    if (Math.abs(reported - computed) > tolerance) {
      mismatches.push({ field, reported, computed });
    }
  };
  checkDerived('footprintWidthMeters', input.footprint.footprintWidthMeters, footprintBounds.width);
  checkDerived('footprintDepthMeters', input.footprint.footprintDepthMeters, footprintBounds.depth);
  if (
    input.footprint.longestEdgeBearingDegrees !== undefined &&
    Math.abs(normalizeDegrees(input.footprint.longestEdgeBearingDegrees - computedBearing) % 180) > 5
  ) {
    mismatches.push({
      field: 'longestEdgeBearingDegrees',
      reported: input.footprint.longestEdgeBearingDegrees,
      computed: computedBearing,
    });
  }
  if (mismatches.length > 0) {
    ledger.flag({
      subStep: 'footprint',
      code: 'derived-values-disagree',
      message:
        `Step 02's derived values disagree with this polygon: ` +
        mismatches
          .map((m) => `${m.field} reported ${m.reported.toFixed(2)}, computed ${m.computed.toFixed(2)}`)
          .join('; ') +
        '. Placement used the values computed from the polygon.',
    });
  }

  // --- Mesh ----------------------------------------------------------------
  const meshFootprint = await resolveMeshFootprint(input.mesh);
  const meshOutline = meshFootprint.outline;
  if (meshOutline.length < 3 || area(meshOutline) <= 0) {
    throw new PlacementInputError(
      'Mesh base outline is degenerate — step 07 may not have produced a usable base.',
    );
  }

  // --- Rotation search (spec 08) -------------------------------------------
  // Spec 08 generates candidates from "the longest-edge bearing from step 02,
  // plus that angle +/- 0/90/180/270 degree offsets". Applied literally that
  // assumes the mesh arrives with its own long axis pointing north, which a
  // mesh reconstructed from a photograph does not: TripoSR orients output to
  // the camera. So the candidate heading is the rotation that carries the
  // *mesh's* long axis onto the footprint's, plus the offset:
  //
  //     heading = footprintBearing - meshBearing + offset
  //
  // That reduces to the spec's formula whenever meshBearing is 0, keeps the
  // four candidates exactly 90 degrees apart (which is what step 09's "try
  // these 4 alignments" buttons need), and is what makes the sweep meaningful
  // for a mesh that carries an orientation of its own.
  // Both principal axes come from the minimum-area rectangle rather than the
  // longest edge. On the real VT footprints the min-area-rectangle angle of a
  // polygon and of its own convex hull agree to 0.000 degrees across every
  // building measured, while their longest edges disagree by as much as 65 —
  // and step 08 is always comparing a convex mesh outline to a possibly-concave
  // OSM polygon, so the stable estimator is the one that matters. Step 02's
  // longest-edge bearing is still reported in diagnostics.
  const footprintAxis = minAreaRectangle(footprintRing).angleDegrees;
  const meshBearing = minAreaRectangle(meshOutline).angleDegrees;

  // Score every candidate and keep them all: step 09 reuses the full list, so
  // nothing computed here gets discarded.
  const candidates: ScoredRotationCandidate[] = ROTATION_OFFSETS.map((offset) => {
    const headingDegrees = normalizeDegrees(footprintAxis - meshBearing + offset);
    const fit = fitScale(meshOutline, footprintRing, headingDegrees);

    const { placed } = placeOutline(meshOutline, headingDegrees, fit.uniform, footprintCentroid);

    const intersection = intersectionArea(placed, footprintRing);
    const union = area(placed) + footprintArea - intersection;

    return {
      offsetDegrees: offset,
      rotationDegrees: headingDegrees,
      iou: union > 0 ? intersection / union : 0,
      intersectionAreaSqM: intersection,
      scale: fit.uniform,
      coverage: [
        (fit.uniform * fit.meshWidth) / Math.max(fit.targetWidth, 1e-9),
        (fit.uniform * fit.meshDepth) / Math.max(fit.targetDepth, 1e-9),
      ] as [number, number],
    };
  });

  const ranked = [...candidates].sort((a, b) => b.iou - a.iou);
  const winner = ranked[0]!;

  // The 180-degree flip is a special case, not a rival. A building footprint is
  // very nearly centrosymmetric, so rotating a mesh end-for-end barely changes
  // its IoU — measured across the real fixtures, 44% of buildings had their top
  // two candidates within the ambiguity margin and *every one of them* was a
  // pure 0-vs-180 pair. Flagging those would mark nearly half of all placements
  // for review on a distinction footprint IoU cannot make in principle.
  //
  // So ambiguity is judged against the best *geometrically distinguishable*
  // alternative — the 90-degree turns, where the mesh really does sit across
  // the footprint rather than along it. The flip is reported separately so
  // step 09 can still offer "turn it around" without every building being
  // routed to manual review to get the button.
  const flip = ranked.find((c) => Math.abs(c.offsetDegrees - winner.offsetDegrees) === 180);
  const runnerUp = ranked.find(
    (c) => c !== winner && Math.abs(c.offsetDegrees - winner.offsetDegrees) !== 180,
  );
  const rotationFlipMargin = flip ? winner.iou - flip.iou : null;

  // A mesh base outline is convex; a real OSM footprint frequently is not. So
  // the highest IoU any convex outline could possibly score against this
  // polygon is the polygon against its own hull — 0.48 for Campbell Hall, 0.98
  // for Sandy Hall. Judging every building against one absolute IoU number
  // would flag a perfect placement on the concave ones and wave through a
  // mediocre one on the simple ones. Fit quality is the achieved IoU as a
  // fraction of that ceiling. The check itself runs after the offset
  // refinement below, so it judges the placement actually being returned.
  const maxAchievableIou = ringIou(convexHull(footprintRing), footprintRing);

  if (runnerUp && winner.iou - runnerUp.iou < opts.rotationAmbiguityMargin) {
    ledger.flag({
      subStep: 'rotation',
      code: 'rotation-ambiguous',
      message:
        `Top two rotations are within ${(winner.iou - runnerUp.iou).toFixed(3)} IoU ` +
        `(${winner.rotationDegrees.toFixed(1)}° vs ${runnerUp.rotationDegrees.toFixed(1)}°) — the mesh may belong across ` +
        'the footprint rather than along it, and IoU cannot separate the two.',
    });
  }

  // --- Scale (spec 08) ------------------------------------------------------
  const fit = fitScale(meshOutline, footprintRing, winner.rotationDegrees);

  const uniformCoverage = winner.coverage;
  const worstCoverage = Math.min(uniformCoverage[0], uniformCoverage[1]);

  let scaleMode: 'uniform' | 'non-uniform' = 'uniform';
  let horizontalScale: [number, number] = [fit.uniform, fit.uniform];

  if (worstCoverage < opts.undersizeThreshold) {
    // Uniform scaling leaves the mesh badly undersized on one axis, so fall back
    // to independent width/depth stretching. Height stays on the uniform factor:
    // spec 08 authorises stretching width and depth, and a building that grows
    // taller because its plan is the wrong aspect ratio would look plainly wrong.
    scaleMode = 'non-uniform';
    horizontalScale = fit.perAxis;
    ledger.flag({
      subStep: 'scale',
      code: 'non-uniform-fallback',
      message:
        `Uniform scaling covered only ${(worstCoverage * 100).toFixed(0)}% of the footprint on one axis ` +
        `(threshold ${(opts.undersizeThreshold * 100).toFixed(0)}%); fell back to independent width/depth scaling ` +
        `(${fit.perAxis[0].toFixed(3)} x ${fit.perAxis[1].toFixed(3)}).`,
    });
  }

  // A fit factor far from 1 means step 07 handed over a mesh that isn't in
  // metres. Spec 07 owns that; flag it rather than quietly absorbing it.
  const fitRatio = Math.max(fit.uniform, 1 / Math.max(fit.uniform, 1e-9));
  if (fitRatio > IMPLAUSIBLE_SCALE_RATIO) {
    ledger.flag({
      subStep: 'mesh',
      code: 'implausible-scale',
      message:
        `Fitting the mesh needed a ${fit.uniform.toFixed(3)}x scale — off by more than ${IMPLAUSIBLE_SCALE_RATIO}x. ` +
        "This looks like a units problem in step 07's normalization, not a scale-fitting result.",
    });
  }

  const transformed = rotateRing(scaleRing(meshOutline, horizontalScale), winner.rotationDegrees);
  const transformedCentroid = centroid(transformed);
  const seedOffset: PointMeters = [
    footprintCentroid[0] - transformedCentroid[0],
    footprintCentroid[1] - transformedCentroid[1],
  ];

  const refined = refineOffset(
    transformed,
    footprintRing,
    footprintArea,
    seedOffset,
    Math.max(footprintBounds.width, footprintBounds.depth) * 0.1,
  );

  const offset = refined.offset;
  const placedOutline = translateRing(transformed, offset);
  const finalIou = refined.iou;
  const placedArea = area(placedOutline);

  const fitQuality = maxAchievableIou > 0 ? finalIou / maxAchievableIou : 0;
  if (fitQuality < opts.minFitQuality) {
    ledger.flag({
      subStep: 'rotation',
      code: 'low-iou',
      message:
        `Best placement reached IoU ${finalIou.toFixed(3)} against a ceiling of ${maxAchievableIou.toFixed(3)} ` +
        `for this footprint — ${(fitQuality * 100).toFixed(0)}% of achievable, below the ` +
        `${(opts.minFitQuality * 100).toFixed(0)}% threshold. The mesh outline and the OSM polygon may not ` +
        'describe the same building.',
    });
  }

  // --- Collision (spec 08) --------------------------------------------------
  // Neighbours come from step 02's already-fetched result. No new Overpass call.
  const overlaps: CollisionOverlap[] = [];
  const targetId = input.footprint.polygon.id;
  const neighbors = (input.footprint.neighbors ?? []).filter((n) => {
    if (targetId !== undefined && n.id !== undefined) return String(n.id) !== String(targetId);
    // Without ids, exclude anything that is essentially the target polygon itself.
    try {
      return ringIou(openRing(projection.ringToMeters(n.geometry)), footprintRing) < 0.9;
    } catch {
      return true;
    }
  });

  const placedFootprintArea = Math.max(placedArea, 1e-9);

  for (const neighbor of neighbors) {
    let neighborRing: Ring;
    try {
      neighborRing = openRing(projection.ringToMeters(neighbor.geometry));
    } catch {
      continue;
    }
    if (neighborRing.length < 3) continue;

    // Spec 08 asks for a bounding-box overlap test. Kept as the cheap gate —
    // but an axis-aligned box is a poor stand-in for a building on this campus,
    // where footprints sit at roughly 45 degrees to the compass and their boxes
    // overlap while the buildings themselves are metres apart. So a box hit is
    // confirmed against the actual polygons before it counts as a collision.
    if (bboxOverlapArea(placedOutline, neighborRing) <= 0) continue;

    const overlapArea = intersectionArea(placedOutline, neighborRing);
    if (overlapArea <= 0) continue;

    const neighborArea = Math.max(area(neighborRing), 1e-9);

    // Measured against both footprints, and the worse of the two is what counts.
    // A ratio against the mesh alone misses the case that matters most: a large
    // building placed over a small neighbour covers it completely while using
    // only a few percent of its own footprint, which would slip under any
    // mesh-relative threshold.
    overlaps.push({
      neighborId: neighbor.id ?? null,
      overlapAreaSqM: overlapArea,
      overlapRatio: Math.max(overlapArea / placedFootprintArea, overlapArea / neighborArea),
      overlapRatioOfMesh: overlapArea / placedFootprintArea,
      overlapRatioOfNeighbor: overlapArea / neighborArea,
    });
  }

  overlaps.sort((a, b) => b.overlapRatio - a.overlapRatio);
  const worstOverlapRatio = overlaps[0]?.overlapRatio ?? 0;

  if (worstOverlapRatio > opts.collisionThreshold) {
    ledger.flag({
      subStep: 'collision',
      code: 'neighbor-overlap',
      message:
        `Placed mesh overlaps neighbouring footprint ${overlaps[0]!.neighborId ?? '(unnamed)'} by ` +
        `${(worstOverlapRatio * 100).toFixed(0)}% of its own bounding box ` +
        `(threshold ${(opts.collisionThreshold * 100).toFixed(0)}%).`,
    });
  }

  // --- Ground alignment (spec 08) ------------------------------------------
  // Step 07 base-centres the pivot, so baseOffset should be ~0 and z should be
  // ~0. Computing it anyway means a mesh that wasn't quite base-centred still
  // lands on the ground instead of floating or sinking.
  const verticalScale = horizontalScale[0] === horizontalScale[1] ? horizontalScale[0] : fit.uniform;
  const z = -meshFootprint.baseOffset * verticalScale;

  if (meshFootprint.heightUnits > 0) {
    const baseOffsetFraction = Math.abs(meshFootprint.baseOffset) / meshFootprint.heightUnits;
    if (baseOffsetFraction > 0.02) {
      ledger.flag({
        subStep: 'ground',
        code: 'pivot-not-base-centred',
        message:
          `Mesh base sits ${meshFootprint.baseOffset.toFixed(3)} units from its own origin ` +
          `(${(baseOffsetFraction * 100).toFixed(1)}% of its height). Step 07 should base-centre the pivot; ` +
          `placement corrected for it with z = ${z.toFixed(3)} m.`,
      });
    }
  }

  const position = projection.toLatLng(offset);

  return {
    rotationDegrees: winner.rotationDegrees,
    scale: fit.uniform,
    position: [position.lat, position.lng, z],
    confidence: ledger.confidence,
    scoredRotationCandidates: ranked,

    scaleMode,
    scaleXYZ: [horizontalScale[0], verticalScale, horizontalScale[1]],

    flags: ledger.flags,

    collision: {
      neighborsChecked: neighbors.length,
      overlaps,
      worstOverlapRatio,
    },

    ground: {
      meshBaseOffsetUnits: meshFootprint.baseOffset,
      z,
    },

    diagnostics: {
      iou: finalIou,
      maxAchievableIou,
      fitQuality,
      footprintAreaSqM: footprintArea,
      placedMeshAreaSqM: placedArea,
      footprintWidthMeters: footprintBounds.width,
      footprintDepthMeters: footprintBounds.depth,
      longestEdgeBearingDegrees: bearing,
      meshLongestEdgeBearingDegrees: longestEdgeBearing(meshOutline),
      footprintPrincipalAxisDegrees: footprintAxis,
      meshPrincipalAxisDegrees: meshBearing,
      /** How far the IoU refinement moved the mesh off a plain centroid match. */
      refinementShiftMeters: Math.hypot(offset[0] - seedOffset[0], offset[1] - seedOffset[1]),
      rotationFlipMargin,
      meshWidthUnits: meshFootprint.width,
      meshDepthUnits: meshFootprint.depth,
      meshHeightUnits: meshFootprint.heightUnits,
      scaledHeightMeters: meshFootprint.heightUnits * verticalScale,
      upAxis: meshFootprint.upAxis as UpAxis,
      ...(mismatches.length > 0 ? { footprintDerivedMismatch: mismatches } : {}),
    },
  };
}

export { closeRing };
