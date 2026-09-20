import { describe, expect, it } from "vitest";
import { buildUrlSearch, parseUrlState } from "../map/useUrlState";
import type { UrlState } from "../map/useUrlState";

const base: UrlState = {
  buildingId: null, center: null, zoom: null, pitch: null,
  bearing: null, satellite: null, labels: null, reveal: null,
};

describe("reading the view out of the URL", () => {
  it("picks up a building, a camera and the toggles", () => {
    const s = parseUrlState("?b=abc&c=37.2287,-80.4229&z=17.5&p=55&r=120&sat=1&lbl=0&rv=0.4");
    expect(s.buildingId).toBe("abc");
    expect(s.center).toEqual({ lat: 37.2287, lng: -80.4229 });
    expect(s.zoom).toBe(17.5);
    expect(s.pitch).toBe(55);
    expect(s.bearing).toBe(120);
    expect(s.satellite).toBe(true);
    expect(s.labels).toBe(false);
    expect(s.reveal).toBe(0.4);
  });

  it("reads an empty query as nothing set, not as defaults", () => {
    // `null` and `false` are different answers: absent means "use the app's
    // default", not "the user turned satellite off".
    expect(parseUrlState("")).toEqual(base);
    expect(parseUrlState("?").satellite).toBeNull();
  });

  it("drops a half-parsed coordinate rather than flying somewhere wrong", () => {
    // `c=37.2287` alone would otherwise read as lng NaN and put the camera in
    // the Gulf of Guinea, which looks exactly like a placement bug.
    expect(parseUrlState("?c=37.2287").center).toBeNull();
    expect(parseUrlState("?c=north,west").center).toBeNull();
  });

  it("ignores non-numeric camera values", () => {
    expect(parseUrlState("?z=far&p=&r=abc").zoom).toBeNull();
    expect(parseUrlState("?z=far").pitch).toBeNull();
  });
});

describe("writing the view into the URL", () => {
  it("round-trips a full state", () => {
    const state: UrlState = {
      buildingId: "abc",
      center: { lat: 37.2287, lng: -80.4229 },
      zoom: 17.5, pitch: 55, bearing: 120,
      satellite: true, labels: false, reveal: 0.4,
    };
    const parsed = parseUrlState(buildUrlSearch(state));
    expect(parsed.buildingId).toBe("abc");
    expect(parsed.center?.lat).toBeCloseTo(37.2287, 5);
    expect(parsed.satellite).toBe(true);
    expect(parsed.labels).toBe(false);
    expect(parsed.reveal).toBeCloseTo(0.4, 2);
  });

  it("leaves defaults out so a link stays readable", () => {
    const search = buildUrlSearch({
      ...base, satellite: false, labels: true, reveal: 1, zoom: 17,
    });
    expect(search).not.toContain("sat=");
    expect(search).not.toContain("lbl=");
    expect(search).not.toContain("rv=");
    expect(search).toContain("z=17.00");
  });

  it("is empty when nothing is set", () => {
    expect(buildUrlSearch(base)).toBe("");
  });

  it("escapes a building id rather than breaking the query", () => {
    const search = buildUrlSearch({ ...base, buildingId: "a b&c=d" });
    expect(parseUrlState(search).buildingId).toBe("a b&c=d");
  });
});
