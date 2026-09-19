import { describe, expect, it } from 'vitest'
import { haversineMeters, metersPerDegree, offsetMeters } from '../lib/geo'

describe('haversineMeters', () => {
  it('is zero for the same point', () => {
    expect(haversineMeters(37.2287, -80.4229, 37.2287, -80.4229)).toBeCloseTo(0, 6)
  })

  it('matches the backend across the VT drillfield', () => {
    const d = haversineMeters(37.2284, -80.4234, 37.2296, -80.4139)
    expect(d).toBeGreaterThan(800)
    expect(d).toBeLessThan(900)
  })
})

describe('offsetMeters', () => {
  it('moves the requested distance north', () => {
    const [lat, lng] = offsetMeters(37.2287, -80.4229, 10, 0)
    expect(haversineMeters(37.2287, -80.4229, lat, lng)).toBeCloseTo(10, 1)
  })

  it('nudges 0.5m accurately — the step 09 arrow-key step', () => {
    const [lat, lng] = offsetMeters(37.2287, -80.4229, 0, 0.5)
    expect(haversineMeters(37.2287, -80.4229, lat, lng)).toBeCloseTo(0.5, 2)
  })
})

describe('metersPerDegree', () => {
  it('shrinks longitude away from the equator', () => {
    expect(metersPerDegree(0)[1]).toBeGreaterThan(metersPerDegree(37.2287)[1])
  })
})
