import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { SearchIcon } from '../components/Icons'
import { Sheet } from '../components/Sheet'
import { HealthBadge } from '../components/Health'
import { HealthDot } from '../components/Status'
import { toast } from '../components/Toast'
import type { Host, Playbook, RerunState } from '../types'
import { changedVars, formatExtraVars, hostHealth, osLabel, parseExtraVars } from '../util'

export function RunPage() {
  const navigate = useNavigate()
  const rerun = (useLocation().state as RerunState | null) ?? null

  const [playbooks, setPlaybooks] = useState<Playbook[]>([])
  const [hosts, setHosts] = useState<Host[]>([])
  const [loading, setLoading] = useState(true)
  const [playbook, setPlaybook] = useState<string | null>(rerun?.playbook ?? null)
  const [selected, setSelected] = useState<Set<number>>(new Set(rerun?.host_ids ?? []))
  const [query, setQuery] = useState('')
  const [checkMode, setCheckMode] = useState(rerun?.check_mode ?? false)
  const [extraVars, setExtraVars] = useState(rerun ? formatExtraVars(rerun.extra_vars) : '')
  const [showOptions, setShowOptions] = useState(Boolean(rerun && Object.keys(rerun.extra_vars).length))
  const [pickerOpen, setPickerOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    Promise.all([api.playbooks(), api.hosts()])
      .then(([p, h]) => {
        setPlaybooks(p)
        setHosts(h)
        const pb = rerun && p.find((x) => x.path === rerun.playbook)
        if (pb) {
          // Re-run: defaults merged with the values that were changed in that run
          setExtraVars(formatExtraVars({ ...pb.vars, ...rerun.extra_vars }))
          setShowOptions(Object.keys(pb.vars).length > 0 || Object.keys(rerun.extra_vars).length > 0)
        }
      })
      .catch(toast.error)
      .finally(() => setLoading(false))
  }, [])

  const groups = useMemo(() => {
    const set = new Set<string>()
    hosts.forEach((h) => {
      set.add(h.kind)
      h.tags.forEach((t) => set.add(t))
    })
    return [...set].sort()
  }, [hosts])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return hosts
    return hosts.filter((h) =>
      [h.name, h.address, h.kind, h.os_name ?? '', ...h.tags].some((v) => v.toLowerCase().includes(q)),
    )
  }, [hosts, query])

  const selectable = (h: Host) => h.enabled
  const inGroup = (h: Host, g: string) => h.kind === g || h.tags.includes(g)

  function toggle(id: number) {
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  }

  function toggleGroup(g: string) {
    const members = hosts.filter((h) => selectable(h) && inGroup(h, g)).map((h) => h.id)
    const all = members.every((id) => selected.has(id))
    setSelected((s) => {
      const n = new Set(s)
      members.forEach((id) => (all ? n.delete(id) : n.add(id)))
      return n
    })
  }

  function selectVisible(on: boolean) {
    setSelected((s) => {
      const n = new Set(s)
      visible.filter(selectable).forEach((h) => (on ? n.add(h.id) : n.delete(h.id)))
      return n
    })
  }

  const current = playbooks.find((p) => p.path === playbook)
  const hasDefaults = Boolean(current && Object.keys(current.vars).length)

  function selectPlaybook(p: Playbook) {
    setPlaybook(p.path)
    setExtraVars(formatExtraVars(p.vars))
    if (Object.keys(p.vars).length) setShowOptions(true)
  }

  async function start() {
    if (!playbook) return toast.error('Choose a playbook first')
    if (!selected.size) return toast.error('Select at least one host')
    let vars: Record<string, unknown>
    try {
      vars = changedVars(parseExtraVars(extraVars), current?.vars ?? {})
    } catch (e) {
      setShowOptions(true)
      return toast.error(e)
    }
    if (!checkMode && !confirm(`Run "${current?.title ?? playbook}" on ${selected.size} host(s)?`)) return
    setBusy(true)
    try {
      const run = await api.createRun({ playbook, host_ids: [...selected], check_mode: checkMode, extra_vars: vars })
      navigate(`/runs/${run.id}`)
    } catch (e) {
      toast.error(e)
      setBusy(false)
    }
  }

  const enabledCount = hosts.filter(selectable).length

  if (loading) return <div className="empty">Loading…</div>

  return (
    <div className="page with-action-bar">
      <section>
        <h2 className="section-title">1 · Playbook</h2>
        <button className="card picker" onClick={() => setPickerOpen(true)}>
          {current ? (
            <>
              <div className="card-title">{current.title}</div>
              <div className="muted small">{current.path}</div>
            </>
          ) : (
            <div className="muted">Tap to choose a playbook…</div>
          )}
        </button>
      </section>

      <section>
        <div className="section-head">
          <h2 className="section-title">
            2 · Hosts <span className="muted">({selected.size}/{enabledCount})</span>
          </h2>
          <div className="row gap-s">
            <button className="btn btn-small" onClick={() => selectVisible(true)}>
              All
            </button>
            <button className="btn btn-small" onClick={() => selectVisible(false)}>
              None
            </button>
          </div>
        </div>

        {hosts.length === 0 ? (
          <div className="empty">
            No hosts yet. Add some on the <Link to="/hosts">Hosts</Link> tab or import from Proxmox.
          </div>
        ) : (
          <>
            {groups.length > 0 && (
              <div className="chips" role="group" aria-label="Select by tag">
                {groups.map((g) => {
                  const members = hosts.filter((h) => selectable(h) && inGroup(h, g))
                  const active = members.length > 0 && members.every((h) => selected.has(h.id))
                  return (
                    <button
                      key={g}
                      className={`chip ${active ? 'chip-active' : ''}`}
                      onClick={() => toggleGroup(g)}
                      aria-pressed={active}
                    >
                      {g} <span className="chip-count">{members.length}</span>
                    </button>
                  )
                })}
              </div>
            )}

            <div className="search">
              <SearchIcon width={18} height={18} />
              <input
                type="search"
                placeholder="Filter hosts…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                autoCapitalize="off"
              />
            </div>

            <ul className="list">
              {visible.map((h) => (
                <li key={h.id}>
                  <label className={`card check-card ${selected.has(h.id) ? 'checked' : ''} ${h.enabled ? '' : 'disabled'}`}>
                    <input
                      type="checkbox"
                      checked={selected.has(h.id)}
                      disabled={!h.enabled}
                      onChange={() => toggle(h.id)}
                    />
                    <div className="grow min0">
                      <div className="card-title row gap-s">
                        <span className="grow ellipsis">
                          <HealthDot health={hostHealth(h)} title={h.last_error ?? undefined} /> {h.name}
                        </span>
                        <HealthBadge host={h} />
                      </div>
                      <div className="muted small ellipsis">
                        {h.address} · {osLabel(h)} · {h.kind}
                      </div>
                    </div>
                  </label>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section>
        <button className="link-btn" onClick={() => setShowOptions((v) => !v)}>
          {showOptions ? '▾' : '▸'} 3 · Options
        </button>
        {showOptions && (
          <div className="form">
            <label className="switch">
              <input type="checkbox" checked={checkMode} onChange={(e) => setCheckMode(e.target.checked)} />
              <span>Dry run (--check --diff)</span>
            </label>
            <label>
              Extra vars (key=value per line)
              <textarea
                rows={Math.min(12, Math.max(3, extraVars.split('\n').length + 2))}
                className="mono"
                value={extraVars}
                onChange={(e) => setExtraVars(e.target.value)}
                placeholder="key=value"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
              />
            </label>
            {hasDefaults && (
              <div className="row">
                <span className="muted small grow">Prefilled with the playbook defaults. Only changed values are sent.</span>
                <button className="btn btn-small" onClick={() => current && setExtraVars(formatExtraVars(current.vars))}>
                  Reset
                </button>
              </div>
            )}
          </div>
        )}
      </section>

      <div className="action-bar">
        <button className="btn btn-primary btn-block" disabled={busy || !playbook || !selected.size} onClick={start}>
          {busy
            ? 'Starting…'
            : `${checkMode ? 'Dry run' : 'Run'} on ${selected.size} host${selected.size === 1 ? '' : 's'}`}
        </button>
      </div>

      <Sheet title="Choose playbook" open={pickerOpen} onClose={() => setPickerOpen(false)}>
        {playbooks.length === 0 && <div className="empty">No playbooks found in the playbooks directory.</div>}
        <Link className="btn picker-manage" to="/playbooks">
          Manage playbooks…
        </Link>
        <ul className="list">
          {playbooks.map((p) => (
            <li key={p.path}>
              <div className={`card ${p.path === playbook ? 'checked' : ''}`}>
                <button
                  className="card-main"
                  onClick={() => {
                    selectPlaybook(p)
                    setPickerOpen(false)
                  }}
                >
                  <div className="card-title">{p.title}</div>
                  <div className="muted small">{p.path}</div>
                  {p.description && <p className="description">{p.description}</p>}
                </button>
                <Link className="btn btn-small" to={`/playbooks/edit/${encodeURIComponent(p.path)}`}>
                  Edit
                </Link>
              </div>
            </li>
          ))}
        </ul>
      </Sheet>

    </div>
  )
}
