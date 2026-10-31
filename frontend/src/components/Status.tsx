import type { RunStatus } from '../types'
import type { HostHealth, HostOutcome } from '../util'

const LABELS: Record<string, string> = {
  pending: 'Pending',
  running: 'Running',
  successful: 'Success',
  failed: 'Failed',
  canceled: 'Canceled',
  error: 'Error',
  timeout: 'Timeout',
  ok: 'OK',
  changed: 'Changed',
  unreachable: 'Unreachable',
}

export function StatusBadge({ status }: { status: RunStatus | HostOutcome }) {
  return <span className={`badge badge-${status}`}>{LABELS[status] ?? status}</span>
}

export function HealthDot({ health, title }: { health: HostHealth; title?: string }) {
  return <span className={`dot dot-${health}`} title={title ?? health} aria-label={health} />
}
