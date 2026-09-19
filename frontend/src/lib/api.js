/**
 * Backend client.
 *
 * Every call throws on a non-2xx response. Step 11 is explicit that a failed
 * write must never look like a success in the UI, so nothing here returns a
 * quiet null that a caller could render straight past.
 */

export class ApiError extends Error {
  constructor(status, detail, path) {
    super(`${path} failed (HTTP ${status}): ${detail}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.path = path
  }
}

async function request(path, options = {}) {
  let res
  try {
    res = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch (e) {
    throw new ApiError(0, `network error: ${e.message}`, path)
  }
  const text = await res.text()
  let body = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = text
    }
  }
  if (!res.ok) {
    const detail =
      (body && typeof body === 'object' && (body.detail ?? body.message)) ||
      (typeof body === 'string' ? body : 'unknown error')
    const message = typeof detail === 'string' ? detail : JSON.stringify(detail)
    console.error(`[api] ${path} -> ${res.status}: ${message}`)
    throw new ApiError(res.status, message, path)
  }
  return body
}

export const api = {
  health: () => request('/api/health'),

  /** Every persisted row — the data behind the step 12 ScenegraphLayer. */
  listGenerations: () => request('/api/generations'),

  getGeneration: (id) => request(`/api/generations/${id}`),

  /** One address's sequence, oldest first: Reality -> Flooded -> Reclaimed. */
  history: (address) =>
    request(`/api/history?address=${encodeURIComponent(address)}`),

  saveGeneration: (payload) =>
    request('/api/generations', { method: 'POST', body: JSON.stringify(payload) }),

  /** Step 09: persist a corrected transform; backend flips to manually-verified. */
  correct: (id, correction) =>
    request(`/api/generations/${id}/correction`, {
      method: 'PATCH',
      body: JSON.stringify(correction),
    }),

  /** Step 10: reveal pre-baked neighbours within a radius. */
  propagate: (sourceGenerationId, radiusMeters, neighbors = []) =>
    request('/api/propagate', {
      method: 'POST',
      body: JSON.stringify({
        source_generation_id: sourceGenerationId,
        radius_meters: radiusMeters,
        neighbors,
      }),
    }),
}
