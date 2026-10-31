import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { HistoryNav } from '../components/HistoryNav'
import { StatusBadge } from '../components/Status'
import { toast } from '../components/Toast'
import type { Run } from '../types'
import { duration, hostOutcome, timeAgo } from '../util'

export function HistoryPage() {
  const [runs, setRuns] = useState<Run[] | null>(null)

  useEffect(() => {
    let stop = false
    let timer: ReturnType<typeof setTimeout>
    const load = async () => {
      try {
        const data = await api.runs()
        if (stop) return
        setRuns(data)
        const anyActive = data.some((r) => r.status === 'running' || r.status === 'pending')
        timer = setTimeout(load, anyActive ? 3000 : 15000)
      } catch (e) {
        toast.error(e)
      }
    }
    load()
    return () => {
      stop = true
      clearTimeout(timer)
    }
  }, [])

  return (
    <div className="page">
      <HistoryNav />
      {!runs && <div className="empty">Loading…</div>}
      {runs && !runs.length && <div className="empty">No runs yet.</div>}
      <ul className="list">
        {(runs ?? []).map((r) => {
          const bad = r.host_names.filter((n) => ['failed', 'unreachable'].includes(hostOutcome(r.stats, n))).length
          return (
            <li key={r.id}>
              <Link to={`/runs/${r.id}`} className="card card-link">
                <div className="row">
                  <div className="card-title grow ellipsis">
                    #{r.id} {r.playbook}
                  </div>
                  <StatusBadge status={r.status} />
                </div>
                <div className="muted small">
                  {r.host_names.length} host{r.host_names.length === 1 ? '' : 's'}
                  {bad > 0 && <span className="text-error"> · {bad} failed</span>}
                  {r.check_mode && ' · dry run'} · {timeAgo(r.created_at)} · {duration(r.started_at, r.finished_at)}
                </div>
                <div className="muted small ellipsis">{r.host_names.join(', ')}</div>
                {r.triggered_by?.startsWith('schedule:') && <div className="small muted">⏱ {r.triggered_by.slice(9).trim()}</div>}
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
