import { useEffect, useState } from 'react'

type Toast = { id: number; text: string; kind: 'error' | 'info' }
let push: ((t: Omit<Toast, 'id'>) => void) | null = null

export const toast = {
  error: (e: unknown) => push?.({ text: e instanceof Error ? e.message : String(e), kind: 'error' }),
  info: (text: string) => push?.({ text, kind: 'info' }),
}

export function Toaster() {
  const [items, setItems] = useState<Toast[]>([])
  useEffect(() => {
    let next = 1
    push = (t) => {
      const id = next++
      setItems((xs) => [...xs, { ...t, id }])
      setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), t.kind === 'error' ? 6000 : 3000)
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
          onClick={() => setItems((xs) => xs.filter((x) => x.id !== t.id))}
        >
          {t.text}
        </div>
      ))}
    </div>
  )
}
