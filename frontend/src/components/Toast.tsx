import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

type Toast = { id: number; text: ReactNode; kind: 'error' | 'info' | 'warning' }
let push: ((t: Omit<Toast, 'id'>) => void) | null = null

export const toast = {
  error: (e: unknown) => push?.({ text: e instanceof Error ? e.message : String(e), kind: 'error' }),
  info: (text: string) => push?.({ text, kind: 'info' }),
  warning: (text: ReactNode) => push?.({ text, kind: 'warning' }),
}

export function Toaster() {
  const [items, setItems] = useState<Toast[]>([])
  useEffect(() => {
    let next = 1
    push = (t) => {
      const id = next++
      setItems((xs) => [...xs, { ...t, id }])
      if (t.kind !== 'warning') {
        setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), t.kind === 'error' ? 6000 : 3000)
      }
    }
    return () => {
      push = null
    }
  }, [])
  return (
    <div className="toaster" aria-live="polite">
      {items.map((t) => (
        <div
          key={t.id}
          className={`toast toast-${t.kind}`}
          onClick={t.kind === 'warning' ? undefined : () => setItems((xs) => xs.filter((x) => x.id !== t.id))}
        >
          {t.kind === 'warning' ? (
            <>
              <span>{t.text}</span>
              <button
                className="btn btn-small"
                aria-label="Dismiss update notification"
                onClick={() => setItems((xs) => xs.filter((x) => x.id !== t.id))}
              >
                Dismiss
              </button>
            </>
          ) : t.text}
        </div>
      ))}
    </div>
  )
}
