import { AnsiUp } from 'ansi_up'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { BackIcon } from '../components/Icons'
import { StatusBadge } from '../components/Status'
import { toast } from '../components/Toast'
import type { Host, RerunState, Run } from '../types'
import { duration, hostOutcome, parseDate } from '../util'

const ACTIVE = new Set(['pending', 'running'])

/** Ansible pads banners with ~80 '*' which wrap badly on phones. */
const tidy = (text: string) => text.replace(/ ?\*{4,}/g, ' ***')

export function RunDetailPage() {
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const [run, setRun] = useState<Run | null>(null)
  const [hosts, setHosts] = useState<Host[]>([])
  const [html, setHtml] = useState('')
  const [wrap, setWrap] = useState(true)
  const [follow, setFollow] = useState(true)
  const [, tick] = useState(0)
  const logRef = useRef<HTMLPreElement>(null)

  const refresh = useCallback(() => api.run(id).then(setRun).catch(toast.error), [id])

  useEffect(() => {
    refresh()
    api.hosts().then(setHosts).catch(() => undefined)
    const ansi = new AnsiUp()
    let buffer = ''
    setHtml('')

    const es = new EventSource(`/api/runs/${id}/stream`)
    es.addEventListener('log', (e) => {
      buffer += ansi.ansi_to_html(tidy((e as MessageEvent).data + '\n'))
      setHtml(buffer)
    })
    es.addEventListener('end', () => {
      es.close()
      refresh()
    })
    es.onerror = () => {
      // Avoid duplicated output from EventSource's auto-reconnect: fall back to a full reload.
      es.close()
      api
        .runLog(id)
        .then((text) => setHtml(new AnsiUp().ansi_to_html(tidy(text))))
        .catch(() => undefined)
      refresh()
    }
    return () => es.close()
  }, [id, refresh])

  // Keep the duration counter ticking while running.
  useEffect(() => {
    if (!run || !ACTIVE.has(run.status)) return
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [run])

  useEffect(() => {
    if (follow && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [html, follow])

  if (!run) return <div className="empty">Loading…</div>

  const active = ACTIVE.has(run.status)
  const idByName = new Map(hosts.map((h) => [h.name, h.id]))
  const failedNames = run.host_names.filter((n) => ['failed', 'unreachable'].includes(hostOutcome(run.stats, n)))

  function rerun(names?: string[]) {
    const ids = names ? names.map((n) => idByName.get(n)).filter((x): x is number => x !== undefined) : run!.host_ids
    const state: RerunState = {
      playbook: run!.playbook,
      host_ids: ids,
      check_mode: run!.check_mode,
      extra_vars: run!.extra_vars,
    }
    navigate('/', { state })
  }

  async function cancel() {
    try {
      await api.cancelRun(id)
      toast.info('Cancel requested')
    } catch (e) {
      toast.error(e)
    }
  }

  return (
    <div className="page">
      <div className="row gap-s">
        <Link to="/runs" className="icon-btn" aria-label="Back to history">
          <BackIcon />
        </Link>
        <h2 className="grow ellipsis">
          #{run.id} {run.playbook}
        </h2>
        <StatusBadge status={run.status} />
      </div>

      <div className="card meta">
        <div>
          <span className="muted">Started</span> {parseDate(run.started_at ?? run.created_at)?.toLocaleString()}
        </div>
        <div>
          <span className="muted">Duration</span> {duration(run.started_at, run.finished_at)}
        </div>
        {run.check_mode && <div className="badge badge-pending">dry run</div>}
        {run.triggered_by && (
          <div>
            <span className="muted">By</span> {run.triggered_by}
          </div>
        )}
        {Object.keys(run.extra_vars).length > 0 && (
          <div className="mono small ellipsis">
            <span className="muted">Vars</span> {JSON.stringify(run.extra_vars)}
          </div>
        )}
      </div>

      <ul className="host-results">
        {run.host_names.map((n) => (
          <li key={n}>
            <span className="ellipsis">{n}</span>
            <StatusBadge status={active ? 'running' : hostOutcome(run.stats, n)} />
          </li>
        ))}
      </ul>

      <div className="row gap-s wrap-row">
        {active ? (
          <button className="btn btn-danger" onClick={cancel}>
            Cancel run
          </button>
        ) : (
          <>
            <button className="btn" onClick={() => rerun()}>
              Run again
            </button>
            {failedNames.length > 0 && (
              <button className="btn" onClick={() => rerun(failedNames)}>
                Retry {failedNames.length} failed
              </button>
            )}
          </>
        )}
        <span className="grow" />
        <label className="switch small">
          <input type="checkbox" checked={wrap} onChange={(e) => setWrap(e.target.checked)} />
          <span>Wrap</span>
        </label>
        <label className="switch small">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
          <span>Follow</span>
        </label>
      </div>

      <pre
        ref={logRef}
        className={`log log-fill ${wrap ? 'wrap' : ''}`}
        dangerouslySetInnerHTML={{ __html: html || (active ? 'Waiting for output…' : '') }}
      />
    </div>
  )
}
