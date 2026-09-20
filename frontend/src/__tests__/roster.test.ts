import { describe, expect, it } from "vitest";
import { buildRoster, nextFlagged, shortName } from "../panel/BuildingRoster";
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
    world_state: "flooded",
    confidence_state: "auto-high",
    created_at: "2026-09-19T00:00:00Z",
    placement: { rotationDegrees: 0, scale: 1, position: [37.2287, -80.4229, 0] },
    ...over,
  }) as Generation;

describe("the building roster", () => {
  it("groups states under one building, not one entry each", () => {
    const rows = [
      row({ id: "1", world_state: "scorched" }),
      row({ id: "2", world_state: "flooded", created_at: "2026-09-19T01:00:00Z" }),
    ];
    const roster = buildRoster(rows, null, null);
    expect(roster).toHaveLength(1);
    expect(roster[0].states).toHaveLength(2);
  });

  it("shows the state the map is showing", () => {
    const rows = [
      row({ id: "old", world_state: "scorched" }),
      row({ id: "new", world_state: "flooded", created_at: "2026-09-19T02:00:00Z" }),
    ];
    // Newest by default…
    expect(buildRoster(rows, null, null)[0].shown.id).toBe("new");
    // …but the selected row wins, exactly as it does on the map.
    expect(buildRoster(rows, "old", null)[0].shown.id).toBe("old");
    // …and so does a pin.
    expect(buildRoster(rows, null, new Set(["old"]))[0].shown.id).toBe("old");
  });

  it("flags a building whose hidden state is the low-confidence one", () => {
    // The flagged row is not the visible one. Reading the flag off the visible
    // state only would hide it from the fix queue entirely.
    const roster = buildRoster(
      [
        row({ id: "bad", confidence_state: "auto-low" }),
        row({ id: "good", created_at: "2026-09-19T03:00:00Z" }),
      ],
      null,
      null,
    );
    expect(roster[0].shown.id).toBe("good");
    expect(roster[0].flagged).toBe(true);
  });

  it("sorts by the short name a human reads", () => {
    const roster = buildRoster(
      [
        row({ id: "1", address: "Norris Hall, Blacksburg, VA" }),
        row({ id: "2", address: "Burruss Hall, Blacksburg, VA" }),
        row({ id: "3", address: "Hitt Hall, Blacksburg, VA" }),
      ],
      null,
      null,
    );
    expect(roster.map((e) => shortName(e.address))).toEqual([
      "Burruss Hall", "Hitt Hall", "Norris Hall",
    ]);
  });

  it("filters on name and on world state", () => {
    const rows = [
      row({ id: "1", address: "Norris Hall, VA", world_state: "buried" }),
      row({ id: "2", address: "Burruss Hall, VA", world_state: "flooded" }),
    ];
    expect(buildRoster(rows, null, null, "norris")).toHaveLength(1);
    expect(buildRoster(rows, null, null, "flooded")[0].address).toContain("Burruss");
    expect(buildRoster(rows, null, null, "nothing here")).toHaveLength(0);
  });

  it("handles a row with no address instead of collapsing them together", () => {
    const roster = buildRoster(
      [row({ id: "x", address: "" }), row({ id: "y", address: "" })],
      null,
      null,
    );
    expect(roster).toHaveLength(2);
    expect(shortName("")).toBe("unnamed");
  });
});

describe("stepping through flagged placements", () => {
  const flaggedRows = [
    row({ id: "f1", address: "A Hall", confidence_state: "auto-low" }),
    row({ id: "ok", address: "B Hall" }),
    row({ id: "f2", address: "C Hall", confidence_state: "auto-low" }),
  ];

  it("advances to the next flagged row and wraps", () => {
    const roster = buildRoster(flaggedRows, null, null);
    expect(nextFlagged(roster, null)?.id).toBe("f1");
    expect(nextFlagged(roster, "f1")?.id).toBe("f2");
    expect(nextFlagged(roster, "f2")?.id).toBe("f1");
  });

  it("is null when nothing is flagged", () => {
    const roster = buildRoster([row({ id: "ok" })], null, null);
    expect(nextFlagged(roster, null)).toBeNull();
  });
});
