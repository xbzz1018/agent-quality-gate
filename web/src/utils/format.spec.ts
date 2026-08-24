import { describe, expect, it } from 'vitest'

import { formatCost, formatNumber, formatPercent, pretty } from './format'

describe('measurement formatting', () => {
  it('preserves missing observations as UNKNOWN rather than zero', () => {
    expect(formatNumber(null)).toBe('UNKNOWN')
    expect(formatPercent(undefined)).toBe('UNKNOWN')
    expect(formatCost(null)).toBe('UNKNOWN')
  })

  it('formats measured zero as a real value', () => {
    expect(formatNumber(0)).toBe('0')
    expect(formatPercent(0)).toBe('0.0%')
    expect(formatCost('0')).toBe('USD 0.000000')
  })

  it('renders structured observations as readable JSON', () => {
    expect(pretty({ passed: true })).toContain('"passed": true')
  })
})
