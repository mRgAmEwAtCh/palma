import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { Host, KeyDeployResult } from '../types'
import { HealthDot } from './Status'
import { Sheet } from './Sheet'
import { toast } from './Toast'
import { guestLabel, hostHealth } from '../util'

type Method = 'proxmox' | 'ssh'

interface Props {
  open: boolean
  hosts: Host[]
  initialIds: number[]
  initialMethod?: Method
  onClose: () => void
  onDone: () => void
}

const isGuest = (h: Host) => h.source === 'proxmox' && h.proxmox_vmid !== null

export function KeyDeploySheet({ open, hosts, initialIds, initialMethod, onClose, onDone }: Props) {
  const [method, setMethod] = useState<Method>('proxmox')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [username, setUsername] = useState('root')
  const [password, setPassword] = useState('')
  const [ensureSshd, setEnsureSshd] = useState(true)
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<KeyDeployResult[] | null>(null)

  // Reset only when the sheet opens; the parent reloads `hosts` after a run and results must stay visible.
  useEffect(() => {
    if (!open) return
    const initial = hosts.filter((h) => initialIds.includes(h.id))
    const m: Method = initialMethod ?? (initial.length > 0 && initial.every(isGuest) ? 'proxmox' : 'ssh')
    setMethod(m)
    setSelected(new Set(initial.filter((h) => m === 'ssh' || isGuest(h)).map((h) => h.id)))
    setUsername(m === 'ssh' && initial.length === 1 ? (initial[0].ssh_user ?? 'root') : 'root')
    setPassword('')
    setResults(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const candidates = useMemo(() => (method === 'proxmox' ? hosts.filter(isGuest) : hosts), [hosts, method])

  function switchMethod(m: Method) {
    setMethod(m)
    setResults(null)
    if (m === 'proxmox') {
      setUsername('root')
      setSelected((s) => new Set([...s].filter((id) => hosts.some((h) => h.id === id && isGuest(h)))))
    }
  }

  function toggle(id: number) {
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  }

  async function run() {
    setBusy(true)
    setResults(null)
    try {
      const r = await api.deployKey({ host_ids: [...selected], method, username, password, ensure_sshd: ensureSshd })
      setResults(r.results)
      const okCount = r.results.filter((x) => x.verified).length
      toast.info(`Key login verified on ${okCount}/${r.results.length} host(s)`)
      onDone()
    } catch (e) {
      toast.error(e)
    } finally {
      setPassword('')
      setBusy(false)
    }
  }

  const resultById = new Map((results ?? []).map((r) => [r.host_id, r]))

  return (
    <Sheet
      title="Install SSH key"
      open={open}
      onClose={onClose}
      footer={
        <button
          className="btn btn-primary btn-block"
          onClick={run}
          disabled={busy || !selected.size || !username || !password}
        >
          {busy ? 'Installing… (can take a while)' : `Install key on ${selected.size} host${selected.size === 1 ? '' : 's'}`}
        </button>
      }
    >
      <div className="form">
        <div className="segmented" role="radiogroup" aria-label="Method">
          <button
            role="radio"
            aria-checked={method === 'proxmox'}
            className={method === 'proxmox' ? 'active' : ''}
            onClick={() => switchMethod('proxmox')}
          >
            Via Proxmox node
          </button>
          <button
            role="radio"
            aria-checked={method === 'ssh'}
            className={method === 'ssh' ? 'active' : ''}
            onClick={() => switchMethod('ssh')}
          >
            Direct SSH
          </button>
        </div>

        <p className="muted small">
          {method === 'proxmox'
            ? 'Logs into the Proxmox node(s) and adds the key inside the guest: "pct exec" for containers, the QEMU guest agent ("qm guest exec") for VMs. No guest password needed. Use the root login of your Proxmox node.'
            : 'Logs into each host with the given user and password (like ssh-copy-id) and adds the key for that user. Requires password login over SSH to be allowed.'}{' '}
          The password is used once and not stored.
        </p>

        <div className="row">
          <label className="grow">
            {method === 'proxmox' ? 'Proxmox node user' : 'SSH user'}
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoCapitalize="off" autoCorrect="off" />
          </label>
        </div>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
        </label>
        {method === 'proxmox' && (
          <label className="switch">
            <input type="checkbox" checked={ensureSshd} onChange={(e) => setEnsureSshd(e.target.checked)} />
            <span>Install &amp; start SSH server if missing</span>
          </label>
        )}

        <div className="section-head">
          <span className="section-title">
            Hosts ({selected.size}/{candidates.length})
          </span>
          <div className="row gap-s">
            <button className="btn btn-small" onClick={() => setSelected(new Set(candidates.map((h) => h.id)))}>
              All
            </button>
            <button className="btn btn-small" onClick={() => setSelected(new Set())}>
              None
            </button>
          </div>
        </div>
        {candidates.length === 0 && (
          <div className="empty">No imported Proxmox guests. Import them on the Proxmox tab first.</div>
        )}
        <ul className="list">
          {candidates.map((h) => {
            const r = resultById.get(h.id)
            return (
              <li key={h.id}>
                <label className={`card check-card ${selected.has(h.id) ? 'checked' : ''}`}>
                  <input type="checkbox" checked={selected.has(h.id)} onChange={() => toggle(h.id)} />
                  <div className="grow min0">
                    <div className="card-title ellipsis">
                      <HealthDot health={hostHealth(h)} /> {h.name}
                    </div>
                    <div className="muted small ellipsis">
                      {h.address}
                      {method === 'proxmox' ? ` · ${h.proxmox_node} / ${guestLabel(h.proxmox_type, h.proxmox_vmid)}` : ` · ${h.kind}`}
                    </div>
                    {r && (
                      <div className={`small ${r.verified ? 'text-ok' : 'text-error'}`}>
                        {r.verified ? '✓ ' : r.ok ? '⚠ ' : '✗ '}
                        {r.message}
                      </div>
                    )}
                  </div>
                </label>
              </li>
            )
          })}
        </ul>
      </div>
    </Sheet>
  )
}
