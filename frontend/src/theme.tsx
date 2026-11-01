import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from './api'
import type { ThemeCatalog, ThemePreset, ThemeSettings } from './types'

export function luminance(color: string): number {
  const channels = [1, 3, 5].map((offset) => {
    const channel = parseInt(color.slice(offset, offset + 2), 16) / 255
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  })
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
}

export function readableAccent(color: string, surface: string): string {
  let result = color
  for (let step = 0; step <= 255; step++) {
    result = '#' + [1, 3, 5].map((offset) => {
      const channel = parseInt(color.slice(offset, offset + 2), 16)
      return Math.round(channel + (255 - channel) * step / 255).toString(16).padStart(2, '0')
    }).join('')
    if ((luminance(result) + 0.05) / (luminance(surface) + 0.05) >= 4.5) break
  }
  return result
}

export function themeTokens(theme: ThemeSettings, preset: ThemePreset): Record<string, string> {
  const onAccent = theme.primary === '#f4a63c' && theme.secondary === '#3fb950'
    ? '#1b1407' : luminance(theme.primary) > 0.179 ? '#000000' : '#ffffff'
  const gradientReadable = Array.from({ length: 33 }, (_, step) => {
    const color = '#' + [1, 3, 5].map((offset) => {
      const start = parseInt(theme.primary.slice(offset, offset + 2), 16)
      const end = parseInt(theme.secondary.slice(offset, offset + 2), 16)
      return Math.round(start + (end - start) * step / 32).toString(16).padStart(2, '0')
    }).join('')
    const light = Math.max(luminance(color), luminance(onAccent))
    const dark = Math.min(luminance(color), luminance(onAccent))
    return (light + 0.05) / (dark + 0.05) >= 4.5
  }).every(Boolean)
  const gradient = `linear-gradient(135deg, ${theme.primary} 0%, ${theme.secondary} 100%)`
  return {
    '--bg': preset.bg,
    '--surface': preset.surface,
    '--surface-2': preset.surface2,
    '--border': preset.border,
    '--text': preset.text,
    '--muted': preset.muted,
    '--accent': theme.primary,
    '--accent-text': readableAccent(theme.primary, preset.surface2),
    '--accent-2': theme.secondary,
    '--accent-soft': `${theme.primary}12`,
    '--on-accent': onAccent,
    '--brand-gradient': gradient,
    '--primary-fill': gradientReadable ? gradient : theme.primary,
    '--brand-gradient-h': `linear-gradient(90deg, ${readableAccent(theme.primary, preset.surface2)} 0%, ${readableAccent(theme.secondary, preset.surface2)} 100%)`,
    '--topbar-bg': `${preset.bg}eb`,
    '--log-bg': preset.id === 'graphite' ? '#050505' : preset.bg,
  }
}

const ThemeContext = createContext<{
  catalog: ThemeCatalog | null
  update: (theme: ThemeSettings) => void
} | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [catalog, setCatalog] = useState<ThemeCatalog | null>(null)
  const [error, setError] = useState<string | null>(null)
  const version = useRef(0)

  function update(theme: ThemeSettings) {
    version.current++
    setCatalog((current) => current ? { ...current, theme } : current)
  }

  useEffect(() => {
    let active = true
    async function refresh() {
      const requestVersion = ++version.current
      try {
        const next = await api.theme()
        if (!active || requestVersion !== version.current) return
        setCatalog((current) => JSON.stringify(current) === JSON.stringify(next) ? current : next)
        setError(null)
      } catch (err) {
        if (active && requestVersion === version.current) {
          setError(`Could not load system theme: ${err instanceof Error ? err.message : String(err)}`)
        }
      }
    }
    void refresh()
    const interval = window.setInterval(() => { if (!document.hidden) void refresh() }, 30000)
    const onFocus = () => { void refresh() }
    window.addEventListener('focus', onFocus)
    return () => {
      active = false
      clearInterval(interval)
      window.removeEventListener('focus', onFocus)
    }
  }, [])

  useEffect(() => {
    if (!catalog) return
    const preset = catalog.presets.find((item) => item.id === catalog.theme.background)
    if (!preset) {
      setError('The system theme has an unknown background preset.')
      return
    }
    const tokens = themeTokens(catalog.theme, preset)
    for (const [key, value] of Object.entries(tokens)) document.documentElement.style.setProperty(key, value)
    const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    if (meta) meta.content = preset.bg
  }, [catalog])

  return (
    <ThemeContext.Provider value={{ catalog, update }}>
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      {catalog || error ? children : <div className="empty full">Loading theme…</div>}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('ThemeProvider is required')
  return context
}
