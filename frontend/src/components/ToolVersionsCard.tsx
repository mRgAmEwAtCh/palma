import { useState } from 'react'
import { api } from '../api'
import type { ToolVersions } from '../types'
import { timeAgo } from '../util'
import { toast } from './Toast'

const UPDATE_CMD = 'docker compose pull && docker compose up -d'

interface Props {
  versions: ToolVersions | null
  onChange: (v: ToolVersions) => void
}

export function ToolVersionsCard({ versions, onChange }: Props) {
  const [busy, setBusy] = useState(false)

  async function refresh() {
    setBusy(true)
    try {
      onChange(await api.versions(true))
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <div className="row">
        <div className="card-title grow">Tool maintenance</div>
        {versions && (
          <span className={`badge ${versions.update_available ? 'badge-pending' : 'badge-ok'}`}>
            {versions.update_available ? 'Update available' : 'Up to date'}
          </span>
        )}
      </div>

      {!versions ? (
        <div className="muted small">Checking versions…</div>
      ) : (
        <ul className="list">
          {versions.components.map((c) => (
            <li key={c.name} className="version-row">
              <div className="row">
                <div className="grow min0">
                  <div className="ellipsis">
                    <b>{c.name}</b>
                  </div>
                  <div className="muted small ellipsis">{c.description}</div>
                </div>
                <VersionBadge status={c.status} level={c.level} />
              </div>
              <div className="small version-numbers">
                <span>
                  <span className="muted">installed</span> <code>{c.installed ?? '–'}</code>
                </span>
                <span>
                  <span className="muted">latest</span>{' '}
                  {c.url && c.latest ? (
                    <a href={c.url} target="_blank" rel="noreferrer">
                      <code>{c.latest}</code>
                    </a>
                  ) : (
                    <code>{c.latest ?? '–'}</code>
                  )}
                  {c.latest_released && <span className="muted"> · {timeAgo(c.latest_released)}</span>}
                </span>
              </div>
              {c.error && <div className="small text-error">{c.error}</div>}
            </li>
          ))}
        </ul>
      )}

      {versions?.update_available && (
        <>
          <p className="muted small">
            Dependencies are pinned and updated via Dependabot pull requests. Once the update is merged and released,
            update the container on the Docker host (or rebuild it with <code>docker compose up -d --build</code> after{' '}
            <code>git pull</code>):
          </p>
          <pre className="log wrap selectable">{UPDATE_CMD}</pre>
        </>
      )}

      <div className="row">
        <span className="muted small grow">{versions ? `checked ${timeAgo(versions.checked_at)}` : ''}</span>
        <button className="btn btn-small" onClick={refresh} disabled={busy}>
          {busy ? 'Checking…' : 'Check now'}
        </button>
      </div>
    </section>
  )
}

function VersionBadge({ status, level }: { status: string; level: string | null }) {
  if (status === 'current') return <span className="badge badge-ok">current</span>
  if (status === 'outdated') return <span className={`badge ${level === 'patch' ? 'badge-changed' : 'badge-pending'}`}>{level} update</span>
  if (status === 'missing') return <span className="badge badge-failed">missing</span>
  return <span className="badge">unknown</span>
}
