import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, importWorld, peekUndo, seedWorld, undoLast, worldExportUrl } from "../api/client";

function mockFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  const fn = vi.fn(async () =>
    ({
      ok: status < 400,
      status,
      headers: { get: (k: string) => headers[k.toLowerCase()] ?? null },
      json: async () => body,
    }) as unknown as Response);
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("moving a world between machines", () => {
  it("hands the browser a URL rather than pulling a zip through JS", () => {
    // The bundle runs to hundreds of megabytes; streaming it straight to disk
    // beats buffering it into a blob first.
    expect(worldExportUrl()).toBe("/api/world/export");
    expect(worldExportUrl("json")).toBe("/api/world/export?format=json");
  });

  it("uploads a bundle as multipart and defaults to merging", async () => {
    const fetchMock = mockFetch(200, { imported: 3, skipped_already_present: 0 });
    const file = new File(["PK"], "world.zip", { type: "application/zip" });
    await importWorld(file);

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toContain("mode=merge");
    expect(init.body).toBeInstanceOf(FormData);
    // The browser has to set the multipart boundary itself.
    expect(init.headers).toEqual({});
  });

  it("asks for replace only when told to", async () => {
    const fetchMock = mockFetch(200, { imported: 1 });
    await importWorld(new File([""], "w.zip"), "replace");
    expect((fetchMock.mock.calls[0] as [string])[0]).toContain("mode=replace");
  });

  it("seeds from the repo without a body", async () => {
    const fetchMock = mockFetch(200, { imported: 8, available: 8 });
    const result = await seedWorld();
    expect(result.imported).toBe(8);
    expect((fetchMock.mock.calls[0] as [string])[0]).toContain("/api/world/seed");
  });

  it("surfaces a failed import instead of resolving quietly", async () => {
    mockFetch(400, { detail: "not a zip bundle and not valid JSON" });
    await expect(importWorld(new File([""], "bad.zip"))).rejects.toThrow(/not a zip/);
  });
});

describe("undo", () => {
  it("reports what would be restored", async () => {
    mockFetch(200, { available: true, count: 18, action: "reset-world" });
    const info = await peekUndo();
    expect(info.available).toBe(true);
    expect(info.count).toBe(18);
  });

  it("carries the 404 through so the caller can tell empty from broken", async () => {
    // "nothing to undo" and "undo failed" must not look the same.
    mockFetch(404, { detail: "nothing to undo" });
    await expect(undoLast()).rejects.toBeInstanceOf(ApiError);
    await expect(undoLast()).rejects.toMatchObject({ status: 404 });
  });

  it("returns how many rows came back", async () => {
    mockFetch(200, { restored: 18, in_batch: 18 });
    expect((await undoLast()).restored).toBe(18);
  });
});
