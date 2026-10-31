import type { Host } from './types'

/** Backend timestamps are stored as UTC without an offset; treat them as UTC. */
export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`)
}

export function timeAgo(value: string | null | undefined): string {
  const d = parseDate(value)
  if (!d) return 'never'
  const s = Math.round((Date.now() - d.getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} d ago`
}

export function duration(start: string | null, end: string | null): string {
  const a = parseDate(start)
  if (!a) return '–'
  const b = parseDate(end) ?? new Date()
  const s = Math.max(0, Math.round((b.getTime() - a.getTime()) / 1000))
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`
}

export type HostHealth = 'ok' | 'error' | 'unknown' | 'disabled'

export function hostHealth(h: Host): HostHealth {
  if (!h.enabled) return 'disabled'
  if (h.last_error) return 'error'
  if (h.last_seen) return 'ok'
  return 'unknown'
}

export function osLabel(h: Host): string {
  if (h.os_name && h.os_version) return `${h.os_name} ${h.os_version}`
  return h.os_name ?? h.os_family ?? 'unknown OS'
}

/** Accepts either a JSON object or `key=value` lines; values may be JSON lists/objects (`k=["a","b"]`). */
export function parseExtraVars(text: string): Record<string, unknown> {
  const t = text.trim()
  if (!t) return {}
  if (t.startsWith('{')) {
    const parsed = JSON.parse(t)
    if (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null) {
      throw new Error('Extra vars JSON must be an object')
    }
    return parsed
  }
  const out: Record<string, unknown> = {}
  for (const raw of t.split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const i = line.indexOf('=')
    if (i < 1) throw new Error(`Invalid line "${line}" (expected key=value)`)
    const key = line.slice(0, i).trim()
    const value = line.slice(i + 1).trim()
    if (/^(true|false)$/i.test(value)) out[key] = value.toLowerCase() === 'true'
    else if (/^-?\d+(\.\d+)?$/.test(value)) out[key] = Number(value)
    else if (value === 'null') out[key] = null
    else if (/^[[{]/.test(value)) {
      try {
        out[key] = JSON.parse(value)
      } catch {
        throw new Error(`Invalid JSON value for "${key}"`)
      }
    } else out[key] = value
  }
  return out
}

export function formatExtraVars(vars: Record<string, unknown>): string {
  return Object.entries(vars)
    .map(([k, v]) => `${k}=${v !== null && typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join('\n')
}

/** Keeps only values that differ from the playbook defaults (extra vars would override host vars otherwise). */
export function changedVars(vars: Record<string, unknown>, defaults: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(vars).filter(([k, v]) => !(k in defaults) || JSON.stringify(v) !== JSON.stringify(defaults[k])),
  )
}

export type HostOutcome = 'ok' | 'changed' | 'failed' | 'unreachable' | 'pending'

export function hostOutcome(stats: Record<string, Record<string, number>>, host: string): HostOutcome {
  if (!stats || !Object.keys(stats).length) return 'pending'
  if (stats.dark?.[host]) return 'unreachable'
  if (stats.failures?.[host]) return 'failed'
  if (stats.changed?.[host]) return 'changed'
  if (stats.processed?.[host] !== undefined || stats.ok?.[host] !== undefined) return 'ok'
  return 'pending'
}

/** "CT 101" for containers, "VM 150" for QEMU VMs (hosts imported before VM support count as containers). */
export function guestLabel(type: string | null | undefined, vmid: number | null): string {
  return `${type === 'qemu' ? 'VM' : 'CT'} ${vmid}`
}
