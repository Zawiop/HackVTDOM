import { useCallback, useMemo, useRef, useState } from 'react'
import MapView from './map/MapView'
import { useGenerations } from './map/useGenerations'
import { UP_AXIS_ROLL } from './map/layers'
import BuildingPanel from './panel/BuildingPanel'
import PropagatePanel from './propagate/PropagatePanel'
import { offsetMeters } from './lib/geo'

/**
 * Composition root for the persistence + map half of the app (steps 09-12).
 *
 * Steps 01-05 (address entry, photo upload, World State selector) are owned by
 * other agents; their panels mount alongside this shell rather than replacing
 * it, and they write through the same POST /api/generations contract.
 */
export default function App() {
  const { rows, error, loading, refresh, replaceRow } = useGenerations()
  const [selectedId, setSelectedId] = useState(null)
  const [overrides, setOverrides] = useState(null)
  const [propagate, setPropagate] = useState(null)
  const [satellite, setSatellite] = useState(false)
  const [showLabels, setShowLabels] = useState(true)
  const mapRef = useRef(null)

  const selected = useMemo(
    () => rows.find((r) => r.id === selectedId) ?? null,
    [rows, selectedId]
  )

  const onSelect = useCallback((row) => {
    setSelectedId(row?.id ?? null)
    setOverrides(null)
  }, [])

  const closePanel = useCallback(() => {
    setSelectedId(null)
    setOverrides(null)
  }, [])

  // A saved correction replaces the row in place — no full refetch needed.
  const onSaved = useCallback(
    (updated) => {
      replaceRow(updated)
      setOverrides(null)
    },
    [replaceRow]
  )

  /** The pitch's strongest beat: zoom out so the whole propagated area is visible. */
  const revealArea = useCallback((source, radiusMeters) => {
    const map = mapRef.current
    if (!map || !source) return
    const pad = radiusMeters * 1.4
    const [nLat, eLng] = offsetMeters(source.lat, source.lng, pad, pad)
    const [sLat, wLng] = offsetMeters(source.lat, source.lng, -pad, -pad)
    map.fitBounds(
      [
        [wLng, sLat],
        [eLng, nLat],
      ],
      { padding: 80, pitch: 50, duration: 1400 }
    )
  }, [])

  const counts = useMemo(() => {
    const low = rows.filter((r) => r.confidence_state === 'auto-low').length
    const fixed = rows.filter((r) => r.confidence_state === 'manually-verified').length
    return { total: rows.length, low, fixed }
  }, [rows])

  return (
    <div className="app-shell">
      {error && (
        <div className="error-banner">
          backend unreachable — {error.message}
          <button style={{ marginLeft: 12 }} onClick={refresh}>retry</button>
        </div>
      )}

      <MapView
        rows={rows}
        selectedId={selectedId}
        onSelect={onSelect}
        roll={UP_AXIS_ROLL}
        overrides={overrides}
        propagate={propagate}
        satellite={satellite}
        showLabels={showLabels}
        onMapReady={(m) => (mapRef.current = m)}
      />

      <div className="panel panel-left">
        <h2>SCORCHED NEBRASKA</h2>
        <div className="mono-sm">
          {loading ? 'loading…' : `${counts.total} generations · ${counts.low} flagged · ${counts.fixed} verified`}
        </div>

        <h3>view</h3>
        <div className="btn-grid">
          <button
            className={satellite ? 'active' : ''}
            onClick={() => setSatellite((v) => !v)}
          >
            satellite
          </button>
          <button
            className={showLabels ? 'active' : ''}
            onClick={() => setShowLabels((v) => !v)}
          >
            labels
          </button>
        </div>

        {selected ? (
          <PropagatePanel
            source={selected}
            onResult={(state) => {
              setPropagate(state)
              revealArea(state.source, state.radiusMeters)
            }}
            onClear={() => setPropagate(null)}
          />
        ) : (
          <>
            <h3>world propagate</h3>
            <p className="hint">Select a building to spread its World State.</p>
          </>
        )}

        <h3>legend</h3>
        <p className="hint">
          <span style={{ color: 'var(--sn-warn)' }}>amber ring</span> = flagged by the
          placement checker, shown rather than hidden. Click it to open the correction
          controls.
        </p>
      </div>

      {selected && (
        <BuildingPanel
          row={selected}
          onClose={closePanel}
          onPreview={setOverrides}
          onSaved={onSaved}
          onPickHistory={(r) => onSelect(r)}
          satellite={satellite}
          onToggleSatellite={() => setSatellite((v) => !v)}
        />
      )}
    </div>
  )
}
