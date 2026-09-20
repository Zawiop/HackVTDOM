import { lazy, Suspense, useEffect } from "react";

import Landing from "./Landing";
import { useRoute } from "./router";

/**
 * Chooses between the landing page and the map.
 *
 * The map is loaded lazily. deck.gl, MapLibre and the glTF loaders are the
 * heaviest thing in the bundle by a wide margin, and a visitor reading the
 * landing page has no use for any of it yet — splitting it out is what keeps
 * the first paint fast on a phone.
 */
const MapApp = lazy(() => import("../App"));

export default function Root() {
  const route = useRoute();

  // Coming back from a deep scroll on the landing page into the map, and then
  // back again, should not land you halfway down the page.
  useEffect(() => {
    if (route === "map") window.scrollTo(0, 0);
  }, [route]);

  if (route === "map") {
    return (
      <Suspense fallback={<MapLoading />}>
        <MapApp />
      </Suspense>
    );
  }

  return <Landing />;
}

function MapLoading() {
  return (
    <div className="se-map-loading" role="status" aria-live="polite">
      <span className="se-map-loading-mark" />
      <p>Loading the map…</p>
    </div>
  );
}
