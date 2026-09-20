import { ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { ScenegraphLayer } from "@deck.gl/mesh-layers";
import { GLTFLoader } from "@loaders.gl/gltf";

import type { Generation, PlacementOverrides } from "../types/contract";

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
      pickable: true,
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
  const flagged = rows
    .filter((r) => r.confidence_state === "auto-low")
    .map((r) => applyOverrides(r, selectedId, overrides));

  return new ScatterplotLayer<Generation>({
    id: "low-confidence-rings",
    data: flagged,
    getPosition: positionFor,
    stroked: true,
    filled: false,
    radiusUnits: "meters",
    getRadius: 14,
    lineWidthUnits: "meters",
    getLineWidth: 1.1,
    getLineColor: [217, 96, 59, 235], // --sn-warn
    pickable: true,
    onClick: (info) => {
      if (info.object) onClick?.(info.object);
    },
    updateTriggers: { getPosition: [selectedId, overrides?.position?.join(",")] },
  });
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
