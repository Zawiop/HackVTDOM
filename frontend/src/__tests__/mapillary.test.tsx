import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import MapillarySuggestions from "../photo/MapillarySuggestions";

/**
 * Step 03 path B. The behaviour that matters is mostly about *restraint*: this
 * is a convenience layer, and `03-photo-input.md` says an empty result must
 * fall through silently to the required upload rather than surface an error.
 */

const BURRUSS = { lat: 37.2284, lng: -80.4234 };

function lookup(photos: unknown[]) {
  return vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).includes("/api/photo/mapillary")) {
      return new Response(
        JSON.stringify({
          attempted: true,
          attempts: 1,
          requiresManualUpload: photos.length === 0,
          photos,
        }),
        { headers: { "Content-Type": "application/json" } },
      );
    }
    // The thumbnail download when a capture is adopted.
    return new Response(new Blob(["jpeg-bytes"], { type: "image/jpeg" }));
  });
}

const photo = (over: Record<string, unknown> = {}) => ({
  source: "mapillary",
  id: "1137417950117930",
  url: "https://example.test/a.jpg",
  mimeType: "image/jpeg",
  location: { lat: 37.228, lng: -80.423 },
  distanceMeters: 23.1,
  // Epoch milliseconds, matching the backend contract.
  capturedAt: 1728604800000,
  ...over,
});

afterEach(() => vi.unstubAllGlobals());

describe("MapillarySuggestions", () => {
  it("shows nearby captures with their distance and date", async () => {
    vi.stubGlobal("fetch", lookup([photo()]));

    render(<MapillarySuggestions {...BURRUSS} onPick={vi.fn()} />);

    const strip = await screen.findByTestId("mapillary-suggestions");
    expect(within(strip).getByText(/23 m/)).toBeInTheDocument();
    expect(within(strip).getByText(/2024-10/)).toBeInTheDocument();
    // ODbL-adjacent attribution the spec asks for.
    expect(within(strip).getByText(/Mapillary contributors/)).toBeInTheDocument();
  });

  it("renders NOTHING where there is no coverage — not an error", async () => {
    vi.stubGlobal("fetch", lookup([]));

    render(<MapillarySuggestions lat={47.7} lng={-87.5} onPick={vi.fn()} />);

    await waitFor(() => expect(screen.queryByText(/checking for/i)).not.toBeInTheDocument());
    expect(screen.queryByTestId("mapillary-suggestions")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("stays equally silent when the lookup itself fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new Error("offline"))));

    render(<MapillarySuggestions {...BURRUSS} onPick={vi.fn()} />);

    await waitFor(() => expect(screen.queryByText(/checking for/i)).not.toBeInTheDocument());
    expect(screen.queryByTestId("mapillary-suggestions")).not.toBeInTheDocument();
  });

  it("does not look anything up before a building is located", () => {
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);

    render(<MapillarySuggestions lat={null} lng={null} onPick={vi.fn()} />);

    expect(spy).not.toHaveBeenCalled();
  });

  it("hands back real bytes, not the expiring CDN url", async () => {
    vi.stubGlobal("fetch", lookup([photo()]));
    const onPick = vi.fn();

    render(<MapillarySuggestions {...BURRUSS} onPick={onPick} />);
    const strip = await screen.findByTestId("mapillary-suggestions");

    await userEvent.click(within(strip).getByRole("button"));

    await waitFor(() => expect(onPick).toHaveBeenCalledOnce());
    const file = onPick.mock.calls[0][0] as File;
    expect(file).toBeInstanceOf(File);
    expect(file.type).toBe("image/jpeg");
    expect(file.name).toContain("1137417950117930");
  });

  it("caps the strip so it cannot crowd out the upload below it", async () => {
    vi.stubGlobal(
      "fetch",
      lookup(Array.from({ length: 9 }, (_, i) => photo({ id: `id-${i}` }))),
    );

    render(<MapillarySuggestions {...BURRUSS} onPick={vi.fn()} />);
    const strip = await screen.findByTestId("mapillary-suggestions");

    expect(within(strip).getAllByRole("listitem")).toHaveLength(4);
  });

  it("survives a capture with no location or date", async () => {
    vi.stubGlobal("fetch", lookup([photo({ distanceMeters: null, capturedAt: null, location: null })]));

    render(<MapillarySuggestions {...BURRUSS} onPick={vi.fn()} />);
    expect(await screen.findByTestId("mapillary-suggestions")).toBeInTheDocument();
  });
});
