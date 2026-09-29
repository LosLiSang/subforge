import React, { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  X,
  GripHorizontal,
  RotateCcw,
  Type,
  PictureInPicture,
} from 'lucide-react'
import { usePlayer } from '../../context/PlayerContext'

function formatSeconds(sec: number): string {
  if (!sec || isNaN(sec)) return '00:00'
  const total = Math.floor(sec)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export function FloatLyrics() {
  const navigate = useNavigate()
  const {
    floatLyricsOpen,
    toggleFloatLyrics,
    isDesktopPipActive,
    toggleDesktopPip,
    subtitles,
    activeSubtitleIndex,
    currentTrack,
    currentItem,
    currentTime,
    duration,
    isPlaying,
    togglePlay,
    skipBackward,
    skipForward,
  } = usePlayer()

  const [position, setPosition] = useState<{ x: number; y: number } | null>(() => {
    try {
      const saved = localStorage.getItem('subforge.float_lyrics_pos')
      if (saved) return JSON.parse(saved)
    } catch {}
    return null
  })

  const [fontSizeLevel, setFontSizeLevel] = useState<'sm' | 'md' | 'lg'>(() => {
    try {
      const s = localStorage.getItem('subforge.float_lyrics_size')
      if (s === 'sm' || s === 'md' || s === 'lg') return s
    } catch {
      return 'md'
    }
    return 'md'
  })

  const containerRef = useRef<HTMLDivElement | null>(null)
  const isDraggingRef = useRef(false)
  const dragStartRef = useRef({ mouseX: 0, mouseY: 0, startX: 0, startY: 0 })

  const handleMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button') || (e.target as HTMLElement).closest('a')) return
    if (!containerRef.current) return

    e.preventDefault()
    isDraggingRef.current = true
    const rect = containerRef.current.getBoundingClientRect()
    dragStartRef.current = {
      mouseX: e.clientX,
      mouseY: e.clientY,
      startX: rect.left,
      startY: rect.top,
    }

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!isDraggingRef.current) return
      const deltaX = moveEvent.clientX - dragStartRef.current.mouseX
      const deltaY = moveEvent.clientY - dragStartRef.current.mouseY
      const newX = Math.max(10, Math.min(window.innerWidth - 300, dragStartRef.current.startX + deltaX))
      const newY = Math.max(10, Math.min(window.innerHeight - 80, dragStartRef.current.startY + deltaY))

      setPosition({ x: newX, y: newY })
    }

    const handleMouseUp = () => {
      isDraggingRef.current = false
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.userSelect = ''
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect()
        try {
          localStorage.setItem('subforge.float_lyrics_pos', JSON.stringify({ x: Math.round(rect.left), y: Math.round(rect.top) }))
        } catch {}
      }
    }

    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }

  const handleResetPos = (e: React.MouseEvent) => {
    e.stopPropagation()
    setPosition(null)
    try {
      localStorage.removeItem('subforge.float_lyrics_pos')
    } catch {}
  }

  const handleCycleFontSize = (e: React.MouseEvent) => {
    e.stopPropagation()
    const next = fontSizeLevel === 'sm' ? 'md' : fontSizeLevel === 'md' ? 'lg' : 'sm'
    setFontSizeLevel(next)
    try {
      localStorage.setItem('subforge.float_lyrics_size', next)
    } catch {}
  }

  if (!floatLyricsOpen) return null

  const targetLine =
    subtitles && activeSubtitleIndex >= 0 && subtitles.target.length > 0
      ? subtitles.target[activeSubtitleIndex]?.text
      : null
  const sourceLine =
    subtitles && activeSubtitleIndex >= 0 && subtitles.source.length > 0
      ? subtitles.source[activeSubtitleIndex]?.text
      : null

  const hasAnySubtitles = subtitles && (subtitles.target.length > 0 || subtitles.source.length > 0)

  const sizeStyles = {
    sm: { source: '12px', target: '14.5px' },
    md: { source: '13.5px', target: '16.5px' },
    lg: { source: '15px', target: '19px' },
  }[fontSizeLevel]

  return (
    <>
    <div
      ref={containerRef}
      className="float-lyrics-container"
      style={
        position
          ? {
              left: `${position.x}px`,
              top: `${position.y}px`,
              bottom: 'auto',
              right: 'auto',
            }
          : undefined
      }
    >
      <div className="float-lyrics-header" onMouseDown={handleMouseDown} title="按住可自由拖拽到屏幕任意位置">
        <div className="float-lyrics-title-wrap">
          <GripHorizontal size={14} style={{ color: 'var(--fg-faint)', cursor: 'grab' }} />
          <span className="float-lyrics-dot" />
          <span className="float-lyrics-title">
            {currentTrack ? currentTrack.title : '双语台本同步'}
          </span>
        </div>

        <div className="float-lyrics-actions">
          {position && (
            <button
              type="button"
              onClick={handleResetPos}
              className="float-lyrics-tool-btn"
              title="复位到默认位置"
            >
              <RotateCcw size={12} />
            </button>
          )}

          <button
            type="button"
            onClick={handleCycleFontSize}
            className="float-lyrics-tool-btn"
            title={`切换字号大小 (当前: ${fontSizeLevel === 'sm' ? '小' : fontSizeLevel === 'md' ? '中' : '大'})`}
          >
            <Type size={12} />
            <span style={{ fontSize: 10, marginLeft: 2 }}>{fontSizeLevel.toUpperCase()}</span>
          </button>

          {/* Desktop Picture-in-Picture Button */}
          <button
            type="button"
            onClick={toggleDesktopPip}
            className={`float-lyrics-tool-btn ${isDesktopPipActive ? 'active' : ''}`}
            title={
              isDesktopPipActive
                ? '关闭独立桌面悬浮小窗'
                : '开启独立桌面歌词小窗（置顶悬浮在其他所有应用之上）'
            }
            aria-label="独立桌面画中画小窗"
          >
            <PictureInPicture size={12} />
          </button>

          <button
            type="button"
            onClick={toggleFloatLyrics}
            className="float-lyrics-close-btn"
            title="关闭悬浮歌词"
            aria-label="关闭悬浮歌词"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {isDesktopPipActive && (
        <div style={{ padding: '4px 0', borderBottom: '1px solid rgba(255,255,255,0.06)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11, color: 'var(--accent-base)' }}>
          <span>已开启独立桌面小窗（置顶在其他软件窗口之上）</span>
          <button
            type="button"
            onClick={toggleDesktopPip}
            style={{ background: 'none', border: 'none', color: 'var(--fg-dim)', cursor: 'pointer', fontSize: 11, textDecoration: 'underline' }}
          >
            收回小窗
          </button>
        </div>
      )}

      <div className="float-lyrics-body">
        {sourceLine && (
          <p className="float-lyrics-source" style={{ fontSize: sizeStyles.source }}>
            {sourceLine}
          </p>
        )}
        {targetLine && (
          <p className="float-lyrics-target" style={{ fontSize: sizeStyles.target }}>
            {targetLine}
          </p>
        )}
        {!sourceLine && !targetLine && hasAnySubtitles && (
          <p className="float-lyrics-idle">··· 正在播放间隙 ···</p>
        )}
        {!hasAnySubtitles && (
          <p className="float-lyrics-idle">
            当前音轨暂无对齐字幕
            {currentItem && (
              <span style={{ display: 'block', fontSize: 11, color: 'var(--fg-dim)', marginTop: 2 }}>
                可在作品详情页点击「处理」生成双语字幕
              </span>
            )}
          </p>
        )}
      </div>
    </div>
    </>
  )
}
