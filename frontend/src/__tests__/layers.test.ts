import { describe, expect, it } from "vitest";
import {
  UP_AXIS_ROLL,
  groupByMesh,
  orientationFor,
  positionFor,
  scaleFor,
  visibleRows,
} from "../map/layers";
import type { Generation } from "../types/contract";

const row = (over: Partial<Generation> = {}): Generation =>
  ({
    id: "a",
    address: "Burruss Hall, Blacksburg, VA",
    lat: 37.2287,
    lng: -80.4229,
    source_photo: null,
    artifact: null,
    mesh_url: "/placeholder.glb",
    world_state: "reclaimed",
    confidence_state: "auto-high",
    created_at: "2026-09-19T00:00:00Z",
    placement: {
      rotationDegrees: 47.5,
      scale: 1.8,
      position: [37.2287, -80.4229, 2.5],
      confidence: "auto-high",
      scoredRotationCandidates: [],
    },
    ...over,
  }) as Generation;

describe("positionFor", () => {
  it("converts stored [lat, lng] into deck.gl [lng, lat, z] order", () => {
    // Getting this backwards puts every building in the Indian Ocean.
    expect(positionFor(row())).toEqual([-80.4229, 37.2287, 2.5]);
  });

  it("defaults z to 0 when step 08 omitted ground alignment", () => {
    expect(positionFor(row({ placement: {} as never }))[2]).toBe(0);
  });
});

describe("orientationFor", () => {
  it("is [pitch, yaw, roll] with roll=90 for Y-up glTF", () => {
    // Verified visually against a real mesh: at roll=0 buildings lie flat.
    expect(orientationFor(row())).toEqual([0, 47.5, 90]);
    expect(UP_AXIS_ROLL).toBe(90);
  });

  it("accepts a roll override so a different mesh convention can be corrected", () => {
    expect(orientationFor(row(), 0)).toEqual([0, 47.5, 0]);
  });

  it("falls back to 0 yaw rather than NaN when rotation is missing", () => {
    expect(orientationFor({ placement: {} } as never)).toEqual([0, 0, 90]);
  });
});

describe("scaleFor", () => {
  it("applies the uniform scale on all three axes", () => {
    expect(scaleFor(row())).toEqual([1.8, 1.8, 1.8]);
  });

  it("never collapses a mesh to zero when scale is missing or invalid", () => {
    expect(scaleFor({ placement: {} } as never)).toEqual([1, 1, 1]);
    expect(scaleFor({ placement: { scale: 0 } } as never)).toEqual([1, 1, 1]);
  });
});

describe("groupByMesh", () => {
  it("groups rows per distinct mesh url", () => {
    // deck.gl's `scenegraph` prop is not a per-row accessor, so each distinct
    // mesh needs its own layer. This grouping is what makes that work.
    const rows = [
      row({ id: "a", mesh_url: "/one.glb" }),
      row({ id: "b", mesh_url: "/two.glb" }),
      row({ id: "c", mesh_url: "/one.glb" }),
    ];
    const groups = groupByMesh(rows);
    expect([...groups.keys()].sort()).toEqual(["/one.glb", "/two.glb"]);
    expect(groups.get("/one.glb")!.map((r) => r.id)).toEqual(["a", "c"]);
  });

  it("routes rows with no mesh to the placeholder instead of dropping them", () => {
    const groups = groupByMesh([row({ mesh_url: null })], "/placeholder.glb");
    expect(groups.get("/placeholder.glb")).toHaveLength(1);
  });
});

describe("visibleRows", () => {
  const row = (id: string, address: string, created_at: string) =>
    ({ id, address, created_at, placement: {}, mesh_url: `/${id}.glb` }) as never;

  it("keeps only the newest generation per address", () => {
    const rows = [
      row("a1", "Burruss Hall", "2026-09-19T01:00:00Z"),
      row("a2", "Burruss Hall", "2026-09-19T02:00:00Z"),
      row("b1", "Torgersen Hall", "2026-09-19T01:30:00Z"),
    ];
    expect(visibleRows(rows).map((r) => r.id).sort()).toEqual(["a2", "b1"]);
  });

  it("shows the selected generation instead, so picking a history entry swaps the mesh", () => {
    const rows = [
      row("a1", "Burruss Hall", "2026-09-19T01:00:00Z"),
      row("a2", "Burruss Hall", "2026-09-19T02:00:00Z"),
    ];
    expect(visibleRows(rows, "a1").map((r) => r.id)).toEqual(["a1"]);
  });

  it("does not collapse rows that have no address", () => {
    const rows = [row("a1", "", "2026-09-19T01:00:00Z"), row("a2", "", "2026-09-19T02:00:00Z")];
    expect(visibleRows(rows)).toHaveLength(2);
  });
});
