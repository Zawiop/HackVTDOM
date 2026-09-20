import { useCallback, useEffect, useState } from "react";

/**
 * A two-route router, hand-rolled.
 *
 * The app already hand-rolls its URL state (`map/useUrlState.ts`), and pulling
 * in a routing library to choose between exactly two screens would be more
 * surface than the problem deserves — and more risk of fighting that module
 * over who owns `history`.
 *
 * Division of labour: this owns `location.pathname` only, `useUrlState` owns
 * the query string only. They never write the same part of the URL, so the
 * map's camera state survives a route change and vice versa.
 */

export type Route = "home" | "map";

/** Everything not recognised falls back to the landing page. */
export function routeFromPath(pathname: string): Route {
  // Tolerate a trailing slash and a sub-path deploy (e.g. /scorched-earth/map).
  return /\/map\/?$/.test(pathname) ? "map" : "home";
}

export function pathForRoute(route: Route): string {
  return route === "map" ? "/map" : "/";
}

/**
 * Navigate without a reload, preserving the query string when it still applies.
 *
 * The map's camera lives in the query string, so going home and coming back
 * should return you to the same view rather than resetting to Blacksburg.
 */
export function navigate(route: Route, options: { keepQuery?: boolean } = {}): void {
  const keep = options.keepQuery ?? true;
  const url = pathForRoute(route) + (keep ? window.location.search : "");
  if (url === window.location.pathname + window.location.search) return;

  window.history.pushState({ route }, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/**
 * Mirror the route onto <html> so CSS can switch page-level layout.
 *
 * The map is a fixed-height shell that must not scroll and the landing page is
 * a document that must, and that difference is set on `html`/`body`. Applied
 * synchronously rather than from an effect: an effect runs after the first
 * paint, which is long enough to see the page jump.
 */
export function applyRouteToDocument(route: Route): void {
  document.documentElement.dataset.route = route;
}

/** The current route, kept in sync with Back/Forward. */
export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => {
    const initial = routeFromPath(window.location.pathname);
    applyRouteToDocument(initial);
    return initial;
  });

  useEffect(() => {
    const sync = () => {
      const next = routeFromPath(window.location.pathname);
      applyRouteToDocument(next);
      setRoute(next);
    };
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  return route;
}

/**
 * Smooth-scroll to a section on the landing page.
 *
 * Honours `prefers-reduced-motion`: a long smooth scroll is exactly the kind of
 * motion that triggers vestibular symptoms, and the anchor still has to work.
 */
export function useScrollTo(): (id: string) => void {
  return useCallback((id: string) => {
    const target = document.getElementById(id);
    if (!target) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
  }, []);
}
