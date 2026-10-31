import { useEffect, useState } from 'react'
import type { Host, HostInput } from '../types'
import { guestLabel } from '../util'
import { HealthDetails } from './Health'
import { Sheet } from './Sheet'

const KINDS = ['lxc', 'vm', 'baremetal', 'other']

interface Props {
  open: boolean
  host: Host | null
  onClose: () => void
  onSave: (data: HostInput) => Promise<void>
  onDelete?: () => Promise<void>
  onDeployKey?: () => void
}

const empty: HostInput = {
  name: '',
  address: '',
  port: 22,
  ssh_user: null,
  kind: 'lxc',
  tags: [],
  vars: {},
  enabled: true,
  notes: '',
}

export function HostForm({ open, host, onClose, onSave, onDelete, onDeployKey }: Props) {
  const [form, setForm] = useState<HostInput>(empty)
  const [tags, setTags] = useState('')
  const [vars, setVars] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    const src = host ?? empty
    setForm({ ...empty, ...src })
    setTags(src.tags.join(', '))
    setVars(Object.keys(src.vars).length ? JSON.stringify(src.vars, null, 2) : '')
    setError(null)
  }, [open, host])

  const set = <K extends keyof HostInput>(k: K, v: HostInput[K]) => setForm((f) => ({ ...f, [k]: v }))

  async function submit(e?: React.FormEvent) {
    e?.preventDefault()
    let parsedVars: Record<string, unknown> = {}
    try {
      parsedVars = vars.trim() ? JSON.parse(vars) : {}
    } catch {
      setError('Host vars must be valid JSON')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await onSave({
        ...form,
        ssh_user: form.ssh_user?.trim() || null,
        tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
        vars: parsedVars,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!onDelete || !confirm(`Delete host "${host?.name}"?`)) return
    setBusy(true)
    try {
      await onDelete()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Sheet
      title={host ? `Edit ${host.name}` : 'Add host'}
      open={open}
      onClose={onClose}
      footer={
        <>
          {host && onDelete && (
            <button className="btn btn-danger" onClick={remove} disabled={busy}>
              Delete
            </button>
          )}
          <button className="btn btn-primary grow" onClick={() => submit()} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </>
      }
    >
      <form className="form" onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        {host && <HealthDetails host={host} />}
        {host && onDeployKey && (
          <button type="button" className="btn" onClick={onDeployKey}>
            Install SSH key…
          </button>
        )}
        {host?.source === 'proxmox' && (
          <div className="alert">
            Imported from Proxmox ({host.proxmox_node} / {guestLabel(host.proxmox_type, host.proxmox_vmid)}). Address is refreshed on re-import.
          </div>
        )}
        <label>
          Name
          <input value={form.name} onChange={(e) => set('name', e.target.value)} required autoCapitalize="off" />
        </label>
        <label>
          Address (IP or hostname)
          <input
            value={form.address}
            onChange={(e) => set('address', e.target.value)}
            required
            inputMode="url"
            autoCapitalize="off"
            autoCorrect="off"
          />
        </label>
        <div className="row">
          <label className="grow">
            SSH user
            <input
              value={form.ssh_user ?? ''}
              placeholder="default"
              onChange={(e) => set('ssh_user', e.target.value)}
              autoCapitalize="off"
            />
          </label>
          <label style={{ width: '6.5rem' }}>
            Port
            <input
              type="number"
              inputMode="numeric"
              value={form.port}
              onChange={(e) => set('port', Number(e.target.value) || 22)}
            />
          </label>
        </div>
        <label>
          Type
          <select value={form.kind} onChange={(e) => set('kind', e.target.value)}>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <label>
          Tags (comma separated)
          <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="docker, pve1" autoCapitalize="off" />
        </label>
        <label className="switch">
          <input type="checkbox" checked={form.enabled} onChange={(e) => set('enabled', e.target.checked)} />
          <span>Enabled (selectable for runs)</span>
        </label>
        <label>
          Host vars (JSON, optional)
          <textarea
            rows={3}
            value={vars}
            onChange={(e) => setVars(e.target.value)}
            placeholder='{"ansible_python_interpreter": "/usr/bin/python3"}'
            className="mono"
            autoCapitalize="off"
            spellCheck={false}
          />
        </label>
        <label>
          Notes
          <textarea rows={2} value={form.notes} onChange={(e) => set('notes', e.target.value)} />
        </label>
        <button type="submit" hidden />
      </form>
    </Sheet>
  )
}
