import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { HistoryNav } from '../components/HistoryNav'
import { PlusIcon } from '../components/Icons'
import { CRON_PRESETS, ScheduleForm } from '../components/ScheduleForm'
import { StatusBadge } from '../components/Status'
import { toast } from '../components/Toast'
import type { Host, Playbook, Schedule, ScheduleInput } from '../types'
import { parseDate, timeAgo } from '../util'

function CronLabel({ cron }: { cron: string }) {
  const preset = CRON_PRESETS.find((p) => p.cron === cron)
  return preset ? <span>{preset.label}</span> : <span className="mono">{cron}</span>
}

function describeTarget(s: Schedule, hosts: Host[]): string {
  if (s.target_host_ids.length) {
    const names = hosts.filter((h) => s.target_host_ids.includes(h.id)).map((h) => h.name)
    return names.length <= 3 ? names.join(', ') : `${names.length} hosts`
  }
  if (s.target_tags.length) return `tags: ${s.target_tags.join(', ')}`
  return 'all hosts'
}

function formatWhen(value: string | null): string {
  const d = parseDate(value)
  if (!d) return '–'
  return d.toLocaleString([], { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export function SchedulesPage() {
  const navigate = useNavigate()
  const [schedules, setSchedules] = useState<Schedule[] | null>(null)
  const [playbooks, setPlaybooks] = useState<Playbook[]>([])
  const [hosts, setHosts] = useState<Host[]>([])
  const [editing, setEditing] = useState<Schedule | null>(null)
  const [formOpen, setFormOpen] = useState(false)

  const load = useCallback(() => api.schedules().then(setSchedules).catch(toast.error), [])

  useEffect(() => {
    load()
    Promise.all([api.playbooks(), api.hosts()])
      .then(([p, h]) => {
        setPlaybooks(p)
        setHosts(h)
      })
      .catch(toast.error)
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [load])

  function open(s: Schedule | null) {
    setEditing(s)
    setFormOpen(true)
  }

  async function save(body: ScheduleInput) {
    if (editing) await api.updateSchedule(editing.id, body)
    else await api.createSchedule(body)
    toast.info('Schedule saved')
    setFormOpen(false)
    load()
  }

  async function remove() {
    if (!editing) return
    await api.deleteSchedule(editing.id)
    setFormOpen(false)
    load()
  }

  async function toggleEnabled(s: Schedule) {
    try {
      await api.updateSchedule(s.id, { enabled: !s.enabled })
      load()
    } catch (e) {
      toast.error(e)
    }
  }

  async function runNow(s: Schedule) {
    try {
      const r = await api.runSchedule(s.id)
      navigate(`/runs/${r.run_id}`)
    } catch (e) {
      toast.error(e)
    }
  }

  const title = (path: string) => playbooks.find((p) => p.path === path)?.title ?? path

  return (
    <div className="page">
      <HistoryNav />
      {!schedules ? (
        <div className="empty">Loading…</div>
      ) : schedules.length === 0 ? (
        <div className="empty">
          No schedules yet. Tap + to run a playbook periodically, e.g. the health check every 6 hours.
        </div>
      ) : (
        <ul className="list">
          {schedules.map((s) => (
            <li key={s.id} className="card">
              <button className={`card-main ${s.enabled ? '' : 'paused'}`} onClick={() => open(s)}>
                <div className="row">
                  <div className="card-title grow ellipsis">{s.name}</div>
                  <span className={`badge ${s.enabled ? 'badge-ok' : ''}`}>{s.enabled ? 'active' : 'paused'}</span>
                </div>
                <div className="muted small ellipsis">
                  {title(s.playbook)} · {describeTarget(s, hosts)} ({s.target_count})
                </div>
                <div className="small">
                  <CronLabel cron={s.cron} />
                  {s.enabled && <span className="muted"> · next {formatWhen(s.next_run_at)}</span>}
                </div>
                {s.last_message && <div className="small text-warn">{s.last_message}</div>}
              </button>
              <div className="row gap-s">
                {s.last_run_id ? (
                  <Link to={`/runs/${s.last_run_id}`} className="row gap-s grow small last-run">
                    <span className="muted">last {timeAgo(s.last_run_at)}</span>
                    {s.last_run_status && <StatusBadge status={s.last_run_status} />}
                  </Link>
                ) : (
                  <span className="muted small grow">never run</span>
                )}
                <button className="btn btn-small" onClick={() => toggleEnabled(s)}>
                  {s.enabled ? 'Pause' : 'Resume'}
                </button>
                <button className="btn btn-small" onClick={() => runNow(s)}>
                  Run now
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <button className="fab" onClick={() => open(null)} aria-label="New schedule">
        <PlusIcon />
      </button>

      <ScheduleForm
        open={formOpen}
        schedule={editing}
        playbooks={playbooks}
        hosts={hosts}
        onClose={() => setFormOpen(false)}
        onSave={save}
        onDelete={editing ? remove : undefined}
      />
    </div>
  )
}
