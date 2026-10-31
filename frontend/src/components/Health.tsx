import type { Host, StatusCheck } from '../types'
import { parseDate, timeAgo } from '../util'

const ORDER = ['docker', 'disk', 'updates', 'units']
const LABEL: Record<string, string> = { docker: 'Docker', disk: 'Disk', updates: 'Updates', units: 'systemd' }
const STALE_MS = 26 * 3600 * 1000

function sortedChecks(host: Host): [string, StatusCheck][] {
  const checks = Object.entries(host.health?.checks ?? {})
  return checks.sort(([a], [b]) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99))
}

function isStale(host: Host): boolean {
  const d = parseDate(host.health_checked_at)
  return !d || Date.now() - d.getTime() > STALE_MS
}

/** Small status labels per check (Hosts overview). */
export function HealthLabels({ host }: { host: Host }) {
  if (!host.health) return null
  return (
    <div className={`health-labels ${isStale(host) ? 'stale' : ''}`} title={`checked ${timeAgo(host.health_checked_at)}`}>
      {sortedChecks(host).map(([key, c]) => (
        <span key={key} className={`hl hl-${c.level}`}>
          {LABEL[key] ?? key} {c.summary}
        </span>
      ))}
    </div>
  )
}

/** One compact label with the overall status (host pickers). */
export function HealthBadge({ host }: { host: Host }) {
  if (!host.health) return null
  const issues = sortedChecks(host).filter(([, c]) => c.level !== 'ok')
  const text = host.health.level === 'ok' ? 'healthy' : issues.map(([k]) => LABEL[k] ?? k).join(', ')
  return <span className={`hl hl-${host.health.level} ${isStale(host) ? 'stale' : ''}`}>{text}</span>
}

/** Detailed list for the host sheet. */
export function HealthDetails({ host }: { host: Host }) {
  if (!host.health) return null
  return (
    <div className="health-details">
      <div className="row">
        <b className="grow">Health</b>
        <span className="muted small">checked {timeAgo(host.health_checked_at)}</span>
      </div>
      {sortedChecks(host).map(([key, c]) => (
        <div key={key} className="health-detail">
          <span className={`hl hl-${c.level}`}>
            {LABEL[key] ?? key} {c.summary}
          </span>
          {c.details.length > 0 && (
            <ul className="small muted">
              {c.details.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  )
}
