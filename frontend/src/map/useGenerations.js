import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'

/**
 * Loads every persisted generation for the map.
 *
 * A load failure is surfaced as `error`, never swallowed into an empty map —
 * an empty map and a broken backend must not look identical to the user.
 */
export function useGenerations() {
  const [rows, setRows] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.listGenerations()
      setRows(Array.isArray(data) ? data : [])
      setError(null)
    } catch (e) {
      console.error('[useGenerations] load failed', e)
      setError(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  /** Replace one row in place after a correction, without a full refetch. */
  const replaceRow = useCallback((updated) => {
    setRows((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
  }, [])

  return { rows, error, loading, refresh, replaceRow }
}
