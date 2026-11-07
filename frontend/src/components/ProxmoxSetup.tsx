import type { ProxmoxSourceInput } from '../types'
import { ChevronDownIcon } from './Icons'

export function ProxmoxGuide({ open = false }: { open?: boolean }) {
  return (
    <details className="card collapsible-card setup-copy" open={open}>
      <summary className="card-title">
        <span>Step-by-step Proxmox requirements</span>
        <ChevronDownIcon className="collapse-chevron" width={20} height={20} />
      </summary>
      <ol className="small collapsible-content">
        <li>Open the Proxmox web UI as an administrator. Under Datacenter → Permissions → Users, add a dedicated user such as <code>palma@pve</code>.</li>
        <li>Under Permissions → Add → User Permission, select path <code>/</code>, that user, role <b>PVEAuditor</b> and enable Propagate.</li>
        <li>Under Permissions → API Tokens, add a token for that user (for example <code>palma</code>). Keep Privilege Separation enabled. Copy the secret now; Proxmox only displays it once.</li>
        <li>Under Permissions → Add → API Token Permission, grant that token <b>PVEAuditor</b> on <code>/</code> with Propagate. With privilege separation, both the user and token need permissions.</li>
        <li>Enter the full token ID (<code>palma@pve!palma</code>), secret, and a reachable API URL such as <code>https://192.168.1.2:8006</code>. Allow Palma to reach TCP port 8006. Enable TLS verification when the certificate is trusted; self-signed certificates require leaving it off.</li>
        <li>For VM IP discovery, enable QEMU Guest Agent in VM Options and install/start <code>qemu-guest-agent</code> in the guest. PVE 9 needs <code>VM.GuestAgent.Audit</code> (included in PVEAuditor); PVE 8 needs an additional role with <code>VM.Monitor</code>, granted to both user and token. LXC guests need a running interface or a configured static IP.</li>
        <li>Guests need SSH access and Python (use the Bootstrap playbook for Python). Non-root users need passwordless sudo for playbooks using become. API access does not install the controller key: after import, use <b>Install SSH key</b>. The Proxmox-node method uses a separate root SSH login, not the API token.</li>
      </ol>
    </details>
  )
}

export function ProxmoxSourceFields({
  value, onChange, editing = false,
}: {
  value: ProxmoxSourceInput
  onChange: (value: ProxmoxSourceInput) => void
  editing?: boolean
}) {
  const set = <K extends keyof ProxmoxSourceInput>(key: K, v: ProxmoxSourceInput[K]) =>
    onChange({ ...value, [key]: v })
  return (
    <>
      <label>
        Name
        <input value={value.name} onChange={(e) => set('name', e.target.value)} placeholder="pve1" autoCapitalize="off" required />
      </label>
      <label>
        API URL
        <input value={value.url} onChange={(e) => set('url', e.target.value)} placeholder="https://192.168.1.2:8006" inputMode="url" autoCapitalize="off" required />
      </label>
      <label>
        Token ID
        <input value={value.token_id} onChange={(e) => set('token_id', e.target.value)} placeholder="palma@pve!palma" autoCapitalize="off" required />
      </label>
      <label>
        Token secret {editing && <span className="muted">(leave empty to keep)</span>}
        <input type="password" value={value.token_secret ?? ''} onChange={(e) => set('token_secret', e.target.value)} autoComplete="off" required={!editing} />
      </label>
      <label>
        Default SSH user for imported hosts
        <input value={value.default_ssh_user} onChange={(e) => set('default_ssh_user', e.target.value)} autoCapitalize="off" required />
      </label>
      <label className="switch">
        <input type="checkbox" checked={value.verify_ssl} onChange={(e) => set('verify_ssl', e.target.checked)} />
        <span>Verify TLS certificate</span>
      </label>
    </>
  )
}
