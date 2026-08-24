export function formatDate(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString('zh-CN') : 'UNKNOWN'
}

export function formatPercent(value: number | null | undefined): string {
  return value == null ? 'UNKNOWN' : `${(value * 100).toFixed(1)}%`
}

export function formatNumber(value: number | string | null | undefined, suffix = ''): string {
  if (value == null) return 'UNKNOWN'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `${parsed.toLocaleString('zh-CN')}${suffix}` : 'UNKNOWN'
}

export function formatCost(value: string | null | undefined, currency = 'USD'): string {
  if (value == null) return 'UNKNOWN'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `${currency} ${parsed.toFixed(6)}` : 'UNKNOWN'
}

export function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2)
}
