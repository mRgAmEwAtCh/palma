import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { PlusIcon } from '../components/Icons'
import { toast } from '../components/Toast'
import type { Playbook } from '../types'

export function PlaybooksPage() {
  const navigate = useNavigate()
  const [playbooks, setPlaybooks] = useState<Playbook[] | null>(null)

  useEffect(() => {
    api.playbooks().then(setPlaybooks).catch(toast.error)
  }, [])

  if (!playbooks) return <div className="empty">Loading…</div>

  return (
    <div className="page">
      <p className="muted small">
        Playbooks live in the <code>playbooks/</code> folder. The first play's <code>name</code> is the title, the
        leading <code>#</code> comment is the description and the play <code>vars:</code> are the defaults shown when
        running.
      </p>
      {playbooks.length === 0 && <div className="empty">No playbooks yet.</div>}
      <ul className="list">
        {playbooks.map((p) => (
          <li key={p.path}>
            <Link to={`/playbooks/edit/${encodeURIComponent(p.path)}`} className="card card-link">
              <div className="card-title">{p.title}</div>
              <div className="muted small">{p.path}</div>
              {p.description && <p className="description clamp-2">{p.description}</p>}
            </Link>
          </li>
        ))}
      </ul>
      <button className="fab" onClick={() => navigate('/playbooks/new')} aria-label="New playbook">
        <PlusIcon />
      </button>
    </div>
  )
}
