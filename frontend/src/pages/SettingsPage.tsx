import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { toast } from '../components/Toast'
import { ToolVersionsCard } from '../components/ToolVersionsCard'
import type { Me, SystemInfo, ToolVersions } from '../types'

interface Props {
  me: Me
  versions: ToolVersions | null
  onVersions: (v: ToolVersions) => void
}

export function SettingsPage({ me, versions, onVersions }: Props) {
  const [info, setInfo] = useState<SystemInfo | null>(null)

  useEffect(() => {
    api.system().then(setInfo).catch(toast.error)
  }, [])

  async function copyKey() {
    if (!info?.ssh_public_key) return
    try {
      await navigator.clipboard.writeText(info.ssh_public_key)
      toast.info('Public key copied')
    } catch {
      toast.error('Clipboard not available (needs HTTPS); long-press the key to copy')
    }
  }

  return (
    <div className="page">
      <section className="card">
        <div className="card-title">{me.name ?? me.sub}</div>
        {me.email && <div className="muted small">{me.email}</div>}
        {me.auth_mode === 'disabled' ? (
          <div className="alert alert-error">Authentication is disabled (AUTH_DISABLED=true).</div>
        ) : (
          <>
            <div className="muted small">Signed in via {me.auth_mode === 'oidc' ? 'Authentik (OIDC)' : 'local account'}</div>
            <a className="btn" href="/auth/logout">
              Log out
            </a>
          </>
        )}
      </section>

      <section className="card">
        <div className="card-title">Controller SSH key</div>
        {info ? (
          info.ssh_public_key ? (
            <>
              <p className="muted small">
                Add this key to <code>~/.ssh/authorized_keys</code> of the SSH user on every managed host.
              </p>
              <pre className="log wrap selectable">{info.ssh_public_key}</pre>
              <button className="btn" onClick={copyKey}>
                Copy public key
              </button>
            </>
          ) : (
            <div className="alert alert-error">No usable private key found at {info.ssh_key_path}</div>
          )
        ) : (
          <div className="muted">Loading…</div>
        )}
      </section>

      <section className="card">
        <div className="card-title">Playbooks</div>
        <p className="muted small">Create, edit and validate the playbooks available on the Run tab.</p>
        <Link className="btn" to="/playbooks">
          Manage playbooks
        </Link>
      </section>

      <ToolVersionsCard versions={versions} onChange={onVersions} />

      {info && (
        <section className="card small">
          <div>
            <span className="muted">Ansible</span> {info.ansible_version ?? 'not found'}
          </div>
          <div>
            <span className="muted">Default SSH user</span> {info.default_ssh_user}
          </div>
          <div className="ellipsis">
            <span className="muted">Playbooks</span> {info.playbooks_dir}
          </div>
        </section>
      )}
    </div>
  )
}
