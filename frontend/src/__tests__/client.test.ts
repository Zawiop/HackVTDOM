import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  deleteAddress,
  deleteGeneration,
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
      // A real Response always has these; the stub needs them too now that
      // request() checks for an empty body before parsing.
      headers: new Headers({ "content-type": "application/json" }),
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


describe("removing buildings", () => {
  it("a 204 is a success, not an empty-body parse error", async () => {
    // DELETE returns no body. Parsing it as JSON would throw on a call that
    // actually succeeded, and the UI would report a failed removal.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 204,
        headers: new Headers(),
        json: async () => {
          throw new Error("no body to parse");
        },
      })),
    );
    await expect(deleteGeneration("abc")).resolves.toBeUndefined();
  });

  it("reports how many states were removed with the building", async () => {
    stubFetch(200, { address: "Burruss Hall", removed: 3 });
    await expect(deleteAddress("Burruss Hall")).resolves.toEqual({
      address: "Burruss Hall",
      removed: 3,
    });
  });

  it("url-encodes the address", async () => {
    stubFetch(200, { address: "x", removed: 0 });
    await deleteAddress("Burruss Hall, Blacksburg, VA");
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("Burruss%20Hall%2C%20Blacksburg%2C%20VA"),
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("surfaces a failed removal instead of pretending it worked", async () => {
    stubFetch(404, { detail: "no generation with id 'gone'" });
    await expect(deleteGeneration("gone")).rejects.toMatchObject({ status: 404 });
  });
});
