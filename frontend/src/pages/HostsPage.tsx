import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { HealthLabels } from '../components/Health'
import { HostForm } from '../components/HostForm'
import { KeyDeploySheet } from '../components/KeyDeploySheet'
import { PlusIcon, SearchIcon } from '../components/Icons'
import { HealthDot } from '../components/Status'
import { toast } from '../components/Toast'
import type { Host, HostInput } from '../types'
import { hostHealth, osLabel, timeAgo } from '../util'

export function HostsPage() {
  const [hosts, setHosts] = useState<Host[] | null>(null)
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<Host | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [keyIds, setKeyIds] = useState<number[] | null>(null)

  const load = () => api.hosts().then(setHosts).catch(toast.error)
  useEffect(() => {
    load()
  }, [])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (hosts ?? []).filter(
      (h) => !q || [h.name, h.address, h.kind, h.os_name ?? '', ...h.tags].some((v) => v.toLowerCase().includes(q)),
    )
  }, [hosts, query])

  function open(h: Host | null) {
    setEditing(h)
    setFormOpen(true)
  }

  async function save(data: HostInput) {
    if (editing) await api.updateHost(editing.id, data)
    else await api.createHost(data)
    toast.info(editing ? 'Host updated' : 'Host added')
    setFormOpen(false)
    load()
  }

  async function remove() {
    if (!editing) return
    await api.deleteHost(editing.id)
    toast.info('Host deleted')
    setFormOpen(false)
    load()
  }

  if (!hosts) return <div className="empty">Loading…</div>

  return (
    <div className="page">
      <div className="search">
        <SearchIcon width={18} height={18} />
        <input
          type="search"
          placeholder={`Search ${hosts.length} hosts…`}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoCapitalize="off"
        />
      </div>

      {hosts.length > 0 && (
        <button
          className="btn"
          onClick={() => setKeyIds(hosts.filter((h) => h.enabled && (h.last_error || !h.last_seen)).map((h) => h.id))}
        >
          Install SSH key…
        </button>
      )}

      {hosts.length === 0 && (
        <div className="empty">No hosts yet. Tap + to add one, or import LXCs from the Proxmox tab.</div>
      )}

      <ul className="list">
        {visible.map((h) => (
          <li key={h.id}>
            <button className={`card card-link ${h.enabled ? '' : 'disabled'}`} onClick={() => open(h)}>
              <div className="row">
                <div className="card-title grow ellipsis">
                  <HealthDot health={hostHealth(h)} /> {h.name}
                </div>
                <span className="muted small">{h.kind}</span>
              </div>
              <div className="muted small ellipsis">
                {h.ssh_user ? `${h.ssh_user}@` : ''}
                {h.address}
                {h.port !== 22 ? `:${h.port}` : ''} · {osLabel(h)}
              </div>
              {h.last_error ? (
                <div className="small text-error ellipsis">{h.last_error}</div>
              ) : (
                <div className="muted small">seen {timeAgo(h.last_seen)}</div>
              )}
              <HealthLabels host={h} />
              {h.tags.length > 0 && (
                <div className="chips chips-static">
                  {h.tags.map((t) => (
                    <span key={t} className="chip chip-small">
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </button>
          </li>
        ))}
      </ul>

      <button className="fab" onClick={() => open(null)} aria-label="Add host">
        <PlusIcon />
      </button>

      <HostForm
        open={formOpen}
        host={editing}
        onClose={() => setFormOpen(false)}
        onSave={save}
        onDelete={editing ? remove : undefined}
        onDeployKey={
          editing
            ? () => {
                setFormOpen(false)
                setKeyIds([editing.id])
              }
            : undefined
        }
      />

      <KeyDeploySheet
        open={keyIds !== null}
        hosts={hosts}
        initialIds={keyIds ?? []}
        onClose={() => setKeyIds(null)}
        onDone={load}
      />
    </div>
  )
}
