/**
 * Save the current view as a PNG.
 *
 * Two canvases stack to make the picture — MapLibre's tiles underneath and
 * deck.gl's meshes over them (MapboxOverlay in overlaid mode keeps them
 * separate) — so a capture has to composite both. Grabbing only the map canvas
 * gives you a picture of Blacksburg with no buildings in it.
 *
 * Timing is the other half. A WebGL drawing buffer is cleared after a frame is
 * presented unless `preserveDrawingBuffer` is on, so the read has to happen
 * inside the frame. MapView calls `capture` from deck's `onAfterRender`.
 */

export interface PostcardOptions {
  /** Drawn bottom-left, e.g. "Burruss Hall — scorched". */
  caption?: string | null;
  /** Small print under the caption. */
  subtitle?: string | null;
}

const MARGIN = 28;

export function compositeCanvases(
  canvases: HTMLCanvasElement[],
  options: PostcardOptions = {},
): HTMLCanvasElement | null {
  const usable = canvases.filter((c) => c.width > 0 && c.height > 0);
  if (!usable.length) return null;

  const width = Math.max(...usable.map((c) => c.width));
  const height = Math.max(...usable.map((c) => c.height));
  const out = document.createElement("canvas");
  out.width = width;
  out.height = height;
  const ctx = out.getContext("2d");
  if (!ctx) return null;

  ctx.fillStyle = "#14120f";
  ctx.fillRect(0, 0, width, height);
  for (const canvas of usable) {
    // Canvases can differ in backing-store size (device pixel ratio, or deck
    // sizing itself off the container); draw each scaled to the output rather
    // than assuming they match.
    try {
      ctx.drawImage(canvas, 0, 0, width, height);
    } catch (e) {
      console.warn("[postcard] a layer could not be drawn", e);
    }
  }

  if (options.caption) drawCaption(ctx, width, height, options);
  return out;
}

function drawCaption(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  { caption, subtitle }: PostcardOptions,
) {
  const scale = Math.max(1, width / 1200);
  const titleSize = Math.round(26 * scale);
  const subSize = Math.round(14 * scale);
  const pad = Math.round(MARGIN * scale);

  // A gradient rather than a box: the caption has to stay readable over both a
  // bright satellite tile and a dark scorched one.
  const band = (subtitle ? titleSize + subSize + pad * 2.2 : titleSize + pad * 1.8);
  const gradient = ctx.createLinearGradient(0, height - band * 1.6, 0, height);
  gradient.addColorStop(0, "rgba(20,18,15,0)");
  gradient.addColorStop(1, "rgba(20,18,15,0.82)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, height - band * 1.6, width, band * 1.6);

  ctx.textBaseline = "alphabetic";
  if (subtitle) {
    ctx.font = `${subSize}px ui-monospace, SFMono-Regular, Menlo, monospace`;
    ctx.fillStyle = "rgba(201,138,60,0.92)";
    ctx.fillText(subtitle, pad, height - pad);
  }
  ctx.font = `700 ${titleSize}px "Chakra Petch", ui-sans-serif, system-ui, sans-serif`;
  ctx.fillStyle = "#e8e2d4";
  ctx.fillText(caption ?? "", pad, height - pad - (subtitle ? subSize + pad * 0.5 : 0));
}

/** Trigger a browser download for a canvas. Returns false if it could not. */
export function downloadCanvas(canvas: HTMLCanvasElement, filename: string): boolean {
  let url: string;
  try {
    url = canvas.toDataURL("image/png");
  } catch (e) {
    // Tainted canvas: a basemap tile served without CORS headers poisons the
    // whole composite. Worth saying plainly rather than failing silently.
    console.error("[postcard] canvas could not be read", e);
    return false;
  }
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  return true;
}

export function postcardFilename(caption?: string | null): string {
  const slug = (caption ?? "scorched-nebraska")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 48) || "scorched-nebraska";
  const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  return `${slug}-${stamp}.png`;
}
