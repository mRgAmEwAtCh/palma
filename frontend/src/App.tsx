import { useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api'
import { CloudIcon, HistoryIcon, PlayIcon, ServerIcon, SettingsIcon } from './components/Icons'
import { toast, Toaster } from './components/Toast'
import { HistoryPage } from './pages/HistoryPage'
import { HostsPage } from './pages/HostsPage'
import { LoginPage } from './pages/LoginPage'
import { PlaybookEditorPage } from './pages/PlaybookEditorPage'
import { PlaybooksPage } from './pages/PlaybooksPage'
import { ProxmoxPage } from './pages/ProxmoxPage'
import { RunDetailPage } from './pages/RunDetailPage'
import { RunPage } from './pages/RunPage'
import { SchedulesPage } from './pages/SchedulesPage'
import { SettingsPage } from './pages/SettingsPage'
import { SetupPage } from './pages/SetupPage'
import type { ApplicationVersion, Me, SetupStatus, ToolVersions } from './types'
import { ThemeProvider } from './theme'

const TABS = [
  { to: '/', label: 'Run', icon: PlayIcon, end: true },
  { to: '/hosts', label: 'Hosts', icon: ServerIcon },
  { to: '/runs', label: 'History', icon: HistoryIcon },
  { to: '/proxmox', label: 'Proxmox', icon: CloudIcon },
  { to: '/settings', label: 'Settings', icon: SettingsIcon },
]

function Title() {
  const path = useLocation().pathname
  if (path.startsWith('/runs/')) return <>Run details</>
  if (path === '/schedules') return <>Schedules</>
  if (path === '/playbooks') return <>Playbooks</>
  if (path === '/playbooks/new') return <>New playbook</>
  if (path.startsWith('/playbooks/')) return <>Edit playbook</>
  const tab = TABS.find((t) => (t.end ? path === t.to : path.startsWith(t.to)))
  return <>{tab?.to === '/' ? 'Run playbook' : (tab?.label ?? 'Palma')}</>
}

function TabBar({ updateAvailable }: { updateAvailable: boolean }) {
  const path = useLocation().pathname
  return (
    <nav className="tabbar">
      {TABS.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            `tab ${isActive || (to === '/runs' && path.startsWith('/schedules')) ? 'active' : ''}`
          }
        >
          <span className="tab-icon">
            <Icon width={22} height={22} />
            {to === '/settings' && updateAvailable && <span className="tab-dot" aria-label="Tool update available" />}
          </span>
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <Startup />
      <Toaster />
    </ThemeProvider>
  )
}

function Startup() {
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.setupStatus().then(setStatus).catch((e: Error) => setError(e.message))
  }, [])
  if (!status) return <div className="empty full">{error ?? 'Loading...'}</div>
  if (status.needs_account) return <SetupPage status={status} />
  return window.location.pathname === '/login' ? <LoginPage /> : <AuthenticatedApp status={status} />
}

function AuthenticatedApp({ status }: { status: SetupStatus }) {
  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [versions, setVersions] = useState<ToolVersions | null>(null)
  const [applicationVersion, setApplicationVersion] = useState<ApplicationVersion | null>(null)

  useEffect(() => {
    api
      .me()
      .then((m) => {
        setMe(m)
        // Cached server-side; only used for the update indicator, so failures are silent.
        if (!status.required) api.versions().then(setVersions).catch(() => undefined)
        if (!status.required) api.applicationVersion().then((version) => {
          setApplicationVersion(version)
          if (version.error) toast.error(version.error)
          if (version.update_available && version.latest) {
            const key = `palma-release-seen:${version.latest}`
            let notify = true
            try {
              notify = !localStorage.getItem(key)
              if (notify) localStorage.setItem(key, 'true')
            } catch (e) {
              toast.error(`Could not save release notification preference: ${String(e)}`)
            }
            if (notify) toast.warning(
              <>
                Palma {version.latest} is available (installed: {version.current}).{' '}
                <a href={version.url} target="_blank" rel="noreferrer">View release notes</a>
              </>,
            )
          }
        }).catch(toast.error)
      })
      .catch((e) => setError(e.message))
  }, [status.required])

  if (!me) {
    return <div className="empty full">{error ?? 'Loading…'}</div>
  }
  if (status.required) return <SetupPage status={status} />

  return (
    <BrowserRouter>
      <header className="topbar">
        <div className="brand">
          <img src="/icon.svg" alt="Palma" />
          <span className="brand-label">
            <span className="brand-name">Palma</span>
            {applicationVersion && (
              <span className="brand-version muted" title={applicationVersion.current}>
                {applicationVersion.current}
              </span>
            )}
          </span>
          <span className="brand-sep">/</span>
          <h1 className="ellipsis">
            <Title />
          </h1>
        </div>
        <span className="muted small ellipsis">{me.name}</span>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<RunPage />} />
          <Route path="/hosts" element={<HostsPage />} />
          <Route path="/runs" element={<HistoryPage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="/schedules" element={<SchedulesPage />} />
          <Route path="/proxmox" element={<ProxmoxPage />} />
          <Route path="/playbooks" element={<PlaybooksPage />} />
          <Route path="/playbooks/new" element={<PlaybookEditorPage key="new" />} />
          <Route path="/playbooks/edit/:name" element={<PlaybookEditorPage />} />
          <Route path="/settings" element={<SettingsPage me={me} versions={versions} onVersions={setVersions} />} />
          <Route path="*" element={<div className="empty">Not found</div>} />
        </Routes>
      </main>
      <TabBar updateAvailable={Boolean(versions?.update_available)} />
    </BrowserRouter>
  )
}
