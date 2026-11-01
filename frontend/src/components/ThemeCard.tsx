import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { themeTokens, useTheme } from '../theme'
import type { ThemeSettings } from '../types'
import { toast } from './Toast'
import { ChevronDownIcon } from './Icons'

export function ThemeCard() {
  const { catalog, update } = useTheme()
  const [draft, setDraft] = useState<ThemeSettings | null>(catalog?.theme ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const previousTheme = useRef(catalog?.theme)

  useEffect(() => {
    if (!catalog) return
    const previous = previousTheme.current
    setDraft((current) => !current || JSON.stringify(current) === JSON.stringify(previous) ? catalog.theme : current)
    previousTheme.current = catalog.theme
  }, [catalog])

  async function save(reset: boolean) {
    if (!draft) return
    setBusy(true)
    setError(null)
    try {
      const saved = reset ? await api.resetTheme() : await api.saveTheme(draft)
      update(saved)
      setDraft(saved)
      toast.info(reset ? 'System theme reset to default' : 'System theme saved for everyone')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (!catalog || !draft) return <section className="card">Theme settings unavailable. Reload to retry.</section>
  const preset = catalog.presets.find((item) => item.id === draft.background)
  return (
    <details className="card collapsible-card">
      <summary className="card-title">
        <span>System theme</span>
        <ChevronDownIcon className="collapse-chevron" width={20} height={20} />
      </summary>
      <div className="form collapsible-content">
      <p className="muted small">Shared by everyone, including the login page. Changes are applied after saving.</p>
      <fieldset className="theme-fields" disabled={busy}>
        <label>
          Primary color
          <input type="color" value={draft.primary} onChange={(event) => setDraft({ ...draft, primary: event.target.value })} />
          <span className="mono small">{draft.primary}</span>
        </label>
        <label>
          Secondary color
          <input type="color" value={draft.secondary} onChange={(event) => setDraft({ ...draft, secondary: event.target.value })} />
          <span className="mono small">{draft.secondary}</span>
        </label>
        <label>
          Background theme
          <select value={draft.background} onChange={(event) => {
            const selected = catalog.presets.find((item) => item.id === event.target.value)
            if (selected) setDraft({ ...draft, background: selected.id })
          }}>
            {catalog.presets.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
      </fieldset>
      {preset && (
        <div className="theme-preview" style={themeTokens(draft, preset)}>
          <strong className="brand-name">Theme preview</strong>
          <p className="muted small">Background, surfaces and brand colors</p>
          <span className="btn btn-primary">Primary</span>
          <span className="theme-secondary">Secondary</span>
        </div>
      )}
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      <div className="row">
        <button className="btn btn-primary" disabled={busy || JSON.stringify(draft) === JSON.stringify(catalog.theme)} onClick={() => void save(false)}>
          {busy ? 'Saving…' : 'Save theme'}
        </button>
        <button className="btn" disabled={busy} onClick={() => void save(true)}>Reset to default</button>
      </div>
      </div>
    </details>
  )
}
