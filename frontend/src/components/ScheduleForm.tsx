import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { CronPreview, Host, Playbook, Schedule, ScheduleInput } from '../types'
import { changedVars, formatExtraVars, parseExtraVars } from '../util'
import { Sheet } from './Sheet'

export const CRON_PRESETS: { label: string; cron: string }[] = [
  { label: 'Hourly', cron: '0 * * * *' },
  { label: 'Every 6 h', cron: '0 */6 * * *' },
  { label: 'Daily 03:00', cron: '0 3 * * *' },
  { label: 'Weekly Mon 04:00', cron: '0 4 * * 1' },
]

type TargetMode = 'all' | 'tags' | 'hosts'

interface Props {
  open: boolean
  schedule: Schedule | null
  playbooks: Playbook[]
  hosts: Host[]
  onClose: () => void
  onSave: (body: ScheduleInput) => Promise<void>
  onDelete?: () => Promise<void>
}

export function ScheduleForm({ open, schedule, playbooks, hosts, onClose, onSave, onDelete }: Props) {
  const [name, setName] = useState('')
  const [playbook, setPlaybook] = useState('')
  const [cron, setCron] = useState('0 */6 * * *')
  const [enabled, setEnabled] = useState(true)
  const [mode, setMode] = useState<TargetMode>('all')
  const [tags, setTags] = useState<Set<string>>(new Set())
  const [hostIds, setHostIds] = useState<Set<number>>(new Set())
  const [extraVars, setExtraVars] = useState('')
  const [preview, setPreview] = useState<CronPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const current = playbooks.find((p) => p.path === playbook)

  useEffect(() => {
    if (!open) return
    const pb = schedule?.playbook ?? (playbooks.find((p) => p.path === 'health.yml') ?? playbooks[0])?.path ?? ''
    const defaults = playbooks.find((p) => p.path === pb)?.vars ?? {}
    setName(schedule?.name ?? 'Health check')
    setPlaybook(pb)
    setCron(schedule?.cron ?? '0 */6 * * *')
    setEnabled(schedule?.enabled ?? true)
    setMode(schedule?.target_host_ids.length ? 'hosts' : schedule?.target_tags.length ? 'tags' : 'all')
    setTags(new Set(schedule?.target_tags ?? []))
    setHostIds(new Set(schedule?.target_host_ids ?? []))
    setExtraVars(formatExtraVars({ ...defaults, ...(schedule?.extra_vars ?? {}) }))
    setError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (!open) return
    const t = setTimeout(() => {
      api.cronPreview(cron).then(setPreview).catch(() => setPreview(null))
    }, 300)
    return () => clearTimeout(t)
  }, [cron, open])

  const groups = useMemo(() => {
    const set = new Set<string>()
    hosts.forEach((h) => {
      set.add(h.kind)
      h.tags.forEach((t) => set.add(t))
    })
    return [...set].sort()
  }, [hosts])

  const matching = useMemo(() => {
    const enabledHosts = hosts.filter((h) => h.enabled)
    if (mode === 'hosts') return enabledHosts.filter((h) => hostIds.has(h.id))
    if (mode === 'tags') return enabledHosts.filter((h) => tags.has(h.kind) || h.tags.some((t) => tags.has(t)))
    return enabledHosts
  }, [hosts, mode, tags, hostIds])

  function choosePlaybook(path: string) {
    setPlaybook(path)
    setExtraVars(formatExtraVars(playbooks.find((p) => p.path === path)?.vars ?? {}))
  }

  function toggle<T>(set: Set<T>, value: T, apply: (s: Set<T>) => void) {
    const n = new Set(set)
    if (n.has(value)) n.delete(value)
    else n.add(value)
    apply(n)
  }

  async function submit() {
    let vars: Record<string, unknown>
    try {
      vars = changedVars(parseExtraVars(extraVars), current?.vars ?? {})
    } catch (e) {
      return setError(e instanceof Error ? e.message : String(e))
    }
    if (mode === 'tags' && !tags.size) return setError('Select at least one tag')
    if (mode === 'hosts' && !hostIds.size) return setError('Select at least one host')
    setBusy(true)
    setError(null)
    try {
      await onSave({
        name: name.trim() || current?.title || playbook,
        playbook,
        cron,
        enabled,
        target_tags: mode === 'tags' ? [...tags] : [],
        target_host_ids: mode === 'hosts' ? [...hostIds] : [],
        extra_vars: vars,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Sheet
      title={schedule ? `Edit ${schedule.name}` : 'New schedule'}
      open={open}
      onClose={onClose}
      footer={
        <>
          {onDelete && (
            <button
              className="btn btn-danger"
              disabled={busy}
              onClick={() => confirm(`Delete schedule "${schedule?.name}"?`) && onDelete()}
            >
              Delete
            </button>
          )}
          <button className="btn btn-primary grow" onClick={submit} disabled={busy || !playbook || !preview?.valid}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </>
      }
    >
      <div className="form">
        {error && <div className="alert alert-error">{error}</div>}
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Playbook
          <select value={playbook} onChange={(e) => choosePlaybook(e.target.value)}>
            {playbooks.map((p) => (
              <option key={p.path} value={p.path}>
                {p.title} ({p.path})
              </option>
            ))}
          </select>
        </label>

        <label>
          Cron (minute hour day month weekday)
          <input
            className="mono"
            value={cron}
            onChange={(e) => setCron(e.target.value)}
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
          />
        </label>
        <div className="chips chips-static">
          {CRON_PRESETS.map((p) => (
            <button key={p.cron} className={`chip ${cron === p.cron ? 'chip-active' : ''}`} onClick={() => setCron(p.cron)}>
              {p.label}
            </button>
          ))}
        </div>
        {preview && (
          <div className={`small ${preview.valid ? 'muted' : 'text-error'}`}>
            {preview.valid
              ? `Next: ${preview.next.map((d) => new Date(d).toLocaleString([], { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })).join(' · ')}`
              : preview.error}
          </div>
        )}

        <span className="section-title">Hosts ({matching.length})</span>
        <div className="segmented" role="radiogroup" aria-label="Target">
          {(['all', 'tags', 'hosts'] as TargetMode[]).map((m) => (
            <button key={m} role="radio" aria-checked={mode === m} className={mode === m ? 'active' : ''} onClick={() => setMode(m)}>
              {m === 'all' ? 'All hosts' : m === 'tags' ? 'By tag' : 'Selected'}
            </button>
          ))}
        </div>
        {mode === 'all' && <p className="muted small">All enabled hosts at run time, including hosts added later.</p>}
        {mode === 'tags' && (
          <div className="chips chips-static">
            {groups.map((g) => (
              <button key={g} className={`chip ${tags.has(g) ? 'chip-active' : ''}`} onClick={() => toggle(tags, g, setTags)}>
                {g}
              </button>
            ))}
          </div>
        )}
        {mode === 'hosts' && (
          <ul className="list">
            {hosts.map((h) => (
              <li key={h.id}>
                <label className={`card check-card ${hostIds.has(h.id) ? 'checked' : ''} ${h.enabled ? '' : 'disabled'}`}>
                  <input type="checkbox" checked={hostIds.has(h.id)} onChange={() => toggle(hostIds, h.id, setHostIds)} />
                  <div className="grow min0">
                    <div className="card-title ellipsis">{h.name}</div>
                    <div className="muted small ellipsis">
                      {h.address} · {h.kind}
                    </div>
                  </div>
                </label>
              </li>
            ))}
          </ul>
        )}

        <label>
          Extra vars (key=value per line)
          <textarea
            className="mono"
            rows={Math.min(12, Math.max(3, extraVars.split('\n').length + 2))}
            value={extraVars}
            onChange={(e) => setExtraVars(e.target.value)}
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
          />
        </label>
        <label className="switch">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          <span>Enabled</span>
        </label>
      </div>
    </Sheet>
  )
}
