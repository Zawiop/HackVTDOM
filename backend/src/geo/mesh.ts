import { area as ringArea, convexHull, bounds as ringBounds, type Ring } from './polygon.js';
import type { PointMeters } from './latlng.js';

/**
 * Mesh geometry reader for the placement step.
 *
 * Step 08 needs two things from the mesh step 07 hands over: the base outline
 * (to rotate and score against the OSM polygon) and the vertical extent (to sit
 * the base on the ground). Both come from vertex positions alone, so this reads
 * POSITION accessors and the scene graph and ignores materials, textures,
 * animations and everything else in the file.
 *
 * Supports .glb (binary glTF) and .obj — spec 06 notes TripoSR typically emits
 * .obj and that conversion to .glb happens somewhere before step 07's output.
 */

export type UpAxis = 'y' | 'z';

export interface MeshGeometry {
  /** World-space vertex positions after applying node transforms. */
  positions: Float64Array;
  vertexCount: number;
  min: [number, number, number];
  max: [number, number, number];
}

export interface MeshFootprint {
  /** Convex outline of the mesh base, in the horizontal plane, mesh units. */
  outline: Ring;
  /** Height of the slab the outline was taken from, as a fraction of total height. */
  slabFraction: number;
  /** Lowest point along the up axis. Should be ~0 if step 07 base-centred it. */
  baseOffset: number;
  /** Total extent along the up axis. */
  heightUnits: number;
  width: number;
  depth: number;
  upAxis: UpAxis;
  /** Number of vertices in the resulting outline. */
  vertexCount: number;
}

// ---------------------------------------------------------------------------
// glTF / GLB
// ---------------------------------------------------------------------------

const GLB_MAGIC = 0x46546c67; // 'glTF'
const CHUNK_JSON = 0x4e4f534a;
const CHUNK_BIN = 0x004e4942;

const COMPONENT_READERS: Record<number, { size: number; read: (dv: DataView, o: number) => number }> = {
  5120: { size: 1, read: (dv, o) => dv.getInt8(o) },
  5121: { size: 1, read: (dv, o) => dv.getUint8(o) },
  5122: { size: 2, read: (dv, o) => dv.getInt16(o, true) },
  5123: { size: 2, read: (dv, o) => dv.getUint16(o, true) },
  5125: { size: 4, read: (dv, o) => dv.getUint32(o, true) },
  5126: { size: 4, read: (dv, o) => dv.getFloat32(o, true) },
};

type Mat4 = number[];

const IDENTITY: Mat4 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];

/** Column-major multiply, matching glTF's matrix convention. */
function multiply(a: Mat4, b: Mat4): Mat4 {
  const out = new Array<number>(16).fill(0);
  for (let c = 0; c < 4; c++) {
    for (let r = 0; r < 4; r++) {
      let sum = 0;
      for (let k = 0; k < 4; k++) sum += a[k * 4 + r]! * b[c * 4 + k]!;
      out[c * 4 + r] = sum;
    }
  }
  return out;
}

function trsToMatrix(node: {
  matrix?: number[];
  translation?: number[];
  rotation?: number[];
  scale?: number[];
}): Mat4 {
  if (Array.isArray(node.matrix) && node.matrix.length === 16) return node.matrix;

  const [tx, ty, tz] = node.translation ?? [0, 0, 0];
  const [qx, qy, qz, qw] = node.rotation ?? [0, 0, 0, 1];
  const [sx, sy, sz] = node.scale ?? [1, 1, 1];

  // Quaternion -> rotation matrix, then fold in scale, column-major.
  const x2 = qx! + qx!;
  const y2 = qy! + qy!;
  const z2 = qz! + qz!;
  const xx = qx! * x2;
  const xy = qx! * y2;
  const xz = qx! * z2;
  const yy = qy! * y2;
  const yz = qy! * z2;
  const zz = qz! * z2;
  const wx = qw! * x2;
  const wy = qw! * y2;
  const wz = qw! * z2;

  return [
    (1 - (yy + zz)) * sx!, (xy + wz) * sx!, (xz - wy) * sx!, 0,
    (xy - wz) * sy!, (1 - (xx + zz)) * sy!, (yz + wx) * sy!, 0,
    (xz + wy) * sz!, (yz - wx) * sz!, (1 - (xx + yy)) * sz!, 0,
    tx!, ty!, tz!, 1,
  ];
}

function transformPoint(m: Mat4, x: number, y: number, z: number): [number, number, number] {
  return [
    m[0]! * x + m[4]! * y + m[8]! * z + m[12]!,
    m[1]! * x + m[5]! * y + m[9]! * z + m[13]!,
    m[2]! * x + m[6]! * y + m[10]! * z + m[14]!,
  ];
}

interface GltfJson {
  scene?: number;
  scenes?: Array<{ nodes?: number[] }>;
  nodes?: Array<{
    mesh?: number;
    children?: number[];
    matrix?: number[];
    translation?: number[];
    rotation?: number[];
    scale?: number[];
  }>;
  meshes?: Array<{ primitives?: Array<{ attributes?: Record<string, number> }> }>;
  accessors?: Array<{
    bufferView?: number;
    byteOffset?: number;
    componentType: number;
    count: number;
    type: string;
    min?: number[];
    max?: number[];
  }>;
  bufferViews?: Array<{ buffer: number; byteOffset?: number; byteLength: number; byteStride?: number }>;
}

export class MeshParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'MeshParseError';
  }
}

function readAccessorVec3(json: GltfJson, bin: Uint8Array, index: number): number[][] {
  const accessor = json.accessors?.[index];
  if (!accessor) throw new MeshParseError(`Accessor ${index} missing`);
  if (accessor.type !== 'VEC3') {
    throw new MeshParseError(`POSITION accessor ${index} is ${accessor.type}, expected VEC3`);
  }

  const reader = COMPONENT_READERS[accessor.componentType];
  if (!reader) {
    throw new MeshParseError(`Unsupported componentType ${accessor.componentType}`);
  }
  if (accessor.bufferView === undefined) {
    // A sparse or zero-filled accessor. Nothing useful to read.
    return [];
  }

  const view = json.bufferViews?.[accessor.bufferView];
  if (!view) throw new MeshParseError(`bufferView ${accessor.bufferView} missing`);

  const elementSize = reader.size * 3;
  const stride = view.byteStride && view.byteStride > 0 ? view.byteStride : elementSize;
  const base = (view.byteOffset ?? 0) + (accessor.byteOffset ?? 0);
  const dv = new DataView(bin.buffer, bin.byteOffset, bin.byteLength);

  const out: number[][] = [];
  for (let i = 0; i < accessor.count; i++) {
    const o = base + i * stride;
    if (o + elementSize > bin.byteLength) break;
    out.push([reader.read(dv, o), reader.read(dv, o + reader.size), reader.read(dv, o + 2 * reader.size)]);
  }
  return out;
}

/** Parse a binary glTF buffer into world-space vertex positions. */
export function parseGlb(buffer: Buffer): MeshGeometry {
  if (buffer.byteLength < 12) throw new MeshParseError('File too short to be a GLB');

  const header = new DataView(buffer.buffer, buffer.byteOffset, buffer.byteLength);
  if (header.getUint32(0, true) !== GLB_MAGIC) {
    throw new MeshParseError('Not a GLB (magic bytes are not "glTF")');
  }

  let offset = 12;
  let json: GltfJson | null = null;
  let bin: Uint8Array = new Uint8Array(0);

  while (offset + 8 <= buffer.byteLength) {
    const chunkLength = header.getUint32(offset, true);
    const chunkType = header.getUint32(offset + 4, true);
    const start = offset + 8;
    const end = Math.min(start + chunkLength, buffer.byteLength);

    if (chunkType === CHUNK_JSON) {
      json = JSON.parse(buffer.subarray(start, end).toString('utf8')) as GltfJson;
    } else if (chunkType === CHUNK_BIN) {
      bin = new Uint8Array(buffer.subarray(start, end));
    }
    offset = start + chunkLength + ((4 - (chunkLength % 4)) % 4);
  }

  if (!json) throw new MeshParseError('GLB has no JSON chunk');
  return collectPositions(json, bin);
}

function collectPositions(json: GltfJson, bin: Uint8Array): MeshGeometry {
  const positions: number[] = [];
  const min: [number, number, number] = [Infinity, Infinity, Infinity];
  const max: [number, number, number] = [-Infinity, -Infinity, -Infinity];

  const visit = (nodeIndex: number, parent: Mat4, depth: number) => {
    // Guards a malformed file with a cyclic node graph.
    if (depth > 64) return;
    const node = json.nodes?.[nodeIndex];
    if (!node) return;

    const world = multiply(parent, trsToMatrix(node));

    if (node.mesh !== undefined) {
      for (const prim of json.meshes?.[node.mesh]?.primitives ?? []) {
        const accessor = prim.attributes?.POSITION;
        if (accessor === undefined) continue;
        for (const [x, y, z] of readAccessorVec3(json, bin, accessor)) {
          const p = transformPoint(world, x!, y!, z!);
          positions.push(p[0], p[1], p[2]);
          for (let i = 0; i < 3; i++) {
            if (p[i]! < min[i]!) min[i] = p[i]!;
            if (p[i]! > max[i]!) max[i] = p[i]!;
          }
        }
      }
    }

    for (const child of node.children ?? []) visit(child, world, depth + 1);
  };

  const sceneIndex = json.scene ?? 0;
  const roots = json.scenes?.[sceneIndex]?.nodes ?? json.nodes?.map((_, i) => i) ?? [];
  for (const root of roots) visit(root, IDENTITY, 0);

  if (positions.length === 0) throw new MeshParseError('Mesh contains no POSITION data');

  return {
    positions: Float64Array.from(positions),
    vertexCount: positions.length / 3,
    min,
    max,
  };
}

/** Parse a Wavefront OBJ. Only `v` lines matter for placement. */
export function parseObj(text: string): MeshGeometry {
  const positions: number[] = [];
  const min: [number, number, number] = [Infinity, Infinity, Infinity];
  const max: [number, number, number] = [-Infinity, -Infinity, -Infinity];

  for (const line of text.split('\n')) {
    if (line.charCodeAt(0) !== 118 /* 'v' */ || line.charCodeAt(1) !== 32 /* ' ' */) continue;
    const parts = line.trim().split(/\s+/);
    const x = Number(parts[1]);
    const y = Number(parts[2]);
    const z = Number(parts[3]);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) continue;

    positions.push(x, y, z);
    const p = [x, y, z];
    for (let i = 0; i < 3; i++) {
      if (p[i]! < min[i]!) min[i] = p[i]!;
      if (p[i]! > max[i]!) max[i] = p[i]!;
    }
  }

  if (positions.length === 0) throw new MeshParseError('OBJ contains no vertex positions');

  return { positions: Float64Array.from(positions), vertexCount: positions.length / 3, min, max };
}

export function parseMesh(bytes: Buffer, hint?: string): MeshGeometry {
  const looksGlb =
    bytes.byteLength >= 4 &&
    new DataView(bytes.buffer, bytes.byteOffset, 4).getUint32(0, true) === GLB_MAGIC;

  if (looksGlb) return parseGlb(bytes);
  if (hint?.toLowerCase().endsWith('.obj') || bytes.subarray(0, 512).includes(Buffer.from('\nv '))) {
    return parseObj(bytes.toString('utf8'));
  }
  throw new MeshParseError(
    `Unrecognised mesh format${hint ? ` for "${hint}"` : ''} — expected .glb or .obj`,
  );
}

// ---------------------------------------------------------------------------
// Base outline
// ---------------------------------------------------------------------------

/** Axis index pairs: which two axes are horizontal, for each up-axis convention. */
const HORIZONTAL: Record<UpAxis, [number, number]> = {
  y: [0, 2], // glTF convention: Y up, so X/Z are the ground plane
  z: [0, 1],
};
const UP_INDEX: Record<UpAxis, number> = { y: 1, z: 2 };

export interface BaseOutlineOptions {
  upAxis?: UpAxis;
  /** Slab height as a fraction of total mesh height. Widened if it is too thin. */
  slabFraction?: number;
  /**
   * Widen the slab while its hull covers less than this fraction of the mesh's
   * full top-down silhouette. Guards against a sparse or noisy lowest layer
   * without punishing a clean low-poly base.
   */
  minBaseCoverage?: number;
}

/**
 * The mesh's base outline: the convex hull of the vertices sitting in a thin
 * slab just above the lowest point.
 *
 * Why the base and not the whole silhouette from above: step 08 scores this
 * against the OSM *footprint*, which is where the building meets the ground. A
 * roof overhang or a spire would inflate a top-down silhouette and bias both the
 * IoU search and the scale fit.
 *
 * The slab widens when its hull is degenerate or covers a tiny fraction of the
 * mesh's overall silhouette — photogrammetry-style output often has a sparse,
 * noisy lowest layer. The test is on hull *area*, not vertex count, so a clean
 * low-poly base (a cube's four corners) is accepted as-is rather than widened
 * into meaninglessness.
 */
export function meshBaseFootprint(
  geometry: MeshGeometry,
  options: BaseOutlineOptions = {},
): MeshFootprint {
  const upAxis = options.upAxis ?? 'y';
  const up = UP_INDEX[upAxis];
  const [hA, hB] = HORIZONTAL[upAxis];

  const minUp = geometry.min[up]!;
  const maxUp = geometry.max[up]!;
  const height = maxUp - minUp;

  const allPoints: PointMeters[] = [];
  for (let i = 0; i < geometry.vertexCount; i++) {
    const base = i * 3;
    allPoints.push([geometry.positions[base + hA]!, geometry.positions[base + hB]!]);
  }

  // The whole-mesh silhouette, used only as the yardstick for "is this slab
  // giving us a real outline or a sliver?".
  const silhouetteArea = ringArea(convexHull(allPoints));
  const minCoverage = options.minBaseCoverage ?? 0.25;

  let slabFraction = options.slabFraction ?? 0.12;
  let outline: Ring = [];

  for (let attempt = 0; attempt < 6; attempt++) {
    const cutoff = minUp + Math.max(height * slabFraction, 1e-9);
    const slab: PointMeters[] = [];
    for (let i = 0; i < geometry.vertexCount; i++) {
      const base = i * 3;
      if (geometry.positions[base + up]! <= cutoff) {
        slab.push([geometry.positions[base + hA]!, geometry.positions[base + hB]!]);
      }
    }

    outline = convexHull(slab);
    const covered = silhouetteArea > 0 ? ringArea(outline) / silhouetteArea : 0;
    if (outline.length >= 3 && covered >= minCoverage) break;
    if (slabFraction >= 1) break;
    slabFraction = Math.min(1, slabFraction * 2);
  }

  // Last resort: a flat mesh, or one with no distinct base at all.
  if (outline.length < 3) {
    outline = convexHull(allPoints);
    slabFraction = 1;
  }

  const b = ringBounds(outline);

  return {
    outline,
    slabFraction,
    baseOffset: minUp,
    heightUnits: height,
    width: b.width,
    depth: b.depth,
    upAxis,
    vertexCount: outline.length,
  };
}
