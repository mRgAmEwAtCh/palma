import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError, api } from '../api'
import { BackIcon } from '../components/Icons'
import { toast } from '../components/Toast'
import type { PlaybookValidation, ValidationIssue } from '../types'

const TEMPLATE = `---
# Describe what this playbook does (shown in the app).
# Extra vars: my_option (default false)

- name: My new playbook
  hosts: all
  gather_facts: true
  become: "{{ ansible_user != 'root' }}"
  vars:
    my_option: false

  tasks:
    - name: Example task
      ansible.builtin.debug:
        msg: "Hello from {{ inventory_hostname }} (my_option={{ my_option }})"
`

const SOURCE_LABEL: Record<ValidationIssue['source'], string> = {
  yaml: 'YAML',
  structure: 'Structure',
  ansible: 'Ansible',
}

function normalizeName(raw: string): string {
  const name = raw.trim()
  return name && !/\.ya?ml$/i.test(name) ? `${name}.yml` : name
}

function cursorPosition(text: string, offset: number): { line: number; column: number } {
  const before = text.slice(0, offset).split('\n')
  return { line: before.length, column: before[before.length - 1].length + 1 }
}

export function PlaybookEditorPage() {
  const params = useParams()
  const navigate = useNavigate()
  const existing = params.name ? decodeURIComponent(params.name) : null

  const [name, setName] = useState(existing ?? '')
  const [content, setContent] = useState(existing ? '' : TEMPLATE)
  const [saved, setSaved] = useState(existing ? '' : TEMPLATE)
  const [loading, setLoading] = useState(Boolean(existing))
  const [busy, setBusy] = useState<'validate' | 'save' | 'delete' | null>(null)
  // Validation of a just-created playbook is handed over when switching from /new to the edit route.
  const handedOver = (useLocation().state as { validation?: PlaybookValidation } | null)?.validation ?? null
  const [result, setResult] = useState<PlaybookValidation | null>(handedOver)
  const [pos, setPos] = useState({ line: 1, column: 1 })
  const ref = useRef<HTMLTextAreaElement>(null)

  const dirty = content !== saved

  useEffect(() => {
    if (!existing) return
    api
      .playbookSource(existing)
      .then((text) => {
        setContent(text)
        setSaved(text)
      })
      .catch((e) => {
        toast.error(e)
        navigate('/playbooks')
      })
      .finally(() => setLoading(false))
  }, [existing, navigate])

  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const updatePos = useCallback(() => {
    const el = ref.current
    if (el) setPos(cursorPosition(el.value, el.selectionStart))
  }, [])

  function jumpTo(issue: ValidationIssue) {
    const el = ref.current
    if (!el || !issue.line) return
    const lines = el.value.split('\n')
    const line = Math.min(issue.line, lines.length)
    let offset = lines.slice(0, line - 1).reduce((n, l) => n + l.length + 1, 0)
    offset += Math.max(0, Math.min((issue.column ?? 1) - 1, lines[line - 1].length))
    el.focus()
    el.setSelectionRange(offset, offset)
    const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 20
    el.scrollTop = Math.max(0, (line - 3) * lineHeight)
    updatePos()
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== 'Tab') return
    e.preventDefault()
    const el = e.currentTarget
    const { selectionStart: start, selectionEnd: end } = el
    const next = content.slice(0, start) + '  ' + content.slice(end)
    setContent(next)
    requestAnimationFrame(() => el.setSelectionRange(start + 2, start + 2))
  }

  async function validate() {
    setBusy('validate')
    try {
      const r = await api.validatePlaybook(content, normalizeName(name) || 'playbook.yml')
      setResult(r)
      if (r.valid) toast.info(r.warnings.length ? `Valid, ${r.warnings.length} warning(s)` : 'Playbook is valid')
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy(null)
    }
  }

  async function save() {
    const fileName = normalizeName(name)
    if (!fileName) return toast.error('Enter a file name')
    setBusy('save')
    try {
      const r = await api.savePlaybook(fileName, content, !existing)
      setResult(r.validation)
      setSaved(content)
      toast.info(`Saved ${fileName}`)
      if (!existing) {
        navigate(`/playbooks/edit/${encodeURIComponent(fileName)}`, { replace: true, state: { validation: r.validation } })
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        setResult((e.detail as { validation: PlaybookValidation }).validation)
        toast.error('Not saved: fix the errors first')
      } else {
        toast.error(e)
      }
    } finally {
      setBusy(null)
    }
  }

  async function remove() {
    if (!existing || !confirm(`Delete ${existing}? A copy is kept in the playbook history.`)) return
    setBusy('delete')
    try {
      await api.deletePlaybook(existing)
      toast.info(`Deleted ${existing}`)
      navigate('/playbooks')
    } catch (e) {
      toast.error(e)
      setBusy(null)
    }
  }

  function back() {
    if (dirty && !confirm('Discard unsaved changes?')) return
    navigate('/playbooks')
  }

  if (loading) return <div className="empty">Loading…</div>

  const issues = result ? [...result.errors.map((i) => ({ ...i, error: true })), ...result.warnings.map((i) => ({ ...i, error: false }))] : []

  return (
    <div className="page editor-page">
      <div className="row gap-s">
        <button className="icon-btn" onClick={back} aria-label="Back to playbooks">
          <BackIcon />
        </button>
        {existing ? (
          <h2 className="grow ellipsis">
            {existing}
            {dirty && <span className="muted"> •</span>}
          </h2>
        ) : (
          <input
            className="grow mono"
            placeholder="file-name.yml"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            aria-label="File name"
          />
        )}
      </div>

      <div className="row gap-s editor-toolbar">
        <button className="btn" onClick={validate} disabled={busy !== null}>
          {busy === 'validate' ? 'Checking…' : 'Validate'}
        </button>
        <button className="btn btn-primary grow" onClick={save} disabled={busy !== null || (!dirty && Boolean(existing))}>
          {busy === 'save' ? 'Validating & saving…' : existing ? 'Save' : 'Create'}
        </button>
        {existing && (
          <button className="btn btn-danger" onClick={remove} disabled={busy !== null}>
            Delete
          </button>
        )}
      </div>

      {result && (
        <div className={`validation ${result.valid ? 'valid' : 'invalid'}`}>
          <div className="row">
            <b className="grow">
              {result.valid ? '✓ Valid' : `✗ ${result.errors.length} error${result.errors.length === 1 ? '' : 's'}`}
              {result.warnings.length > 0 && ` · ${result.warnings.length} warning${result.warnings.length === 1 ? '' : 's'}`}
            </b>
            <button className="icon-btn small" onClick={() => setResult(null)} aria-label="Hide validation">
              ✕
            </button>
          </div>
          {issues.length > 0 && (
            <ul className="issues">
              {issues.map((i, n) => (
                <li key={n}>
                  <button className={`issue ${i.error ? 'issue-error' : 'issue-warning'}`} onClick={() => jumpTo(i)} disabled={!i.line}>
                    <span className="issue-meta">
                      {SOURCE_LABEL[i.source]}
                      {i.line ? ` · line ${i.line}${i.column ? `:${i.column}` : ''}` : ''}
                    </span>
                    <span>{i.message}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <textarea
        ref={ref}
        className="code-editor"
        value={content}
        onChange={(e) => {
          setContent(e.target.value)
          updatePos()
        }}
        onKeyDown={onKeyDown}
        onKeyUp={updatePos}
        onClick={updatePos}
        onSelect={updatePos}
        autoCapitalize="off"
        autoCorrect="off"
        autoComplete="off"
        spellCheck={false}
        wrap="off"
        aria-label="Playbook YAML"
      />
      <div className="muted small editor-status">
        Ln {pos.line}, Col {pos.column} · {content.split('\n').length} lines
        {dirty && ' · unsaved changes'}
      </div>
    </div>
  )
}
