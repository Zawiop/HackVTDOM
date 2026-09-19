import { useState } from 'react'
import { api } from '../lib/api'

/**
 * Step 10: spread one building's World State across its neighbours.
 *
 * This reveals rows that were pre-baked before judging — it never kicks off
 * generation live, which is exactly what 10-propagate.md warns against. If a
 * neighbour inside the radius has no pre-baked row, it is reported as pending
 * rather than quietly omitted.
 */
const RADII = [50, 100, 250]

export default function PropagatePanel({ source, onResult, onClear }) {
  const [radius, setRadius] = useState(100)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function run(r) {
    setRadius(r)
    setBusy(true)
    setError(null)
    try {
      const res = await api.propagate(source.id, r)
      setResult(res)
      onResult?.({
        active: true,
        source,
        radiusMeters: r,
        revealed: res.revealed,
        pending: res.pending,
      })
    } catch (e) {
      console.error('[propagate] failed', e)
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  function clear() {
    setResult(null)
    setError(null)
    onClear?.()
  }

  return (
    <>
      <h3>world propagate</h3>
      <div className="mono-sm" style={{ marginBottom: 6 }}>
        spread “{source.world_state ?? '—'}” from{' '}
        {(source.address ?? '').split(',')[0]}
      </div>
      <div className="btn-grid" style={{ gridTemplateColumns: '1fr 1fr 1fr' }}>
        {RADII.map((r) => (
          <button
            key={r}
            className={result && radius === r ? 'active' : ''}
            disabled={busy}
            onClick={() => run(r)}
          >
            {r}m
          </button>
        ))}
      </div>

      {error && (
        <div className="mono-sm" style={{ color: 'var(--sn-danger)', marginTop: 8 }}>
          propagate failed — {error.message}
        </div>
      )}

      {result && (
        <div style={{ marginTop: 8 }}>
          <div className="mono-sm">
            {result.counts.revealed} revealed
            {result.counts.pending > 0 && (
              <> · {result.counts.pending} not pre-baked</>
            )}
          </div>
          <ul className="timeline" style={{ marginTop: 4 }}>
            {result.revealed.map((g) => (
              <li key={g.id} style={{ cursor: 'default' }}>
                <span>{(g.address ?? '').split(',')[0]}</span>
                <span className={`badge badge--${g.confidence_state}`}>
                  {g.confidence_state}
                </span>
              </li>
            ))}
          </ul>
          <button style={{ marginTop: 6 }} onClick={clear}>clear</button>
        </div>
      )}
    </>
  )
}
