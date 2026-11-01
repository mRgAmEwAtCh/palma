import type {
  Discovery,
  Host,
  HostInput,
  KeyDeployResult,
  Me,
  Playbook,
  PlaybookValidation,
  ProxmoxSource,
  ProxmoxSourceInput,
  Run,
  Schedule,
  ScheduleInput,
  CronPreview,
  SystemInfo,
  ToolVersions,
  ThemeCatalog,
  ThemeSettings,
} from './types'

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    credentials: 'same-origin',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401 && url.startsWith('/api/')) {
    window.location.href = '/auth/login'
    throw new ApiError(401, 'Not authenticated')
  }
  if (!res.ok) {
    let message = res.statusText
    let detail: unknown
    try {
      const data = await res.json()
      detail = data.detail
      message =
        typeof detail === 'string'
          ? detail
          : (detail as { message?: string } | undefined)?.message ?? JSON.stringify(detail)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message, detail)
  }
  if (res.status === 204) return undefined as T
  const type = res.headers.get('content-type') ?? ''
  return (type.includes('json') ? res.json() : res.text()) as Promise<T>
}

export const api = {
  theme: () => request<ThemeCatalog>('GET', '/api/theme'),
  saveTheme: (theme: ThemeSettings) => request<ThemeSettings>('PUT', '/api/theme', theme),
  resetTheme: () => request<ThemeSettings>('DELETE', '/api/theme'),
  me: () => request<Me>('GET', '/api/me'),
  localLogin: (username: string, password: string) =>
    request<{ ok: boolean }>('POST', '/auth/local', { username, password }),
  system: () => request<SystemInfo>('GET', '/api/system'),
  versions: (refresh = false) => request<ToolVersions>('GET', `/api/system/versions${refresh ? '?refresh=true' : ''}`),

  hosts: () => request<Host[]>('GET', '/api/hosts'),
  createHost: (h: HostInput) => request<Host>('POST', '/api/hosts', h),
  updateHost: (id: number, h: Partial<HostInput>) => request<Host>('PATCH', `/api/hosts/${id}`, h),
  deleteHost: (id: number) => request<void>('DELETE', `/api/hosts/${id}`),

  playbooks: () => request<Playbook[]>('GET', '/api/playbooks'),
  playbookSource: (path: string) =>
    request<string>('GET', `/api/playbooks/source?path=${encodeURIComponent(path)}`),
  validatePlaybook: (content: string, name: string) =>
    request<PlaybookValidation>('POST', '/api/playbooks/validate', { content, name }),
  savePlaybook: (name: string, content: string, create: boolean) =>
    request<{ saved: string; validation: PlaybookValidation }>('PUT', '/api/playbooks/file', { name, content, create }),
  deletePlaybook: (name: string) => request<void>('DELETE', `/api/playbooks/file?name=${encodeURIComponent(name)}`),

  runs: () => request<Run[]>('GET', '/api/runs'),
  run: (id: number) => request<Run>('GET', `/api/runs/${id}`),
  runLog: (id: number) => request<string>('GET', `/api/runs/${id}/log`),
  createRun: (body: {
    playbook: string
    host_ids: number[]
    check_mode: boolean
    extra_vars: Record<string, unknown>
  }) => request<Run>('POST', '/api/runs', body),
  cancelRun: (id: number) => request<void>('POST', `/api/runs/${id}/cancel`),

  deployKey: (body: {
    host_ids: number[]
    method: 'ssh' | 'proxmox'
    username: string
    password: string
    ensure_sshd: boolean
  }) => request<{ results: KeyDeployResult[] }>('POST', '/api/keys/deploy', body),

  schedules: () => request<Schedule[]>('GET', '/api/schedules'),
  createSchedule: (body: ScheduleInput) => request<Schedule>('POST', '/api/schedules', body),
  updateSchedule: (id: number, body: Partial<ScheduleInput>) => request<Schedule>('PATCH', `/api/schedules/${id}`, body),
  deleteSchedule: (id: number) => request<void>('DELETE', `/api/schedules/${id}`),
  runSchedule: (id: number) => request<{ run_id: number }>('POST', `/api/schedules/${id}/run`),
  cronPreview: (cron: string) => request<CronPreview>('GET', `/api/schedules/preview?cron=${encodeURIComponent(cron)}`),

  sources: () => request<ProxmoxSource[]>('GET', '/api/proxmox/sources'),
  createSource: (s: ProxmoxSourceInput) => request<ProxmoxSource>('POST', '/api/proxmox/sources', s),
  updateSource: (id: number, s: Partial<ProxmoxSourceInput>) =>
    request<ProxmoxSource>('PATCH', `/api/proxmox/sources/${id}`, s),
  deleteSource: (id: number) => request<void>('DELETE', `/api/proxmox/sources/${id}`),
  discover: (id: number) => request<Discovery>('GET', `/api/proxmox/sources/${id}/discover`),
  importContainers: (id: number, vmids: number[]) =>
    request<{ created: number; updated: number; skipped: { vmid: number; name: string; reason: string }[] }>(
      'POST',
      `/api/proxmox/sources/${id}/import`,
      { vmids },
    ),
}
