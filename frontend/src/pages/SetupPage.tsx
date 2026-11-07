import { useEffect, useState } from 'react'
import { api, emptyProxmoxSource } from '../api'
import { ProxmoxGuide, ProxmoxSourceFields } from '../components/ProxmoxSetup'
import { toast } from '../components/Toast'
import { PlaybookSources } from '../components/PlaybookSources'
import type { ProxmoxSourceInput, SetupStatus } from '../types'

export function SetupPage({ status }: { status: SetupStatus }) {
  const [step, setStep] = useState(status.needs_account ? 0 : 1)
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [publicKey, setPublicKey] = useState<string | null>(null)
  const [source, setSource] = useState<ProxmoxSourceInput>(emptyProxmoxSource)
  const [sourceSaved, setSourceSaved] = useState(false)
  const [warning, setWarning] = useState<string | null>(null)
  const [ready, setReady] = useState(status.needs_account)
  const [busy, setBusy] = useState(false)
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (status.needs_account) return
    Promise.all([api.setupDetails(), api.sources()])
      .then(([details, sources]) => {
        setPublicKey(details.ssh_public_key)
        setSourceSaved(sources.length > 0)
        setReady(true)
      })
      .catch((e: Error) => setError(e.message))
  }, [status.needs_account])

  async function finish() {
    await api.completeSetup()
    window.location.replace('/')
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (step === 0) {
        if (password !== confirmation) throw new Error('Passwords do not match')
        await api.setupAccount(username, password)
        setPassword('')
        setConfirmation('')
        setStep(1)
      } else if (step === 1) {
        const result = await api.setupKey()
        setPublicKey(result.ssh_public_key)
        if (publicKey) setStep(2)
      } else if (step === 2) {
        if (!(await api.playbooks()).length) throw new Error('Add local playbooks or a repository before continuing')
        setStep(3)
      } else if (sourceSaved) {
        await finish()
      } else {
        const discovery = await api.testSource(source)
        await api.createSource(source)
        setSourceSaved(true)
        setSource((s) => ({ ...s, token_secret: '' }))
        setWarning(discovery.warning)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function skip() {
    setBusy(true)
    setError(null)
    try {
      await finish()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }

  async function copyKey() {
    try {
      await navigator.clipboard.writeText(publicKey ?? '')
      toast.info('Public key copied')
    } catch {
      toast.error('Clipboard not available (needs HTTPS); select the public key to copy')
    }
  }

  return (
    <>
      <header className="topbar">
        <div className="brand"><img src="/icon.svg" alt="" /><span className="brand-name">Palma</span><h1>First-run setup</h1></div>
      </header>
      <main>
        <form className="card form" onSubmit={submit}>
          <h2>{['Create administrator account', '1. Controller SSH key', '2. Playbook sources', '3. Proxmox API (optional)'][step]}</h2>
          <p className="muted small">Configuration, keys and playbooks are saved in persistent host directories and survive container recreation.</p>
          {error && <div role="alert" className="alert alert-error">{error}</div>}
          <fieldset disabled={busy || !ready} className="setup-fields form">
            {step === 0 && (
              <>
                <p>Create the local login before configuring Palma. There is no default password.</p>
                <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} pattern="[a-zA-Z0-9_.\-]+" maxLength={64} autoComplete="username" autoCapitalize="off" required /></label>
                <label>Password (at least 12 characters)<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={12} maxLength={256} autoComplete="new-password" required /></label>
                <label>Confirm password<input type="password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} autoComplete="new-password" required /></label>
              </>
            )}
            {step === 1 && (
              <>
                <p>{publicKey ? 'An existing controller key was found. It will be kept, not replaced.' : 'Generate an Ed25519 keypair inside Palma. If a private key was supplied to the container, it is used instead.'}</p>
                {publicKey && (
                  <>
                    <pre className="log wrap selectable">{publicKey}</pre>
                    <button type="button" className="btn" onClick={copyKey}>Copy public key</button>
                  </>
                )}
                <p className="muted small">Add this public key to the SSH user's <code>~/.ssh/authorized_keys</code> on managed hosts, or use Install SSH key after adding/importing hosts. Never share the private key.</p>
              </>
            )}
            {step === 2 && (
              <>
                <p>The default uses the starter playbooks shipped from Palma's source repository, without downloading anything.</p>
                <PlaybookSources defaultRepository={status.default_repository} onBusy={setImporting} />
              </>
            )}
            {step === 3 && (
              <>
                <p>Optional: connect a Proxmox cluster to discover and import guests. You can skip this and manage hosts manually, then add Proxmox later from its tab.</p>
                <ProxmoxGuide open />
                {sourceSaved ? <div className="alert">Proxmox source saved. After finishing, open Proxmox → Discover guests to select hosts for import.</div> : <ProxmoxSourceFields value={source} onChange={setSource} />}
                {warning && <div role="status" className="alert">{warning}</div>}
              </>
            )}
            <div className="row gap-s">
              {step > 1 && <button type="button" className="btn" disabled={importing} onClick={() => setStep(step - 1)}>Back</button>}
              <button className="btn btn-primary grow" type="submit" disabled={importing}>
                {busy ? 'Saving...' : step === 0 ? 'Create account' : step === 1 ? publicKey ? 'Keep key and continue' : 'Generate keypair' : step === 2 ? 'Use all sources and continue' : sourceSaved ? 'Finish setup' : 'Test and save Proxmox'}
              </button>
              {step === 3 && !sourceSaved && <button type="button" className="btn" onClick={skip}>Skip and finish</button>}
            </div>
          </fieldset>
          {!ready && !error && <p className="muted">Loading saved setup...</p>}
        </form>
      </main>
    </>
  )
}
