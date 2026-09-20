import { describe, expect, it, vi } from "vitest";
import { compositeCanvases, postcardFilename } from "../map/postcard";

/** jsdom has no 2D context, so stand one up with the calls we make. */
function fakeCanvas(width: number, height: number) {
  const ctx = {
    fillStyle: "", font: "", textBaseline: "",
    fillRect: vi.fn(), drawImage: vi.fn(), fillText: vi.fn(),
    createLinearGradient: () => ({ addColorStop: vi.fn() }),
  };
  return {
    width, height,
    getContext: () => ctx as unknown as CanvasRenderingContext2D,
    __ctx: ctx,
  } as unknown as HTMLCanvasElement & { __ctx: typeof ctx };
}

describe("capturing the view as a postcard", () => {
  it("draws every layer, because the map and the buildings are separate canvases", () => {
    // Grabbing only MapLibre's canvas gives a picture of Blacksburg with no
    // buildings in it — the whole point is the composite.
    const out = fakeCanvas(800, 600);
    vi.spyOn(document, "createElement").mockReturnValueOnce(out as unknown as HTMLElement);

    const result = compositeCanvases([fakeCanvas(800, 600), fakeCanvas(800, 600)]);
    expect(result).toBe(out);
    expect(out.__ctx.drawImage).toHaveBeenCalledTimes(2);
  });

  it("skips canvases with no pixels rather than sizing the output to zero", () => {
    const out = fakeCanvas(800, 600);
    vi.spyOn(document, "createElement").mockReturnValueOnce(out as unknown as HTMLElement);
    compositeCanvases([fakeCanvas(800, 600), fakeCanvas(0, 0)]);
    expect(out.__ctx.drawImage).toHaveBeenCalledTimes(1);
  });

  it("returns null when there is nothing to capture", () => {
    expect(compositeCanvases([])).toBeNull();
    expect(compositeCanvases([fakeCanvas(0, 0)])).toBeNull();
  });

  it("draws the caption only when there is one", () => {
    const withCaption = fakeCanvas(800, 600);
    vi.spyOn(document, "createElement").mockReturnValueOnce(withCaption as unknown as HTMLElement);
    compositeCanvases([fakeCanvas(800, 600)], { caption: "Burruss Hall", subtitle: "scorched" });
    expect(withCaption.__ctx.fillText).toHaveBeenCalledWith("Burruss Hall", expect.any(Number), expect.any(Number));
    expect(withCaption.__ctx.fillText).toHaveBeenCalledWith("scorched", expect.any(Number), expect.any(Number));

    const plain = fakeCanvas(800, 600);
    vi.spyOn(document, "createElement").mockReturnValueOnce(plain as unknown as HTMLElement);
    compositeCanvases([fakeCanvas(800, 600)]);
    expect(plain.__ctx.fillText).not.toHaveBeenCalled();
  });
});

describe("postcard filenames", () => {
  it("slugs the building name", () => {
    expect(postcardFilename("Burruss Hall")).toMatch(/^burruss-hall-\d{4}-\d{2}-\d{2}/);
  });

  it("falls back rather than producing a file called '.png'", () => {
    expect(postcardFilename("!!!")).toMatch(/^scorched-nebraska-/);
    expect(postcardFilename(null)).toMatch(/^scorched-nebraska-/);
  });

  it("always ends in .png", () => {
    expect(postcardFilename("A Hall")).toMatch(/\.png$/);
  });
});
