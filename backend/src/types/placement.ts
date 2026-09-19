import type { LatLng } from '../geo/latlng.js';
import type { UpAxis } from '../geo/mesh.js';

/** ---- Inputs ------------------------------------------------------------ */

/** A candidate building polygon, as step 02 returns it. */
export interface FootprintPolygon {
  /** OSM way id, when known. Used to exclude the target from its own neighbours. */
  id?: string | number;
  /** Closed or open ring of lat/lng vertices. */
  geometry: LatLng[];
  tags?: Record<string, string>;
}

export interface FootprintInput {
  /** The polygon the mesh is being placed on. */
  polygon: FootprintPolygon;
  /**
   * Other buildings already fetched in step 02. Reused here for the collision
   * check — spec 08 is explicit that this must not trigger a new Overpass call.
   */
  neighbors?: FootprintPolygon[];
  /** Step 02's derived values. Cross-checked here, not trusted blindly. */
  footprintWidthMeters?: number;
  footprintDepthMeters?: number;
  longestEdgeBearingDegrees?: number;
  /** Step 02's own match confidence. A low value here propagates. */
  confidence?: 'high' | 'low';
}

export interface MeshInput {
  /** A local path or file:// URL to the normalized mesh from step 07. */
  path?: string;
  /** An http(s) URL to the same. */
  url?: string;
  /** Raw bytes, when the caller already has them. */
  bytes?: Buffer;
  /**
   * Up-axis convention of the mesh. glTF is Y-up, which is the default. Step 07
   * owns this; a mismatch is reported, never silently corrected.
   */
  upAxis?: UpAxis;
  /**
   * Pre-computed base outline in mesh units, if step 07 already produced one.
   * Skips parsing the file.
   */
  baseOutline?: Array<[number, number]>;
  /** Vertical extent, required alongside `baseOutline`. */
  baseOffset?: number;
  heightUnits?: number;
}

export interface PlacementOptions {
  /**
   * Coverage below which uniform scaling counts as "badly undersized" and the
   * non-uniform fallback kicks in. Spec 08 asks for a concrete threshold rather
   * than per-building eyeballing; ~30% smaller on one axis is its own example.
   */
  undersizeThreshold?: number;
  /** Neighbour bbox overlap (as a fraction of the mesh bbox) that flags low. */
  collisionThreshold?: number;
  /**
   * Fit quality (achieved IoU / the best a convex outline could score against
   * this polygon) below which the rotation search is considered unconvincing.
   */
  minFitQuality?: number;
  /** IoU gap below which the top two rotations are too close to call. */
  rotationAmbiguityMargin?: number;
}

/** ---- Output ------------------------------------------------------------ */

export type PlacementConfidence = 'auto-high' | 'auto-low';

export interface ScoredRotationCandidate {
  /** Offset from the footprint's longest-edge bearing: 0, 90, 180 or 270. */
  offsetDegrees: number;
  /** Absolute compass heading applied to the mesh. */
  rotationDegrees: number;
  iou: number;
  intersectionAreaSqM: number;
  /** The uniform scale that best fits the mesh at this rotation. */
  scale: number;
  /** Fraction of the footprint's width/depth the scaled mesh actually covers. */
  coverage: [number, number];
}

export interface CollisionOverlap {
  neighborId: string | number | null;
  overlapAreaSqM: number;
  /** The worse of the two ratios below. This is what the threshold judges. */
  overlapRatio: number;
  /** Overlap as a fraction of the placed mesh's own footprint area. */
  overlapRatioOfMesh: number;
  /** Overlap as a fraction of the neighbour's footprint area. */
  overlapRatioOfNeighbor: number;
}

export type FlagSubStep = 'footprint' | 'rotation' | 'scale' | 'collision' | 'ground' | 'mesh';

export interface PlacementFlag {
  subStep: FlagSubStep;
  code: string;
  message: string;
}

/**
 * The transform record. The five fields spec 08 names — rotationDegrees, scale,
 * position, confidence, scoredRotationCandidates — plus the working the
 * correction UI in step 09 needs to explain and undo each decision.
 */
export interface PlacementTransform {
  rotationDegrees: number;
  /** Uniform scale factor. Also the baseline for the non-uniform fallback. */
  scale: number;
  /** [lat, lng, z] — z is metres above ground for the mesh's model origin. */
  position: [number, number, number];
  confidence: PlacementConfidence;
  scoredRotationCandidates: ScoredRotationCandidate[];

  scaleMode: 'uniform' | 'non-uniform';
  /** Per-axis scale in renderer order, for deck.gl's getScale. */
  scaleXYZ: [number, number, number];

  /** Every reason the record is or isn't confident. Never silently dropped. */
  flags: PlacementFlag[];

  collision: {
    neighborsChecked: number;
    overlaps: CollisionOverlap[];
    worstOverlapRatio: number;
  };

  ground: {
    /** Lowest mesh vertex along the up axis, in mesh units, before scaling. */
    meshBaseOffsetUnits: number;
    /** Metres the mesh must be lifted so its base sits at ground level. */
    z: number;
  };

  diagnostics: {
    iou: number;
    /** IoU of the footprint against its own convex hull — the ceiling for any
     *  convex mesh outline, which is what a mesh base always is. */
    maxAchievableIou: number;
    /** `iou / maxAchievableIou`. What the confidence check actually judges. */
    fitQuality: number;
    footprintAreaSqM: number;
    placedMeshAreaSqM: number;
    footprintWidthMeters: number;
    footprintDepthMeters: number;
    longestEdgeBearingDegrees: number;
    /** The mesh's own longest-edge bearing. Reported, not used — see below. */
    meshLongestEdgeBearingDegrees: number;
    /** Min-area-rectangle axis of the footprint. The rotation search's basis. */
    footprintPrincipalAxisDegrees: number;
    /** Min-area-rectangle axis of the mesh outline, which the search cancels out. */
    meshPrincipalAxisDegrees: number;
    /** Metres the IoU refinement moved the mesh off a plain centroid match. */
    refinementShiftMeters: number;
    /**
     * How much better the winner scores than its own 180-degree flip. Near zero
     * for almost every building, because a footprint cannot tell a facade from
     * its back. Informational: step 09 can offer a "turn it around" control
     * without this routing the placement to manual review.
     */
    rotationFlipMargin: number | null;
    meshWidthUnits: number;
    meshDepthUnits: number;
    meshHeightUnits: number;
    scaledHeightMeters: number;
    upAxis: UpAxis;
    /** Present when step 02's derived numbers disagree with this module's. */
    footprintDerivedMismatch?: { field: string; reported: number; computed: number }[];
  };
}
