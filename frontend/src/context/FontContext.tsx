import React, { createContext, useContext, useEffect, useState } from 'react'

export interface FontSettings {
  uiFontSize: number
  fontFamily: string
  customFont: string
  jaFont: string
  zhFont: string
  subtitleFontSize: number
  subtitleJaFontSize: number
  subtitleLineHeight: number
}

interface FontContextType {
  fontSettings: FontSettings
  updateFontSettings: (partial: Partial<FontSettings>) => void
  resetFontSettings: () => void
}

const DEFAULT_SETTINGS: FontSettings = {
  uiFontSize: 14,
  fontFamily: 'system',
  customFont: '',
  jaFont: 'system',
  zhFont: 'system',
  subtitleFontSize: 16,
  subtitleJaFontSize: 13.5,
  subtitleLineHeight: 1.55,
}

const FONT_MAP: Record<string, string> = {
  system: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  source_han: '"Source Han Sans SC", "Source Han Sans CN", "Noto Sans SC", "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", sans-serif',
  yahei: '"Microsoft YaHei", "微软雅黑", "PingFang SC", sans-serif',
  lxgw: '"LXGW WenKai", "霞鹜文楷", "LXGW WenKai Screen", "Kaiti SC", "STKaiti", "楷体", serif',
  pingfang: '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
  yu_gothic: '"Yu Gothic", "YuGothic", "游ゴシック Medium", "游ゴシック体", "游ゴシック", "Meiryo", "メイリオ", "Hiragino Kaku Gothic ProN", sans-serif',
  meiryo: '"Meiryo", "メイリオ", "Hiragino Kaku Gothic ProN", "MS PGothic", sans-serif',
  mincho: '"MS Mincho", "ＭＳ 明朝", "Yu Mincho", "游明朝", "Songti SC", "SimSun", "宋体", serif',
  serif: '"Source Han Serif SC", "Source Han Serif CN", "Noto Serif SC", "Songti SC", "SimSun", "Yu Mincho", "游明朝", Georgia, "Times New Roman", serif',
  mono: '"JetBrains Mono", "Fira Code", "Cascadia Code", "SF Mono", Consolas, "Courier New", monospace',
}

const FontContext = createContext<FontContextType | null>(null)

export function FontProvider({ children }: { children: React.ReactNode }) {
  const [fontSettings, setFontSettings] = useState<FontSettings>(() => {
    try {
      const saved = localStorage.getItem('sf.font_settings')
      if (saved) {
        return { ...DEFAULT_SETTINGS, ...JSON.parse(saved) }
      }
    } catch {}
    return DEFAULT_SETTINGS
  })

  const applyStyles = (settings: FontSettings) => {
    const root = document.documentElement

    // Base font
    const baseFont = settings.customFont.trim()
      ? `"${settings.customFont.trim()}", ${FONT_MAP.system}`
      : FONT_MAP[settings.fontFamily] || FONT_MAP.system
    root.style.setProperty('--font-sans', baseFont)

    // Japanese font
    const jaFont = settings.jaFont !== 'system' && FONT_MAP[settings.jaFont]
      ? FONT_MAP[settings.jaFont]
      : baseFont
    root.style.setProperty('--font-ja', jaFont)

    // Chinese font
    const zhFont = settings.zhFont !== 'system' && FONT_MAP[settings.zhFont]
      ? FONT_MAP[settings.zhFont]
      : baseFont
    root.style.setProperty('--font-zh', zhFont)

    // Sizes and line height
    root.style.setProperty('--ui-font-size', `${settings.uiFontSize}px`)
    root.style.fontSize = `${settings.uiFontSize}px`
    root.style.setProperty('--sub-font-size', `${settings.subtitleFontSize}px`)
    root.style.setProperty('--sub-ja-size', `${settings.subtitleJaFontSize}px`)
    root.style.setProperty('--sub-line-height', String(settings.subtitleLineHeight))
  }

  useEffect(() => {
    applyStyles(fontSettings)
    localStorage.setItem('sf.font_settings', JSON.stringify(fontSettings))
  }, [fontSettings])

  const updateFontSettings = (partial: Partial<FontSettings>) => {
    setFontSettings((prev) => {
      const next = { ...prev, ...partial }
      return next
    })
  }

  const resetFontSettings = () => {
    setFontSettings(DEFAULT_SETTINGS)
  }

  return (
    <FontContext.Provider value={{ fontSettings, updateFontSettings, resetFontSettings }}>
      {children}
    </FontContext.Provider>
  )
}

export function useFont() {
  const ctx = useContext(FontContext)
  if (!ctx) throw new Error('useFont must be used within FontProvider')
  return ctx
}
