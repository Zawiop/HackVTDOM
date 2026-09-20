import { useEffect, useRef, useState } from "react";

/**
 * Reveal an element the first time it scrolls into view.
 *
 * Deliberately not IntersectionObserver. The failure mode of a scroll-reveal
 * that never fires is that every section below the fold stays at `opacity: 0`
 * — an entirely blank page, from a purely decorative feature. That is a bad
 * trade for a landing page, and it is not hypothetical: the observer silently
 * never fires in some embedded and headless viewers.
 *
 * A shared rAF-coalesced scroll listener measuring rectangles cannot fail that
 * way, is exact about what "in view" means, and costs one `getBoundingClientRect`
 * per registered element per animation frame — about nine of them here.
 */

type Callback = () => void;

/** How far into the viewport an element must come before it counts as seen. */
const ENTER_RATIO = 0.08;

const watchers = new Map<Element, Callback>();
let pending = 0;
let listening = false;

function inView(el: Element): boolean {
  const rect = el.getBoundingClientRect();
  const viewport = window.innerHeight || document.documentElement.clientHeight;
  // Zero-sized elements (not yet laid out) are not "in view" in any useful sense.
  if (rect.height === 0 && rect.width === 0) return false;

  const margin = viewport * ENTER_RATIO;
  return rect.top < viewport - margin && rect.bottom > 0;
}

function check(): void {
  pending = 0;
  for (const [el, fire] of watchers) {
    if (inView(el)) {
      watchers.delete(el);
      fire();
    }
  }
  if (watchers.size === 0) stop();
}

/**
 * Throttled with a timer rather than requestAnimationFrame.
 *
 * rAF does not run while a document is not being painted — a background tab, a
 * hidden pane, some embedded viewers — and a reveal scheduled on a frame that
 * never arrives is a section that never appears. An 80 ms timer is well inside
 * the threshold where a scroll-triggered fade reads as immediate, and it runs
 * regardless of paint.
 */
function schedule(): void {
  if (pending) return;
  pending = window.setTimeout(check, 80);
}

function start(): void {
  if (listening) return;
  listening = true;
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule, { passive: true });
}

function stop(): void {
  if (!listening) return;
  listening = false;
  window.removeEventListener("scroll", schedule);
  window.removeEventListener("resize", schedule);
  if (pending) {
    clearTimeout(pending);
    pending = 0;
  }
}

function watch(el: Element, fire: Callback): () => void {
  watchers.set(el, fire);
  start();
  // Synchronously, not scheduled: anything already on screen at mount must not
  // wait on a timer, and the very first paint should have it already visible.
  check();
  return () => {
    watchers.delete(el);
    if (watchers.size === 0) stop();
  };
}

export function useReveal<T extends HTMLElement = HTMLDivElement>() {
  const ref = useRef<T | null>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || shown) return;

    // Anyone who has asked for less motion gets the content immediately.
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setShown(true);
      return;
    }

    return watch(node, () => setShown(true));
  }, [shown]);

  return { ref, shown } as const;
}

/** True once the page has scrolled past `after` pixels. Drives the navbar. */
export function useScrolled(after = 24): boolean {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    let pending = 0;
    const onScroll = () => {
      if (pending) return;
      pending = requestAnimationFrame(() => {
        setScrolled(window.scrollY > after);
        pending = 0;
      });
    };

    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (pending) cancelAnimationFrame(pending);
    };
  }, [after]);

  return scrolled;
}
