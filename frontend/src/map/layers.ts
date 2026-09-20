import { PolygonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { ScenegraphLayer } from "@deck.gl/mesh-layers";
import { GLTFLoader } from "@loaders.gl/gltf";

import type { Generation, PlacementOverrides } from "../types/contract";
import { enclosingRadiusMeters, footprintCorners } from "./footprintGeometry";
import { featurePolygon, terrainCells, terrainFeatures } from "./terrain";
import type { TerrainCell, TerrainFeature } from "./terrain";

/**
 * Step 12 layer construction.
 *
 * VERIFIED CORRECTION TO THE SPEC (12-map-render.md):
 * the spec's contract shows `scenegraph: d => d.mesh_url`. In deck.gl 9 the
 * `scenegraph` prop is typed `any` — a URL / parsed glTF / Promise — NOT an
 * `Accessor<DataT, ...>` the way `getOrientation` / `getScale` /
 * `getTranslation` are. Passing a function makes the layer try to load the
 * function itself as a model. Since every building has its own mesh, rows are
 * grouped by `mesh_url` and one ScenegraphLayer is built per distinct mesh.
 */

/**
 * One mesh per address: the newest generation, or whichever one is selected.
 *
 * Step 11 keeps one row per generation, so an address that has been through two World
 * States has two rows at the *same* coordinate — rendering both stacks the meshes into
 * each other. The other states are not lost: the click panel's history timeline lists
 * them, and picking one selects it, which brings it to the front here.
 */
/**
 * One row per address — two World States of the same building sit at the same
 * coordinate and would otherwise interpenetrate.
 *
 * Which one wins, in order:
 *   1. the row being inspected right now,
 *   2. the row the user pinned for that address,
 *   3. otherwise the newest.
 *
 * The pin is what makes a chosen state stick. Without it, picking "scorched"
 * and then closing the panel silently reverted the building to whatever was
 * generated last, and the choice looked like it had been thrown away.
 */
export function visibleRows(
  rows: Generation[],
  selectedId?: string | null,
  pinnedIds?: ReadonlySet<string> | null,
): Generation[] {
  const rank = (row: Generation): number => {
    if (row.id === selectedId) return 3;
    if (pinnedIds?.has(row.id)) return 2;
    return 1;
  };

  const best = new Map<string, Generation>();
  for (const row of rows) {
    const key = row.address || row.id;
    const current = best.get(key);
    if (!current) {
      best.set(key, row);
      continue;
    }
    const a = rank(row);
    const b = rank(current);
    if (a > b || (a === b && (row.created_at ?? "") > (current.created_at ?? ""))) {
      best.set(key, row);
    }
  }
  return [...best.values()];
}

/** [pitch, yaw, roll]. roll=90 lifts a Y-up glTF onto deck.gl's Z-up ground. */
export const UP_AXIS_ROLL = 90;

export const FALLBACK_MESH = "/placeholder.glb";

export function orientationFor(
  row: Partial<Generation>,
  rollOverride: number = UP_AXIS_ROLL,
): [number, number, number] {
  const yaw = Number(row?.placement?.rotationDegrees ?? 0) || 0;
  return [0, yaw, rollOverride];
}

export function scaleFor(row: Partial<Generation>): [number, number, number] {
  const s = Number(row?.placement?.scale ?? 1) || 1;

  // Step 08 emits scaleXYZ only when mesh and footprint proportions disagree
  // enough that the uniform fit looks undersized. Uniform stays the default —
  // proportion-preserving is the stated preference in 08-placement-transform.md —
  // but ignoring the stretch when it is offered throws the information away.
  const xyz = row?.placement?.scaleXYZ;
  if (Array.isArray(xyz) && xyz.length === 3) {
    const [x, y, z] = xyz.map((v) => Number(v));
    if ([x, y, z].every((v) => Number.isFinite(v) && v > 0)) return [x, y, z];
  }
  return [s, s, s];
}

export function positionFor(row: Partial<Generation>): [number, number, number] {
  // placement.position is [lat, lng, z]; deck.gl wants [lng, lat, z].
  const z = Number(row?.placement?.position?.[2] ?? 0) || 0;
  return [Number(row.lng), Number(row.lat), z];
}

export function groupByMesh(
  rows: Generation[],
  fallbackMesh: string = FALLBACK_MESH,
): Map<string, Generation[]> {
  const groups = new Map<string, Generation[]>();
  for (const row of rows) {
    const url = row.mesh_url || fallbackMesh;
    const bucket = groups.get(url);
    if (bucket) bucket.push(row);
    else groups.set(url, [row]);
  }
  return groups;
}

/** A safe layer-id fragment for a mesh URL. */
function meshKey(url: string): string {
  return url.replace(/[^a-zA-Z0-9]/g, "_").slice(-60);
}

interface LayerOpts {
  onClick?: (row: Generation) => void;
  roll?: number;
  fallbackMesh?: string;
  selectedId?: string | null;
  /** Live, unsaved correction values applied to the selected row only. */
  overrides?: PlacementOverrides | null;
  /**
   * 0..1 — how much of the transformed world is showing. 1 is the World State
   * in full; 0 leaves the real basemap bare underneath. Drives the before/after
   * reveal, which is the pitch's own beat: here is your street, here it is
   * after.
   */
  reveal?: number;
}

/**
 * Clamp to 0..1. Anything unset or unreadable means "fully revealed".
 *
 * The null case has to be explicit: `Number(null)` is 0, so falling through to
 * the numeric path would turn an absent value into a hidden world — a link
 * with no `rv` parameter would open on an empty map and read as a broken app.
 */
export function clampReveal(value: number | null | undefined): number {
  if (value == null) return 1;
  const n = Number(value);
  if (!Number.isFinite(n)) return 1;
  return Math.min(1, Math.max(0, n));
}

function applyOverrides(
  row: Generation,
  selectedId: string | null | undefined,
  overrides: PlacementOverrides | null | undefined,
): Generation {
  if (!overrides || row.id !== selectedId) return row;
  return { ...row, placement: { ...row.placement, ...overrides } };
}

export function buildScenegraphLayers(rows: Generation[], opts: LayerOpts = {}) {
  const {
    onClick,
    roll = UP_AXIS_ROLL,
    fallbackMesh = FALLBACK_MESH,
    selectedId = null,
    overrides = null,
  } = opts;
  const reveal = clampReveal(opts.reveal ?? 1);
  if (reveal <= 0) return [];

  return [...groupByMesh(rows, fallbackMesh)].map(([url, group]) => {
    const data = group.map((r) => applyOverrides(r, selectedId, overrides));
    return new ScenegraphLayer<Generation>({
      id: `buildings-${meshKey(url)}`,
      data,
      scenegraph: url,
      loaders: [GLTFLoader],
      getPosition: positionFor,
      getOrientation: (d: Generation) => orientationFor(d, roll),
      getScale: scaleFor,
      sizeScale: 1,
      _lighting: "pbr",
      opacity: reveal,
      // A half-faded building should not swallow clicks meant for the map
      // underneath it — during a reveal the real ground is what is being
      // looked at.
      pickable: reveal > 0.35,
      onClick: (info) => {
        if (info.object) onClick?.(info.object);
      },
      updateTriggers: {
        getOrientation: [roll, selectedId, overrides?.rotationDegrees],
        getScale: [selectedId, overrides?.scale],
        getPosition: [selectedId, overrides?.position?.join(",")],
      },
    });
  });
}

/**
 * Low-confidence treatment: a warning ring, never hiding the building.
 * Showing a flagged result honestly beats quietly dropping it, and clicking
 * the ring opens the step 09 correction controls.
 */
export function buildConfidenceRingLayer(rows: Generation[], opts: LayerOpts = {}) {
  const { onClick, selectedId = null, overrides = null } = opts;
  // The ring flags a *building's* placement, so it goes with the building
  // during a reveal. Left on its own over the bare basemap it marks nothing.
  const reveal = clampReveal(opts.reveal ?? 1);
  const flagged = reveal <= 0
    ? []
    : rows
        .filter((r) => r.confidence_state === "auto-low")
        .map((r) => applyOverrides(r, selectedId, overrides));

  return new ScatterplotLayer<Generation>({
    id: "low-confidence-rings",
    data: flagged,
    opacity: reveal,
    getPosition: positionFor,
    stroked: true,
    filled: false,
    radiusUnits: "meters",
    // Sized to the building. A fixed radius was invisible around a 130 m hall
    // and swallowed anything small, so the flag only read at one zoom.
    getRadius: enclosingRadiusMeters,
    lineWidthUnits: "pixels",
    getLineWidth: 2,
    lineWidthMinPixels: 1.5,
    getLineColor: [217, 96, 59, 235], // --sn-warn
    pickable: true,
    onClick: (info) => {
      if (info.object) onClick?.(info.object);
    },
    updateTriggers: {
      getPosition: [selectedId, overrides?.position?.join(",")],
      getRadius: [selectedId],
    },
  });
}

/**
 * The ground each building stands in, coloured by its World State.
 *
 * Drawn first, under everything: concentric organic patches that fade out into
 * the untouched basemap, plus scattered debris/growth flecks. Without it a
 * flooded building and a scorched one sit on identical street tiles and the
 * World State only exists in the mesh texture — the map says nothing about the
 * place, which is the opposite of the pitch.
 */
export function buildTerrainLayers(rows: Generation[], reveal = 1) {
  // Each patch is blended against the others so differing states wash together
  // instead of meeting at a seam.
  const cells: TerrainCell[] = rows.flatMap((row) =>
    terrainCells(
      row,
      rows.filter((other) => other.id !== row.id),
    ),
  );
  const features: TerrainFeature[] = rows.flatMap(terrainFeatures);
  const shown = clampReveal(reveal);
  if (shown <= 0) return [];

  return [
    new PolygonLayer<TerrainCell>({
      id: "world-state-ground",
      opacity: shown,
      data: cells,
      getPolygon: (d: TerrainCell) => d.polygon,
      getFillColor: (d: TerrainCell) => d.color,
      getElevation: (d: TerrainCell) => d.elevation,
      extruded: true,
      filled: true,
      stroked: false,
      material: { ambient: 0.75, diffuse: 0.5, shininess: 8, specularColor: [40, 40, 40] },
      pickable: false,
    }),
    // Extruded features shrink to nothing as you pull back, so debris and
    // wreckage vanish at district zoom exactly when the wide shot needs texture.
    // These dots hold a minimum pixel size and keep the ground reading as
    // littered rather than bare; up close the real geometry dominates them.
    new ScatterplotLayer<TerrainFeature>({
      id: "world-state-feature-dots",
      opacity: shown,
      data: features,
      getPosition: (d: TerrainFeature) => [d.position[0], d.position[1]],
      getRadius: (d: TerrainFeature) => d.radius * 0.85,
      getFillColor: (d: TerrainFeature) => d.color,
      radiusUnits: "meters",
      radiusMinPixels: 1.6,
      stroked: false,
      filled: true,
      pickable: false,
    }),
    new PolygonLayer<TerrainFeature>({
      id: "world-state-features",
      opacity: shown,
      data: features,
      getPolygon: featurePolygon,
      getFillColor: (d: TerrainFeature) => d.color,
      getElevation: (d: TerrainFeature) => d.elevation,
      extruded: true,
      filled: true,
      stroked: false,
      material: { ambient: 0.6, diffuse: 0.65, shininess: 12, specularColor: [50, 50, 50] },
      pickable: false,
    }),
  ];
}

/**
 * Contact shadow under each building.
 *
 * A ScenegraphLayer draws the mesh floating in screen space with nothing tying
 * it to the ground, so buildings read as pasted onto the tiles. deck.gl's real
 * shadow pass was tried and leaves hard artifacts across the mesh itself on an
 * overlaid MapboxOverlay, so this is drawn geometrically instead: the actual
 * footprint rectangle, rotated to the building's yaw, as two stacked polygons —
 * a wide faint one for falloff and a tighter darker one for contact.
 */
export function buildGroundShadowLayers(rows: Generation[], reveal = 1) {
  const shown = clampReveal(reveal);
  if (shown <= 0) return [];
  const shadow = (id: string, inflate: number, color: [number, number, number, number]) =>
    new PolygonLayer<Generation>({
      id,
      data: rows,
      opacity: shown,
      getPolygon: (d: Generation) => footprintCorners(d, inflate),
      getFillColor: color,
      stroked: false,
      filled: true,
      extruded: false,
      pickable: false,
    });

  return [
    shadow("ground-shadow-soft", 1.13, [24, 28, 34, 26]),
    shadow("ground-shadow-core", 1.0, [20, 24, 30, 56]),
  ];
}

/** Neighbours inside the propagate radius that have no pre-baked row yet. */
export function buildPendingLayer(
  pending: { lat: number; lng: number }[] | null | undefined,
) {
  return new ScatterplotLayer({
    id: "propagate-pending",
    data: pending ?? [],
    getPosition: (d: { lat: number; lng: number }) => [
      Number(d.lng),
      Number(d.lat),
      0,
    ],
    stroked: true,
    filled: false,
    radiusUnits: "meters",
    getRadius: 10,
    lineWidthUnits: "meters",
    getLineWidth: 0.8,
    getLineColor: [150, 140, 125, 200],
    pickable: false,
  });
}

/** Radius indicator for the active propagate selection. */
export function buildRadiusLayer(
  source: Generation | null | undefined,
  radiusMeters: number | null | undefined,
) {
  if (!source || !radiusMeters) return null;
  return new ScatterplotLayer<Generation>({
    id: "propagate-radius",
    data: [source],
    getPosition: positionFor,
    stroked: true,
    filled: true,
    radiusUnits: "meters",
    getRadius: radiusMeters,
    lineWidthUnits: "pixels",
    getLineWidth: 2,
    lineWidthMinPixels: 2,
    getLineColor: [200, 144, 58, 220],
    getFillColor: [200, 144, 58, 30],
    pickable: false,
  });
}

/** Labels, so a judge can tell which building is which without clicking. */
export function buildLabelLayer(rows: Generation[]) {
  return new TextLayer<Generation>({
    id: "building-labels",
    data: rows,
    getPosition: positionFor,
    getText: (d: Generation) => (d.address || "").split(",")[0],
    getSize: 12,
    getColor: [232, 224, 210, 235],
    getPixelOffset: [0, -34],
    background: true,
    getBackgroundColor: [27, 24, 19, 215],
    backgroundPadding: [5, 3],
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    pickable: false,
  });
}

/**
 * A placeholder block where a building is being generated right now.
 *
 * Generation runs 30–90 seconds through two model calls, and until this the
 * only sign of it was a line of text in the side panel. On the map — which is
 * where everyone is looking — nothing happened at all, so a slow success and
 * a silent failure were indistinguishable for a minute and a half. This puts
 * the building's real footprint down immediately, at its real size, so the
 * wait happens in the place the result will appear.
 */
export interface GhostBuilding {
  lat: number;
  lng: number;
  widthMeters?: number | null;
  depthMeters?: number | null;
  rotationDegrees?: number | null;
  /** Roughly how tall to draw the block, in metres. */
  heightMeters?: number | null;
}

export function buildGhostLayers(ghost: GhostBuilding | null | undefined) {
  if (!ghost) return [];
  // Reuse footprintCorners by handing it a row-shaped object: the ghost is
  // meant to sit exactly where the finished building will.
  const asRow = {
    lat: ghost.lat,
    lng: ghost.lng,
    placement: {
      position: [ghost.lat, ghost.lng, 0],
      rotationDegrees: ghost.rotationDegrees ?? 0,
      footprintWidthMeters: ghost.widthMeters ?? undefined,
      footprintDepthMeters: ghost.depthMeters ?? undefined,
    },
  } as unknown as Generation;

  const height = Math.max(6, Number(ghost.heightMeters) || 18);
  return [
    new PolygonLayer<Generation>({
      id: "ghost-building",
      data: [asRow],
      getPolygon: (d: Generation) => footprintCorners(d, 1),
      getFillColor: [201, 138, 60, 44],
      getLineColor: [201, 138, 60, 200],
      getElevation: height,
      extruded: true,
      filled: true,
      stroked: true,
      wireframe: true,
      lineWidthUnits: "pixels",
      getLineWidth: 1.5,
      lineWidthMinPixels: 1.5,
      material: { ambient: 0.9, diffuse: 0.2, shininess: 1, specularColor: [0, 0, 0] },
      pickable: false,
    }),
    new PolygonLayer<Generation>({
      id: "ghost-building-base",
      data: [asRow],
      getPolygon: (d: Generation) => footprintCorners(d, 1.06),
      getFillColor: [201, 138, 60, 26],
      stroked: false,
      filled: true,
      extruded: false,
      pickable: false,
    }),
  ];
}
