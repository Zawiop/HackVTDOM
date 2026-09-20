import type { StyleSpecification } from "maplibre-gl";

/**
 * Base map sources.
 *
 * OSM raster is the default and is free + keyless — step 12 is explicit that no
 * MapTiler key should be introduced. Esri World Imagery is a hidden second
 * layer for the panel's satellite toggle, which is what lets a judge check a
 * mesh against the real roof it is meant to sit on. Also keyless. Both carry
 * their required attribution.
 */
export const OSM_LAYER_ID = "osm";
export const SATELLITE_LAYER_ID = "satellite";

export const BASE_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution: "© OpenStreetMap contributors",
    },
    satellite: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      maxzoom: 19,
      attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
    },
  },
  layers: [
    {
      id: OSM_LAYER_ID,
      type: "raster",
      source: "osm",
      minzoom: 0,
      maxzoom: 22,
      // Graded down deliberately. Stock OSM tiles are bright and cheerful, which
      // fights a post-apocalyptic world and washes out the World State terrain
      // drawn on top — a teal flood or an ochre dust field barely registers
      // against full-saturation parkland green. Pulling saturation and highlights
      // back turns the basemap into a substrate the states can read against.
      paint: {
        "raster-saturation": -0.42,
        "raster-brightness-max": 0.84,
        "raster-contrast": 0.1,
      },
    },
    {
      id: SATELLITE_LAYER_ID,
      type: "raster",
      source: "satellite",
      minzoom: 0,
      maxzoom: 22,
      layout: { visibility: "none" },
      paint: { "raster-saturation": -0.2, "raster-contrast": 0.06 },
    },
  ],
};

/** Virginia Tech drillfield — the demo's home view. */
export const INITIAL_VIEW = {
  longitude: -80.4229,
  latitude: 37.2287,
  zoom: 17.2,
  pitch: 55,
  bearing: -20,
};
