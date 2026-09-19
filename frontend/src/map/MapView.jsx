import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import { MapboxOverlay } from '@deck.gl/mapbox'
import 'maplibre-gl/dist/maplibre-gl.css'

import { BASE_STYLE, INITIAL_VIEW, OSM_LAYER_ID, SATELLITE_LAYER_ID } from './basemap'
import {
  buildConfidenceRingLayer,
  buildLabelLayer,
  buildPendingLayer,
  buildRadiusLayer,
  buildScenegraphLayers,
} from './layers'

/**
 * MapLibre base map with a deck.gl overlay on top.
 *
 * MapboxOverlay (overlaid, not interleaved) is the supported MapLibre interop
 * path and avoids depth-buffer fighting between raster tiles and 3D meshes.
 */
export default function MapView({
  rows,
  selectedId,
  onSelect,
  roll,
  overrides,
  propagate,
  showLabels = true,
  satellite = false,
  onMapReady,
}) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const overlayRef = useRef(null)

  // Create the map once.
  useEffect(() => {
    if (mapRef.current || !containerRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASE_STYLE,
      center: [INITIAL_VIEW.longitude, INITIAL_VIEW.latitude],
      zoom: INITIAL_VIEW.zoom,
      pitch: INITIAL_VIEW.pitch,
      bearing: INITIAL_VIEW.bearing,
      attributionControl: { compact: true },
    })
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right')
    const overlay = new MapboxOverlay({ interleaved: false, layers: [] })
    map.addControl(overlay)
    mapRef.current = map
    overlayRef.current = overlay
    map.on('load', () => onMapReady?.(map))
    return () => {
      overlay.finalize()
      map.remove()
      mapRef.current = null
      overlayRef.current = null
    }
  }, [])

  // Push layers whenever the data or the live correction overrides change.
  useEffect(() => {
    const overlay = overlayRef.current
    if (!overlay) return
    const selected = rows.find((r) => r.id === selectedId) || null
    const layers = [
      buildRadiusLayer(
        propagate?.source ?? selected,
        propagate?.active ? propagate.radiusMeters : null
      ),
      ...buildScenegraphLayers(rows, { onClick: onSelect, roll, selectedId, overrides }),
      buildConfidenceRingLayer(rows, { onClick: onSelect, selectedId, overrides }),
      buildPendingLayer(propagate?.pending),
      showLabels ? buildLabelLayer(rows) : null,
    ].filter(Boolean)
    overlay.setProps({ layers })
  }, [rows, selectedId, onSelect, roll, overrides, propagate, showLabels])

  // Satellite toggle: flip layer visibility rather than swapping the whole
  // style, so the deck.gl overlay and its loaded meshes survive the switch.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => {
      if (!map.getLayer(OSM_LAYER_ID) || !map.getLayer(SATELLITE_LAYER_ID)) return
      map.setLayoutProperty(SATELLITE_LAYER_ID, 'visibility', satellite ? 'visible' : 'none')
      map.setLayoutProperty(OSM_LAYER_ID, 'visibility', satellite ? 'none' : 'visible')
    }
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [satellite])

  // Fly to a building when it is selected from outside the map.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !selectedId) return
    const row = rows.find((r) => r.id === selectedId)
    if (!row) return
    map.easeTo({ center: [Number(row.lng), Number(row.lat)], duration: 700 })
  }, [selectedId, rows])

  return <div className="map-root" ref={containerRef} />
}
