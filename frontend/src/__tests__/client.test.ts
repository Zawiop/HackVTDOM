import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  correctGeneration,
  getHistory,
  listGenerations,
  saveGeneration,
} from "../api/client";

afterEach(() => vi.unstubAllGlobals());

function stubFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    })),
  );
}

describe("persistence client error handling", () => {
  it("throws on a failed write instead of returning a falsy value", async () => {
    // Step 11: a failed save must never look like a success in the UI.
    stubFetch(502, { detail: "persistence.save_generation: connection refused" });
    await expect(
      saveGeneration({ address: "x", lat: 1, lng: 2 }),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("surfaces the backend detail message", async () => {
    stubFetch(502, { detail: "persistence.save_generation: boom" });
    await expect(saveGeneration({ address: "x", lat: 1, lng: 2 })).rejects.toThrow(
      /boom/,
    );
  });

  it("carries the status code for the UI to branch on", async () => {
    stubFetch(404, { detail: "no generation with id 'nope'" });
    await expect(correctGeneration("nope", { scale: 2 })).rejects.toMatchObject({
      status: 404,
    });
  });

  it("returns parsed rows on success", async () => {
    stubFetch(200, [{ id: "a" }]);
    await expect(listGenerations()).resolves.toEqual([{ id: "a" }]);
  });

  it("url-encodes addresses containing commas and spaces", async () => {
    stubFetch(200, []);
    await getHistory("Burruss Hall, Blacksburg, VA");
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining(
        "/api/history?address=Burruss%20Hall%2C%20Blacksburg%2C%20VA",
      ),
      expect.anything(),
    );
  });
});
