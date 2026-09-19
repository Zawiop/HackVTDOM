import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from '../lib/api'

afterEach(() => vi.unstubAllGlobals())

function stubFetch(status, body) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: status >= 200 && status < 300,
      status,
      text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
    }))
  )
}

describe('api error handling', () => {
  it('throws on a failed write instead of returning a falsy value', async () => {
    // Step 11: a failed save must never look like a success in the UI.
    stubFetch(502, { detail: 'persistence.save_generation: connection refused' })
    await expect(api.saveGeneration({ address: 'x' })).rejects.toBeInstanceOf(ApiError)
  })

  it('surfaces the backend detail message', async () => {
    stubFetch(502, { detail: 'persistence.save_generation: boom' })
    await expect(api.saveGeneration({})).rejects.toThrow(/boom/)
  })

  it('turns a network failure into an ApiError rather than an unhandled reject', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline') }))
    await expect(api.listGenerations()).rejects.toThrow(/network error: offline/)
  })

  it('returns parsed rows on success', async () => {
    stubFetch(200, [{ id: 'a' }])
    await expect(api.listGenerations()).resolves.toEqual([{ id: 'a' }])
  })

  it('url-encodes addresses containing commas and spaces', async () => {
    stubFetch(200, [])
    await api.history('Burruss Hall, Blacksburg, VA')
    expect(fetch).toHaveBeenCalledWith(
      '/api/history?address=Burruss%20Hall%2C%20Blacksburg%2C%20VA',
      expect.anything()
    )
  })
})
