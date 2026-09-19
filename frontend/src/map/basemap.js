/**
 * Base map sources.
 *
 * OSM raster is the default and is free + keyless — step 12 is explicit that no
 * MapTiler key should be introduced. Esri World Imagery is added as a hidden
 * second layer purely for the panel's satellite toggle, which is what lets a
 * judge check a mesh against the real roof it is supposed to be sitting on.
 * It is also keyless. Both carry their required attribution.
 */
export const OSM_LAYER_ID = 'osm'
export const SATELLITE_LAYER_ID = 'satellite'

export const BASE_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© OpenStreetMap contributors',
    },
    satellite: {
      type: 'raster',
      tiles: [
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      ],
      tileSize: 256,
      maxzoom: 19,
      attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
    },
  },
  layers: [
    { id: OSM_LAYER_ID, type: 'raster', source: 'osm', minzoom: 0, maxzoom: 22 },
    {
      id: SATELLITE_LAYER_ID,
      type: 'raster',
      source: 'satellite',
      minzoom: 0,
      maxzoom: 22,
      layout: { visibility: 'none' },
    },
  ],
}

/** Virginia Tech drillfield — the demo's home view. */
export const INITIAL_VIEW = {
  longitude: -80.4229,
  latitude: 37.2287,
  zoom: 17.2,
  pitch: 55,
  bearing: -20,
}
