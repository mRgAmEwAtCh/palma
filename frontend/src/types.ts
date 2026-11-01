export interface ThemeSettings {
  primary: string
  secondary: string
  background: 'graphite' | 'midnight' | 'slate' | 'forest'
}

export interface ThemePreset {
  id: ThemeSettings['background']
  name: string
  bg: string
  surface: string
  surface2: string
  border: string
  text: string
  muted: string
}

export interface ThemeCatalog {
  theme: ThemeSettings
  defaults: ThemeSettings
  presets: ThemePreset[]
}

export interface Host {
  id: number
  name: string
  address: string
  port: number
  ssh_user: string | null
  kind: string
  tags: string[]
  vars: Record<string, unknown>
  enabled: boolean
  notes: string
  source: string
  proxmox_source_id: number | null
  proxmox_node: string | null
  proxmox_vmid: number | null
  proxmox_type: 'lxc' | 'qemu' | null
  proxmox_status: string | null
  os_family: string | null
  os_name: string | null
  os_version: string | null
  last_seen: string | null
  last_error: string | null
  health: HostStatus | null
  health_checked_at: string | null
}

export type StatusLevel = 'ok' | 'warning' | 'critical'

export interface StatusCheck {
  level: StatusLevel
  summary: string
  details: string[]
}

export interface HostStatus {
  level: StatusLevel
  checks: Partial<Record<'docker' | 'disk' | 'updates' | 'units', StatusCheck>> & Record<string, StatusCheck>
}

export type HostInput = Pick<
  Host,
  'name' | 'address' | 'port' | 'ssh_user' | 'kind' | 'tags' | 'vars' | 'enabled' | 'notes'
>

export interface Playbook {
  path: string
  title: string
  description: string
  vars: Record<string, unknown>
}

export type RunStatus = 'pending' | 'running' | 'successful' | 'failed' | 'canceled' | 'error' | 'timeout'

export interface Run {
  id: number
  playbook: string
  status: RunStatus
  check_mode: boolean
  extra_vars: Record<string, unknown>
  host_ids: number[]
  host_names: string[]
  stats: Record<string, Record<string, number>>
  rc: number | null
  triggered_by: string | null
  schedule_id: number | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface ProxmoxSource {
  id: number
  name: string
  url: string
  token_id: string
  verify_ssl: boolean
  default_ssh_user: string
  last_sync: string | null
}

export interface ProxmoxSourceInput {
  name: string
  url: string
  token_id: string
  token_secret?: string
  verify_ssl: boolean
  default_ssh_user: string
}

export interface Guest {
  vmid: number
  type: 'lxc' | 'qemu'
  node: string
  name: string
  status: string
  ip: string | null
  ostype: string | null
  tags: string[]
  manageable: boolean
  note: string | null
  host_id: number | null
}

export interface Me {
  sub: string
  name: string | null
  email: string | null
  groups: string[]
  auth_mode: 'oidc' | 'local' | 'disabled'
}

export interface SystemInfo {
  ssh_key_path: string
  ssh_key_present: boolean
  ssh_public_key: string | null
  default_ssh_user: string
  ansible_version: string | null
  playbooks_dir: string
}

export interface RerunState {
  playbook: string
  host_ids: number[]
  check_mode: boolean
  extra_vars: Record<string, unknown>
}

export interface ToolComponent {
  name: string
  source: 'pypi' | 'galaxy'
  description: string
  installed: string | null
  latest: string | null
  latest_released: string | null
  url: string | null
  status: 'current' | 'outdated' | 'missing' | 'unknown'
  level: 'major' | 'minor' | 'patch' | null
  error: string | null
}

export interface ToolVersions {
  checked_at: string
  update_available: boolean
  components: ToolComponent[]
}

export interface Discovery {
  nodes: string[]
  guests: Guest[]
  warning: string | null
}

export interface KeyDeployResult {
  host_id: number
  name: string
  ok: boolean
  verified: boolean
  message: string
}

export interface ValidationIssue {
  message: string
  source: 'yaml' | 'structure' | 'ansible'
  line: number | null
  column: number | null
}

export interface PlaybookValidation {
  valid: boolean
  errors: ValidationIssue[]
  warnings: ValidationIssue[]
}

export interface ScheduleInput {
  name: string
  playbook: string
  cron: string
  enabled: boolean
  target_host_ids: number[]
  target_tags: string[]
  extra_vars: Record<string, unknown>
}

export interface Schedule extends ScheduleInput {
  id: number
  last_run_id: number | null
  last_run_at: string | null
  last_run_status: RunStatus | null
  next_run_at: string | null
  last_message: string | null
  target_count: number
}

export interface CronPreview {
  valid: boolean
  error: string | null
  next: string[]
}
