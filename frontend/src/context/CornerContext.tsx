import React, { createContext, useContext, useEffect, useState } from 'react'

export type CornerMode = 'rounded' | 'sharp'

export interface CornerSettings {
  global: CornerMode
  cards: CornerMode
  buttons: CornerMode
  library: CornerMode
  settings: CornerMode
  sidebar: CornerMode
  table: CornerMode
}

interface CornerContextType {
  cornerSettings: CornerSettings
  updateCornerSettings: (partial: Partial<CornerSettings>) => void
  setAllCorners: (mode: CornerMode) => void
  resetCornerSettings: () => void
}

const DEFAULT_CORNER_SETTINGS: CornerSettings = {
  global: 'rounded',
  cards: 'rounded',
  buttons: 'rounded',
  library: 'rounded',
  settings: 'rounded',
  sidebar: 'rounded',
  table: 'rounded',
};

const CornerContext = createContext<CornerContextType | null>(null)

const applyCornerStyles = (settings: CornerSettings) => {
  const root = document.documentElement
  root.dataset.cornerGlobal = settings.global
  root.dataset.cornerCards = settings.cards
  root.dataset.cornerButtons = settings.buttons
  root.dataset.cornerLibrary = settings.library
  root.dataset.cornerSettings = settings.settings
  root.dataset.cornerSidebar = settings.sidebar
  root.dataset.cornerTable = settings.table

  if (settings.global === 'sharp') {
    root.style.setProperty('--radius-sm', '0px')
    root.style.setProperty('--radius-md', '0px')
    root.style.setProperty('--radius-lg', '0px')
    root.style.setProperty('--radius-xl', '0px')
  } else {
    root.style.removeProperty('--radius-sm')
    root.style.removeProperty('--radius-md')
    root.style.removeProperty('--radius-lg')
    root.style.removeProperty('--radius-xl')
  }
}

export function CornerProvider({ children }: { children: React.ReactNode }) {
  const [cornerSettings, setCornerSettings] = useState<CornerSettings>(() => {
    try {
      const saved = localStorage.getItem('sf.corner_settings')
      if (saved) {
        const parsed = JSON.parse(saved)
        return { ...DEFAULT_CORNER_SETTINGS, ...parsed }
      }
    } catch {}
    return DEFAULT_CORNER_SETTINGS
  })

  useEffect(() => {
    applyCornerStyles(cornerSettings)
    try {
      localStorage.setItem('sf.corner_settings', JSON.stringify(cornerSettings))
    } catch {}
  }, [cornerSettings])

  const updateCornerSettings = (partial: Partial<CornerSettings>) => {
    setCornerSettings((prev) => {
      const next = { ...prev, ...partial }
      const allSharp =
        next.cards === 'sharp' &&
        next.buttons === 'sharp' &&
        next.library === 'sharp' &&
        next.settings === 'sharp' &&
        next.sidebar === 'sharp'
      const allRounded =
        next.cards === 'rounded' &&
        next.buttons === 'rounded' &&
        next.library === 'rounded' &&
        next.settings === 'rounded' &&
        next.sidebar === 'rounded'
      if (allSharp) next.global = 'sharp'
      else if (allRounded) next.global = 'rounded'
      return next
    })
  }

  const setAllCorners = (mode: CornerMode) => {
    setCornerSettings({
      global: mode,
      cards: mode,
      buttons: mode,
      library: mode,
      settings: mode,
      sidebar: mode,
      table: mode,
    })
  }

  const resetCornerSettings = () => {
    setCornerSettings(DEFAULT_CORNER_SETTINGS)
  }

  return (
    <CornerContext.Provider value={{ cornerSettings, updateCornerSettings, setAllCorners, resetCornerSettings }}>
      {children}
    </CornerContext.Provider>
  )
}

export function useCornerStyle() {
  const ctx = useContext(CornerContext)
  if (!ctx) throw new Error('useCornerStyle must be used within CornerProvider')
  return ctx
}
