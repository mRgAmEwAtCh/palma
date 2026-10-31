import { useEffect, useState } from 'react'
import { api } from '../api'
import { PlusIcon } from '../components/Icons'
import { KeyDeploySheet } from '../components/KeyDeploySheet'
import { Sheet } from '../components/Sheet'
import { toast } from '../components/Toast'
import type { Discovery, Host, ProxmoxSource, ProxmoxSourceInput } from '../types'
import { timeAgo } from '../util'

const emptySource: ProxmoxSourceInput = {
  name: '',
  url: 'https://',
  token_id: '',
  token_secret: '',
  verify_ssl: false,
  default_ssh_user: 'root',
}

export function ProxmoxPage() {
  const [sources, setSources] = useState<ProxmoxSource[] | null>(null)
  const [editing, setEditing] = useState<ProxmoxSource | null>(null)
  const [form, setForm] = useState<ProxmoxSourceInput>(emptySource)
  const [formOpen, setFormOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  const [discoverFor, setDiscoverFor] = useState<ProxmoxSource | null>(null)
  const [discovery, setDiscovery] = useState<Discovery | null>(null)
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [keyHosts, setKeyHosts] = useState<Host[] | null>(null)
  const [keyIds, setKeyIds] = useState<number[]>([])

  const load = () => api.sources().then(setSources).catch(toast.error)
  useEffect(() => {
    load()
  }, [])

  function openForm(s: ProxmoxSource | null) {
    setEditing(s)
    setForm(s ? { ...s, token_secret: '' } : emptySource)
    setFormOpen(true)
  }

  async function save() {
    setBusy(true)
    try {
      if (editing) await api.updateSource(editing.id, form)
      else await api.createSource(form)
      setFormOpen(false)
      load()
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!editing || !confirm(`Delete source "${editing.name}"? Imported hosts are kept.`)) return
    try {
      await api.deleteSource(editing.id)
      setFormOpen(false)
      load()
    } catch (e) {
      toast.error(e)
    }
  }

  async function discover(s: ProxmoxSource) {
    setDiscoverFor(s)
    setDiscovery(null)
    try {
      const result = await api.discover(s.id)
      setDiscovery(result)
      setPicked(new Set(result.guests.filter((g) => g.host_id === null && g.ip && g.manageable).map((g) => g.vmid)))
    } catch (e) {
      toast.error(e)
      setDiscoverFor(null)
    }
  }

  async function doImport() {
    if (!discoverFor) return
    setBusy(true)
    try {
      const r = await api.importContainers(discoverFor.id, [...picked])
      const skipped = r.skipped.length ? `, ${r.skipped.length} skipped (${r.skipped.map((x) => x.name).join(', ')})` : ''
      toast.info(`${r.created} imported, ${r.updated} refreshed${skipped}`)
      setDiscoverFor(null)
      load()
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy(false)
    }
  }

  async function openKeyDeploy(src: ProxmoxSource) {
    try {
      const all = await api.hosts()
      setKeyIds(all.filter((h) => h.proxmox_source_id === src.id && h.enabled && (h.last_error || !h.last_seen)).map((h) => h.id))
      setKeyHosts(all)
    } catch (e) {
      toast.error(e)
    }
  }

  const togglePick = (vmid: number) =>
    setPicked((p) => {
      const n = new Set(p)
      if (n.has(vmid)) n.delete(vmid)
      else n.add(vmid)
      return n
    })

  const set = <K extends keyof ProxmoxSourceInput>(k: K, v: ProxmoxSourceInput[K]) =>
    setForm((f) => ({ ...f, [k]: v }))

  if (!sources) return <div className="empty">Loading…</div>

  return (
    <div className="page">
      {sources.length === 0 && (
        <div className="empty">
          Add your Proxmox nodes to import LXC containers and VMs as hosts. Create an API token (Datacenter → Permissions → API
          Tokens) and grant it the <b>PVEAuditor</b> role on path <code>/</code> (Permissions → Add → API Token
          Permission). One source per cluster is enough.
        </div>
      )}
      <ul className="list">
        {sources.map((s) => (
          <li key={s.id} className="card">
            <div className="row">
              <div className="grow min0">
                <div className="card-title">{s.name}</div>
                <div className="muted small ellipsis">{s.url}</div>
                <div className="muted small">synced {timeAgo(s.last_sync)}</div>
              </div>
            </div>
            <div className="row gap-s">
              <button className="btn btn-primary grow" onClick={() => discover(s)}>
                Discover guests
              </button>
              <button className="btn" onClick={() => openForm(s)}>
                Edit
              </button>
            </div>
            <button className="btn" onClick={() => openKeyDeploy(s)}>
              Install SSH key in guests…
            </button>
          </li>
        ))}
      </ul>

      <button className="fab" onClick={() => openForm(null)} aria-label="Add Proxmox source">
        <PlusIcon />
      </button>

      <Sheet
        title={editing ? `Edit ${editing.name}` : 'Add Proxmox source'}
        open={formOpen}
        onClose={() => setFormOpen(false)}
        footer={
          <>
            {editing && (
              <button className="btn btn-danger" onClick={remove}>
                Delete
              </button>
            )}
            <button className="btn btn-primary grow" onClick={save} disabled={busy}>
              Save
            </button>
          </>
        }
      >
        <div className="form">
          <label>
            Name
            <input value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="pve1" autoCapitalize="off" />
          </label>
          <label>
            API URL
            <input
              value={form.url}
              onChange={(e) => set('url', e.target.value)}
              placeholder="https://192.168.1.2:8006"
              inputMode="url"
              autoCapitalize="off"
            />
          </label>
          <label>
            Token ID
            <input
              value={form.token_id}
              onChange={(e) => set('token_id', e.target.value)}
              placeholder="root@pam!homelab"
              autoCapitalize="off"
            />
          </label>
          <label>
            Token secret {editing && <span className="muted">(leave empty to keep)</span>}
            <input
              type="password"
              value={form.token_secret ?? ''}
              onChange={(e) => set('token_secret', e.target.value)}
              autoComplete="off"
            />
          </label>
          <label>
            Default SSH user for imported hosts
            <input
              value={form.default_ssh_user}
              onChange={(e) => set('default_ssh_user', e.target.value)}
              autoCapitalize="off"
            />
          </label>
          <label className="switch">
            <input type="checkbox" checked={form.verify_ssl} onChange={(e) => set('verify_ssl', e.target.checked)} />
            <span>Verify TLS certificate</span>
          </label>
        </div>
      </Sheet>

      <Sheet
        title={discoverFor ? `Guests on ${discoverFor.name}` : ''}
        open={discoverFor !== null}
        onClose={() => setDiscoverFor(null)}
        footer={
          <button className="btn btn-primary btn-block" onClick={doImport} disabled={busy || !picked.size}>
            Import / refresh {picked.size}
          </button>
        }
      >
        {!discovery ? (
          <div className="empty">Querying Proxmox…</div>
        ) : (
          <div className="muted small discovery-nodes">
            Nodes: {discovery.nodes.length ? discovery.nodes.join(', ') : 'none'} ·{' '}
            {discovery.guests.filter((g) => g.type === 'lxc').length} LXC ·{' '}
            {discovery.guests.filter((g) => g.type === 'qemu').length} VM
          </div>
        )}
        {discovery?.warning && <div className="alert alert-error selectable-text">{discovery.warning}</div>}
        {discovery && discovery.guests.length > 0 && (
          <ul className="list">
            {discovery.guests.map((c) => (
              <li key={c.vmid}>
                <label className={`card check-card ${picked.has(c.vmid) ? 'checked' : ''}`}>
                  <input type="checkbox" checked={picked.has(c.vmid)} onChange={() => togglePick(c.vmid)} />
                  <div className="grow min0">
                    <div className="card-title row gap-s">
                      <span className="grow ellipsis">
                        {c.vmid} · {c.name}
                      </span>
                      <span className={`badge ${c.type === 'qemu' ? 'badge-changed' : ''}`}>{c.type === 'qemu' ? 'VM' : 'LXC'}</span>
                    </div>
                    <div className="muted small ellipsis">
                      {c.ip ?? 'no IP'} · {c.ostype ?? '?'} · {c.node} · {c.status}
                    </div>
                    {c.note && <div className={`small ${c.manageable ? 'muted' : 'text-error'}`}>{c.note}</div>}
                    {c.host_id !== null && <div className="small text-ok">already a host (will be refreshed)</div>}
                  </div>
                </label>
              </li>
            ))}
          </ul>
        )}
      </Sheet>

      <KeyDeploySheet
        open={keyHosts !== null}
        hosts={keyHosts ?? []}
        initialIds={keyIds}
        initialMethod="proxmox"
        onClose={() => setKeyHosts(null)}
        onDone={() => undefined}
      />
    </div>
  )
}
