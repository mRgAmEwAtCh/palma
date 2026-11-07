import { useEffect, useState } from 'react'
import { api } from '../api'
import type { PlaybookSource, RepositoryInput } from '../types'

export function PlaybookSources({ defaultRepository, onBusy }: { defaultRepository?: string; onBusy?: (busy: boolean) => void }) {
  const [sources, setSources] = useState<PlaybookSource[] | null>(null)
  const [form, setForm] = useState<RepositoryInput>({
    name: '', url: defaultRepository ?? '', ref: '', path: 'playbooks',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    api.playbookRepositories().then(setSources).catch((e: Error) => setError(e.message))
  }, [])

  async function refresh() {
    setError(null)
    try {
      setSources(await api.playbookRepositories())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function add() {
    setError(null)
    setBusy(true)
    onBusy?.(true)
    try {
      if (!form.url.trim()) throw new Error('Enter a Git repository URL')
      if (!form.name && form.url !== defaultRepository) throw new Error('Enter a unique source name')
      await api.addPlaybookRepository(form)
      setSources(await api.playbookRepositories())
      setForm({ name: '', url: '', ref: '', path: 'playbooks' })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      onBusy?.(false)
    }
  }

  async function pull(source: PlaybookSource) {
    if (source.id === null || !confirm(`Pull latest playbooks for "${source.name}"? This replaces edits and removes files deleted upstream in this source only. A backup is kept. Local files and other sources are not changed.`)) return
    setBusy(true)
    onBusy?.(true)
    setError(null)
    setMessage(null)
    try {
      const result = await api.pullPlaybookRepository(source.id)
      setSources(await api.playbookRepositories())
      setMessage(`Latest playbooks pulled.${result.backup ? ` Backup: /data/${result.backup}.` : ''}${result.legacy_migrated ? ' Legacy root files were kept as local playbooks; use the new source paths for current versions.' : ''}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      onBusy?.(false)
    }
  }

  return (
    <section className="form setup-copy">
      <h2>Playbook sources</h2>
      <p className="muted small">
        All sources are merged into one catalog. Duplicate filenames are kept separately and labeled by source.
        Local playbooks in <code>./playbooks</code> are always included.
        Add more local folders at <code>./playbooks/sources/&lt;name&gt;</code>, or bind-mount a host folder
        at <code>/playbooks/sources/&lt;name&gt;</code> in Compose. Put runnable files at the top level of each source;
        tasks, vars, templates and roles stay alongside them.
      </p>
      {error && <div role="alert" className="alert alert-error">{error}</div>}
      {message && <div role="status" className="alert">{message}</div>}
      {sources ? (
        <ul className="list">
          {sources.map((source) => (
            <li className="card" key={source.id ?? `local:${source.folder}`}>
              <div className="card-title">{source.name} <span className="muted small">({source.kind === 'git' ? 'Git snapshot' : 'local files'})</span></div>
              <div className="muted small selectable">/playbooks{source.folder ? `/${source.folder}` : ''}</div>
              {source.url && (
                <>
                  <a className="small" href={source.url} target="_blank" rel="noreferrer">{source.url}</a>
                  <div className="muted small">Ref: {source.ref || 'bundled / default branch'} · Folder: {source.path || '(repository root)'}</div>
                  <button type="button" className="btn" disabled={busy} onClick={() => pull(source)}>Pull latest</button>
                </>
              )}
            </li>
          ))}
        </ul>
      ) : <p className="muted">Loading sources...</p>}
      <button type="button" className="btn" onClick={refresh} disabled={busy}>Refresh local sources</button>
      <h2>Add Git repository</h2>
      <label>
        Source name
        <input value={form.name ?? ''} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="homelab" autoCapitalize="off" maxLength={64} disabled={busy} />
      </label>
      <label>
        Git repository (HTTPS or local HTTP)
        <input type="url" value={form.url} onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))} placeholder="https://git.example.com/playbooks.git" autoCapitalize="off" disabled={busy} />
      </label>
      <label>
        Branch or tag (empty = default)
        <input value={form.ref} onChange={(e) => setForm((f) => ({ ...f, ref: e.target.value }))} autoCapitalize="off" disabled={busy} />
      </label>
      <label>
        Playbook folder (empty = repository root)
        <input value={form.path} onChange={(e) => setForm((f) => ({ ...f, path: e.target.value }))} autoCapitalize="off" disabled={busy} />
      </label>
      <p className="muted small">
        Repositories must be cloneable without authentication. Imports are additive editable snapshots.
        Pull latest updates only that source from its configured branch/tag, with a backup of edits.
        No Docker image update is needed. Disable schedules using that source before pulling.
        Use HTTPS where possible; HTTP transfers are unencrypted.
        Only import repositories you trust. No automatic dependency installation or Git push occurs.
      </p>
      <button type="button" className="btn btn-primary" onClick={add} disabled={busy}>{busy ? 'Importing...' : 'Add repository'}</button>
    </section>
  )
}
