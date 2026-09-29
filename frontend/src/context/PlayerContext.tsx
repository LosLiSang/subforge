import React, { createContext, useContext, useEffect, useRef, useState, useMemo, useCallback } from 'react'
import type { Item, Track, SubtitlesData } from '../types'
import { api } from '../api/client'
import { useFont } from './FontContext'

interface PlayerContextType {
  currentTrack: Track | null
  currentItem: Item | null
  isPlaying: boolean
  currentTime: number
  duration: number
  volume: number
  playbackRate: number
  loop: boolean
  subtitles: SubtitlesData | null
  activeSubtitleIndex: number
  floatLyricsOpen: boolean
  isDesktopPipActive: boolean
  sleepTimerOption: number | 'end-of-track' | null
  sleepTimerRemaining: number | null
  playlist: Track[]
  hasNextTrack: boolean
  hasPrevTrack: boolean
  playNextTrack: () => void
  playPrevTrack: () => void
  setPlaylist: (tracks: Track[]) => void
  playTrack: (item: Item, track: Track, startTime?: number) => void
  togglePlay: () => void
  pause: () => void
  resume: () => void
  seek: (seconds: number) => void
  skipBackward: (seconds?: number) => void
  skipForward: (seconds?: number) => void
  setVolume: (v: number) => void
  setPlaybackRate: (rate: number) => void
  toggleLoop: () => void
  toggleFloatLyrics: () => void
  toggleDesktopPip: () => Promise<void>
  setSleepTimer: (option: number | 'end-of-track' | null) => void
  loadSubtitles: (trackId: string) => Promise<void>
}

function formatSeconds(sec: number): string {
  if (!sec || isNaN(sec)) return '00:00'
  const total = Math.floor(sec)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const p = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${p(m)}:${p(s)}` : `${p(m)}:${p(s)}`
}

const PlayerContext = createContext<PlayerContextType | null>(null)

export function PlayerProvider({ children }: { children: React.ReactNode }) {
  const { fontSettings } = useFont()
  const fontSettingsRef = useRef(fontSettings)

  const [currentTrack, setCurrentTrack] = useState<Track | null>(null)
  const [currentItem, setCurrentItem] = useState<Item | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolumeState] = useState(() => {
    const saved = localStorage.getItem('subforge_volume')
    return saved ? parseFloat(saved) : 1.0
  })
  const [playbackRate, setPlaybackRateState] = useState(1.0)
  const [loop, setLoop] = useState(false)
  const [subtitles, setSubtitles] = useState<SubtitlesData | null>(null)
  const [floatLyricsOpen, setFloatLyricsOpen] = useState(false)
  const [isDesktopPipActive, setIsDesktopPipActive] = useState(false)
  const [isCanvasPipActive, setIsCanvasPipActive] = useState(false)
  const [sleepTimerOption, setSleepTimerOption] = useState<number | 'end-of-track' | null>(null)
  const [sleepTimerRemaining, setSleepTimerRemaining] = useState<number | null>(null)
  const [playlist, setPlaylist] = useState<Track[]>([])

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const gainNodeRef = useRef<GainNode | null>(null)
  const pipWinRef = useRef<Window | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const sleepOptionRef = useRef(sleepTimerOption)
  const currentItemRef = useRef(currentItem)
  const currentTrackRef = useRef(currentTrack)
  const playlistRef = useRef(playlist)
  const loopRef = useRef(loop)
  const playTrackRef = useRef<((item: Item, track: Track, startTime?: number) => void) | null>(null)
  const currentTimeRef = useRef(currentTime)
  const durationRef = useRef(duration)
  const isPlayingRef = useRef(isPlaying)
  const subtitlesRef = useRef(subtitles)
  const activeSubtitleIndexRef = useRef(-1)
  const togglePlayRef = useRef<() => void>(() => {})
  const skipBackwardRef = useRef<(seconds?: number) => void>(() => {})
  const skipForwardRef = useRef<(seconds?: number) => void>(() => {})
  const seekRef = useRef<(seconds: number) => void>(() => {})

  useEffect(() => {
    sleepOptionRef.current = sleepTimerOption
    currentItemRef.current = currentItem
    currentTrackRef.current = currentTrack
    playlistRef.current = playlist
    loopRef.current = loop
    currentTimeRef.current = currentTime
    durationRef.current = duration
    isPlayingRef.current = isPlaying
    subtitlesRef.current = subtitles
    fontSettingsRef.current = fontSettings
  }, [sleepTimerOption, currentItem, currentTrack, playlist, loop, currentTime, duration, isPlaying, subtitles, fontSettings])

  useEffect(() => {
    const audio = new Audio()
    audio.preload = 'metadata'
    audioRef.current = audio

    audio.addEventListener('timeupdate', () => {
      const t = audio.currentTime
      setCurrentTime(t)
      if (currentItemRef.current && currentTrackRef.current && t > 2) {
        try {
          const state = {
            itemId: currentItemRef.current.item_id,
            trackId: currentTrackRef.current.track_id,
            title: currentItemRef.current.title,
            trackTitle: currentTrackRef.current.title,
            rjCode: currentItemRef.current.rj_code,
            currentTime: t,
            duration: audio.duration || 0,
            coverUrl: `/covers/${currentItemRef.current.item_id}`,
            updatedAt: Date.now(),
          }
          localStorage.setItem('subforge_continue_listening', JSON.stringify(state))
        } catch {}
      }
    })
    audio.addEventListener('durationchange', () => {
      if (audio.duration && !isNaN(audio.duration)) {
        setDuration(audio.duration)
      }
    })
    audio.addEventListener('play', () => setIsPlaying(true))
    audio.addEventListener('pause', () => setIsPlaying(false))
    audio.addEventListener('ended', () => {
      if (sleepOptionRef.current === 'end-of-track') {
        setIsPlaying(false)
        setSleepTimerOption(null)
        setSleepTimerRemaining(null)
        return
      }
      if (!loopRef.current && playlistRef.current.length > 0 && currentTrackRef.current && currentItemRef.current) {
        const curIdx = playlistRef.current.findIndex(
          (t) => t.track_id === currentTrackRef.current?.track_id
        )
        if (curIdx >= 0 && curIdx < playlistRef.current.length - 1) {
          const next = playlistRef.current[curIdx + 1]
          playTrackRef.current?.(currentItemRef.current, next, 0)
          return
        }
      }
      setIsPlaying(false)
    })

    return () => {
      audio.pause()
      audio.src = ''
    }
  }, [])

  useEffect(() => {
    const handleUnload = () => {
      if (pipWinRef.current && !pipWinRef.current.closed) {
        pipWinRef.current.close()
      }
    }
    window.addEventListener('beforeunload', handleUnload)
    return () => {
      window.removeEventListener('beforeunload', handleUnload)
      if (pipWinRef.current && !pipWinRef.current.closed) {
        pipWinRef.current.close()
      }
    }
  }, [])

  // Sleep timer countdown
  useEffect(() => {
    if (typeof sleepTimerRemaining !== 'number') return
    if (sleepTimerRemaining <= 0) {
      audioRef.current?.pause()
      setIsPlaying(false)
      setSleepTimerOption(null)
      setSleepTimerRemaining(null)
      return
    }
    const interval = setInterval(() => {
      setSleepTimerRemaining((prev) => {
        if (prev === null || prev <= 1) {
          audioRef.current?.pause()
          setIsPlaying(false)
          setSleepTimerOption(null)
          return null
        }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(interval)
  }, [sleepTimerRemaining])

  const setSleepTimer = useCallback((option: number | 'end-of-track' | null) => {
    setSleepTimerOption(option)
    setSleepTimerRemaining(typeof option === 'number' ? option * 60 : null)
  }, [])

  const setupGainNode = () => {
    if (!audioRef.current) return
    try {
      if (!audioCtxRef.current) {
        const AudioCtx = window.AudioContext || (window as any).webkitAudioContext
        if (!AudioCtx) return
        const ctx = new AudioCtx()
        audioCtxRef.current = ctx
        const source = ctx.createMediaElementSource(audioRef.current)
        const gain = ctx.createGain()
        gain.gain.value = volume
        source.connect(gain)
        gain.connect(ctx.destination)
        gainNodeRef.current = gain
      }
      if (audioCtxRef.current.state === 'suspended') {
        audioCtxRef.current.resume()
      }
    } catch (e) {
      console.warn('Web Audio gain node setup failed:', e)
    }
  }

  const setVolume = (v: number) => {
    const val = Math.max(0, Math.min(3.0, v))
    setVolumeState(val)
    localStorage.setItem('subforge_volume', String(val))
    if (audioRef.current) {
      audioRef.current.volume = Math.min(1.0, val)
    }
    if (gainNodeRef.current) {
      gainNodeRef.current.gain.value = val
    }
  }

  const setPlaybackRate = (rate: number) => {
    setPlaybackRateState(rate)
    if (audioRef.current) {
      audioRef.current.playbackRate = rate
    }
  }

  const toggleLoop = () => {
    setLoop((prev) => {
      const next = !prev
      if (audioRef.current) {
        audioRef.current.loop = next
      }
      return next
    })
  }

  const loadSubtitles = async (trackId: string) => {
    try {
      const data = await api.get<SubtitlesData>(`/api/tracks/${trackId}/subtitles`)
      setSubtitles(data)
    } catch {
      setSubtitles(null)
    }
  }

  const playTrack = useCallback(async (item: Item, track: Track, startTime = 0) => {
    setCurrentItem(item)
    setCurrentTrack(track)
    setSubtitles(null)
    loadSubtitles(track.track_id)

    if (playlistRef.current.length === 0 || currentItemRef.current?.item_id !== item.item_id) {
      api.get<{ tracks: Track[] }>(`/api/items/${item.item_id}`)
        .then((detail) => {
          if (detail.tracks && Array.isArray(detail.tracks)) setPlaylist(detail.tracks)
        })
        .catch(() => {})
    }

    setupGainNode()
    const audio = audioRef.current
    if (audio) {
      audio.src = `/api/tracks/${track.track_id}/media`
      audio.currentTime = startTime
      audio.playbackRate = playbackRate
      audio.loop = loop
      try {
        await audio.play()
        setIsPlaying(true)
      } catch (err) {
        console.warn('Playback play failed:', err)
      }
    }
  }, [playbackRate, loop])

  useEffect(() => {
    playTrackRef.current = playTrack
  }, [playTrack])

  const togglePlay = () => {
    const audio = audioRef.current
    if (!audio) return
    if (isPlaying) {
      audio.pause()
    } else {
      setupGainNode()
      audio.play().catch(console.warn)
    }
  }

  useEffect(() => {
    togglePlayRef.current = togglePlay
    skipBackwardRef.current = skipBackward
    skipForwardRef.current = skipForward
    seekRef.current = seek
  })

  const pause = () => {
    audioRef.current?.pause()
  }

  const resume = () => {
    setupGainNode()
    audioRef.current?.play().catch(console.warn)
  }

  const seek = (seconds: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = seconds
      setCurrentTime(seconds)
    }
  }

  const skipBackward = useCallback((seconds = 5) => {
    if (audioRef.current) {
      const next = Math.max(0, audioRef.current.currentTime - seconds)
      audioRef.current.currentTime = next
      setCurrentTime(next)
    }
  }, [])

  const skipForward = useCallback((seconds = 30) => {
    if (audioRef.current) {
      const max = audioRef.current.duration || 0
      const next = Math.min(max, audioRef.current.currentTime + seconds)
      audioRef.current.currentTime = next
      setCurrentTime(next)
    }
  }, [])

  const currentTrackIndex = useMemo(() => {
    if (!currentTrack || playlist.length === 0) return -1
    return playlist.findIndex((t) => t.track_id === currentTrack.track_id)
  }, [currentTrack, playlist])

  const hasNextTrack = currentTrackIndex >= 0 && currentTrackIndex < playlist.length - 1
  const hasPrevTrack = currentTrackIndex > 0

  const playNextTrack = useCallback(() => {
    if (hasNextTrack && currentItem) {
      playTrack(currentItem, playlist[currentTrackIndex + 1], 0)
    }
  }, [hasNextTrack, currentItem, playlist, currentTrackIndex, playTrack])

  const playPrevTrack = useCallback(() => {
    if (hasPrevTrack && currentItem) {
      playTrack(currentItem, playlist[currentTrackIndex - 1], 0)
    }
  }, [hasPrevTrack, currentItem, playlist, currentTrackIndex, playTrack])

  const toggleFloatLyrics = () => {
    setFloatLyricsOpen((prev) => !prev)
  }

  const activeSubtitleIndex = useMemo(() => {
    if (!subtitles) return -1
    const entries = subtitles.target.length > 0 ? subtitles.target : subtitles.source
    if (!entries || entries.length === 0) return -1
    for (let i = 0; i < entries.length; i++) {
      if (currentTime >= entries[i].start && currentTime <= entries[i].end) {
        return i
      }
    }
    for (let i = entries.length - 1; i >= 0; i--) {
      if (currentTime >= entries[i].start) {
        return i
      }
    }
    return -1
  }, [subtitles, currentTime])

  useEffect(() => {
    activeSubtitleIndexRef.current = activeSubtitleIndex
  }, [activeSubtitleIndex])

  const drawCanvas = useCallback(
    (canvas: HTMLCanvasElement, title: string, timeStr: string, srcText: string, tgtText: string) => {
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.fillStyle = '#080c14'
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      ctx.fillStyle = 'rgba(255, 255, 255, 0.08)'
      ctx.fillRect(16, 34, canvas.width - 32, 1)

      ctx.font = '13px -apple-system, sans-serif'
      ctx.fillStyle = '#94a3b8'
      ctx.textAlign = 'left'
      ctx.fillText(title.length > 32 ? title.slice(0, 32) + '…' : title, 20, 22)

      ctx.textAlign = 'right'
      ctx.font = '12px ui-monospace, monospace'
      ctx.fillStyle = '#64748b'
      ctx.fillText(timeStr, canvas.width - 20, 22)

      const root = document.documentElement
      const cs = getComputedStyle(root)
      const fontJa = cs.getPropertyValue('--font-ja') || '-apple-system, sans-serif'
      const fontZh = cs.getPropertyValue('--font-zh') || fontJa

      ctx.textAlign = 'center'
      if (srcText) {
        ctx.font = `16px ${fontJa}`
        ctx.fillStyle = '#93c5fd'
        ctx.fillText(srcText.length > 40 ? srcText.slice(0, 40) + '…' : srcText, canvas.width / 2, 70)
      }
      if (tgtText) {
        ctx.font = `bold 20px ${fontZh}`
        ctx.fillStyle = '#ffffff'
        ctx.fillText(tgtText.length > 36 ? tgtText.slice(0, 36) + '…' : tgtText, canvas.width / 2, 110)
      }
    },
    []
  )

  const syncPipFonts = useCallback((win: Window, settings?: any) => {
    try {
      const root = document.documentElement
      const cs = getComputedStyle(root)
      const fontSans = cs.getPropertyValue('--font-sans') || '-apple-system, sans-serif'
      const fontJa = cs.getPropertyValue('--font-ja') || fontSans
      const fontZh = cs.getPropertyValue('--font-zh') || fontSans

      const docEl = win.document.documentElement
      docEl.style.setProperty('--font-sans', fontSans)
      docEl.style.setProperty('--font-ja', fontJa)
      docEl.style.setProperty('--font-zh', fontZh)

      if (settings) {
        const baseSubSize = settings.subtitleFontSize || 18
        const baseJaSize = settings.subtitleJaFontSize || 13.5
        const lineHeight = settings.subtitleLineHeight || 1.35

        docEl.style.setProperty('--sub-font-size', `${Math.max(18, Math.round(baseSubSize * 1.15))}px`)
        docEl.style.setProperty('--sub-ja-size', `${Math.max(13, Math.round(baseJaSize * 1.05))}px`)
        docEl.style.setProperty('--sub-line-height', String(lineHeight))
      }
    } catch (err) {
      console.warn('syncPipFonts failed:', err)
    }
  }, [])

  const setupPipWindow = useCallback((win: Window) => {
    win.document.title = 'SubForge 桌面悬浮歌词'
    win.document.documentElement.setAttribute('lang', 'zh-CN')
    win.document.documentElement.setAttribute('translate', 'no')
    win.document.body.setAttribute('translate', 'no')

    const metaNotranslate = win.document.createElement('meta')
    metaNotranslate.name = 'google'
    metaNotranslate.content = 'notranslate'
    win.document.head.appendChild(metaNotranslate)

    // Copy stylesheets & font definitions from parent document
    document.querySelectorAll('link[rel="stylesheet"]').forEach((link) => {
      try {
        win.document.head.appendChild(link.cloneNode(true))
      } catch {}
    })
    document.querySelectorAll('style').forEach((st) => {
      if (st.textContent && (st.textContent.includes('@font-face') || st.textContent.includes('--font-'))) {
        try {
          win.document.head.appendChild(st.cloneNode(true))
        } catch {}
      }
    })

    const style = win.document.createElement('style')
    style.textContent = `
      *, *::before, *::after {
        box-sizing: border-box;
        margin: 0;
        padding: 0;
      }
      html, body {
        width: 100%;
        height: 100%;
        margin: 0;
        padding: 0;
        overflow: hidden;
        user-select: none;
        -webkit-user-select: none;
        font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans", "Microsoft YaHei", sans-serif);
      }
      :root {
        --pip-bg: #090d16;
        --pip-main-fg: #f8fafc;
        --pip-sub-fg: #7dd3fc;
        --pip-chip-bg: rgba(255, 255, 255, 0.08);
        --pip-chip-fg: #cbd5e1;
        --pip-chip-border: rgba(255, 255, 255, 0.15);
      }
      [data-theme="light"] {
        --pip-bg: #ffffff;
        --pip-main-fg: #000000;
        --pip-sub-fg: #0284c7;
        --pip-chip-bg: rgba(0, 0, 0, 0.05);
        --pip-chip-fg: #334155;
        --pip-chip-border: rgba(0, 0, 0, 0.12);
      }
      .pip-container {
        width: 100vw;
        height: 100vh;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        justify-content: center;
        align-items: center;
        background: var(--pip-bg);
        padding: 6px 18px;
        position: relative;
        cursor: pointer;
        transition: background 0.2s ease, color 0.2s ease;
      }
      .pip-hover-tools {
        position: fixed;
        top: 5px;
        right: 8px;
        display: flex;
        gap: 4px;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.16s ease;
        z-index: 10;
      }
      .pip-container:hover .pip-hover-tools {
        opacity: 1;
        pointer-events: auto;
      }
      .pip-chip {
        background: var(--pip-chip-bg);
        color: var(--pip-chip-fg);
        border: 1px solid var(--pip-chip-border);
        border-radius: 9999px;
        padding: 2px 7px;
        font-size: 11px;
        font-weight: 500;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        transition: all 0.12s ease;
        backdrop-filter: blur(8px);
      }
      .pip-chip:hover {
        background: var(--pip-main-fg);
        color: var(--pip-bg);
      }
      .pip-body {
        width: 100%;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        gap: 3px;
      }
      .pip-source {
        font-family: var(--font-ja, var(--font-sans));
        font-size: var(--sub-ja-size, 13.5px);
        color: var(--pip-sub-fg);
        line-height: var(--sub-line-height, 1.35);
        font-weight: 500;
        white-space: pre-wrap;
        word-break: break-word;
        max-width: 96%;
        max-height: 2.8em;
        overflow: hidden;
        transition: all 0.15s ease;
      }
      .pip-source:empty {
        display: none;
      }
      .pip-target {
        font-family: var(--font-zh, var(--font-sans));
        font-size: var(--sub-font-size, 22px);
        font-weight: 750;
        color: var(--pip-main-fg);
        line-height: var(--sub-line-height, 1.35);
        letter-spacing: 0.02em;
        white-space: pre-wrap;
        word-break: break-word;
        max-width: 96%;
        max-height: 2.8em;
        overflow: hidden;
        transition: all 0.15s ease;
      }
      .pip-container.mode-single .pip-source {
        display: none !important;
      }
      .pip-container.mode-single .pip-target {
        font-family: var(--font-zh, var(--font-sans));
        font-size: calc(var(--sub-font-size, 22px) * 1.15);
      }
    `
    win.document.head.appendChild(style)

    syncPipFonts(win, fontSettingsRef.current)

    const savedTheme = localStorage.getItem('subforge.pip_theme') || (document.documentElement.dataset.theme === 'light' ? 'light' : 'dark')
    win.document.documentElement.dataset.theme = savedTheme

    const savedMode = localStorage.getItem('subforge.pip_mode') || 'single'
    const curSub = subtitlesRef.current
    const curIdx = activeSubtitleIndexRef.current
    const initialSrc = curSub && curIdx >= 0 && curSub.source.length > 0 ? curSub.source[curIdx]?.text || '' : ''
    const initialTgt =
      curSub && curIdx >= 0 && curSub.target.length > 0
        ? curSub.target[curIdx]?.text || ''
        : curSub && (curSub.source.length > 0 || curSub.target.length > 0)
        ? '··· 正在播放间隙 ···'
        : currentTrackRef.current
        ? '当前音轨暂无对齐字幕'
        : '等待播放…'

    win.document.body.innerHTML = `
      <div class="pip-container ${savedMode === 'single' ? 'mode-single' : ''}" id="pip-container" translate="no">
        <div class="pip-hover-tools">
          <button type="button" class="pip-chip" id="pip-play" title="播放 / 暂停">${isPlayingRef.current ? '⏸' : '▶'}</button>
          <button type="button" class="pip-chip" id="pip-theme" title="切换深色/浅色底色">🌓</button>
          <button type="button" class="pip-chip" id="pip-mode" title="切换显示：单行 / 双语">${savedMode === 'single' ? '单行' : '双语'}</button>
          <button type="button" class="pip-chip" id="pip-close" title="收回应用">✕</button>
        </div>

        <div class="pip-body" id="pip-body" title="点击播放 / 暂停">
          <div class="pip-source" id="pip-source">${initialSrc}</div>
          <div class="pip-target" id="pip-target">${initialTgt}</div>
        </div>
      </div>
    `

    const pipBody = win.document.getElementById('pip-body')
    if (pipBody) pipBody.onclick = () => togglePlayRef.current?.()

    const playBtn = win.document.getElementById('pip-play')
    if (playBtn) playBtn.onclick = () => togglePlayRef.current?.()

    const themeBtn = win.document.getElementById('pip-theme')
    if (themeBtn) {
      themeBtn.onclick = () => {
        const nextTheme = win.document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'
        win.document.documentElement.dataset.theme = nextTheme
        try {
          localStorage.setItem('subforge.pip_theme', nextTheme)
        } catch {}
      }
    }

    const modeBtn = win.document.getElementById('pip-mode')
    if (modeBtn) {
      modeBtn.onclick = () => {
        const container = win.document.getElementById('pip-container')
        const isSingle = container?.classList.contains('mode-single')
        if (isSingle) {
          container?.classList.remove('mode-single')
          modeBtn.textContent = '双语'
          try {
            localStorage.setItem('subforge.pip_mode', 'both')
          } catch {}
        } else {
          container?.classList.add('mode-single')
          modeBtn.textContent = '单行'
          try {
            localStorage.setItem('subforge.pip_mode', 'single')
          } catch {}
        }
      }
    }

    const closeBtn = win.document.getElementById('pip-close')
    if (closeBtn)
      closeBtn.onclick = () => {
        win.close()
        pipWinRef.current = null
        setIsDesktopPipActive(false)
      }

    win.addEventListener('pagehide', () => {
      pipWinRef.current = null
      setIsDesktopPipActive(false)
    })
  }, [syncPipFonts])

  // Keep open PiP window in sync whenever fontSettings change in Settings
  useEffect(() => {
    if (pipWinRef.current && !pipWinRef.current.closed) {
      syncPipFonts(pipWinRef.current, fontSettings)
    }
  }, [fontSettings, syncPipFonts])

  // Real-time update for Desktop PiP window
  useEffect(() => {
    const srcText =
      subtitles && activeSubtitleIndex >= 0 && subtitles.source.length > 0
        ? subtitles.source[activeSubtitleIndex]?.text || ''
        : ''
    const tgtText =
      subtitles && activeSubtitleIndex >= 0 && subtitles.target.length > 0
        ? subtitles.target[activeSubtitleIndex]?.text || ''
        : subtitles && (subtitles.source.length > 0 || subtitles.target.length > 0)
        ? '··· 正在播放间隙 ···'
        : currentTrack
        ? '当前音轨暂无对齐字幕'
        : '等待播放…'

    // 1. Update Document Picture-in-Picture window if active
    if (pipWinRef.current && !pipWinRef.current.closed) {
      try {
        const doc = pipWinRef.current.document
        const srcEl = doc.getElementById('pip-source')
        if (srcEl && srcEl.textContent !== srcText) srcEl.textContent = srcText

        const tgtEl = doc.getElementById('pip-target')
        if (tgtEl && tgtEl.textContent !== tgtText) tgtEl.textContent = tgtText

        const playBtn = doc.getElementById('pip-play')
        if (playBtn) playBtn.textContent = isPlaying ? '⏸' : '▶'
      } catch (err) {
        console.warn('Failed to update PiP window:', err)
      }
    }

    // 2. Update Canvas Video PiP if active
    if (isCanvasPipActive && canvasRef.current) {
      const timeStr = `${formatSeconds(currentTime)} / ${formatSeconds(duration)}`
      const titleStr = currentTrack ? currentTrack.title : 'SubForge 桌面悬浮歌词'
      drawCanvas(canvasRef.current, titleStr, timeStr, srcText, tgtText)
    }
  }, [currentTime, duration, isPlaying, currentTrack, subtitles, activeSubtitleIndex, isCanvasPipActive, drawCanvas])

  const toggleDesktopPip = useCallback(async () => {
    // If Document PiP is open, close it
    if (pipWinRef.current && !pipWinRef.current.closed) {
      pipWinRef.current.close()
      pipWinRef.current = null
      setIsDesktopPipActive(false)
      return
    }

    // If native Video PiP is open, exit it
    if (document.pictureInPictureElement) {
      await document.exitPictureInPicture().catch(() => {})
      setIsCanvasPipActive(false)
      setIsDesktopPipActive(false)
      return
    }

    // 1. Preferred: Document Picture-in-Picture API (Chrome 116+, Edge 116+)
    // @ts-ignore
    if (typeof window !== 'undefined' && 'documentPictureInPicture' in window && window.documentPictureInPicture?.requestWindow) {
      try {
        // @ts-ignore
        const win: Window = await window.documentPictureInPicture.requestWindow({
          width: 520,
          height: 100,
        })
        pipWinRef.current = win
        setupPipWindow(win)
        setIsDesktopPipActive(true)
        return
      } catch (err) {
        console.warn('Document Picture-in-Picture failed, attempting Canvas Video PiP fallback:', err)
      }
    }

    // 2. Fallback: Canvas Video Picture-in-Picture
    if (canvasRef.current && videoRef.current) {
      try {
        const canvas = canvasRef.current
        const video = videoRef.current
        const initialTime = `${formatSeconds(currentTimeRef.current)} / ${formatSeconds(durationRef.current)}`
        const initialTitle = currentTrackRef.current ? currentTrackRef.current.title : 'SubForge 桌面悬浮歌词'
        const curSub = subtitlesRef.current
        const curIdx = activeSubtitleIndexRef.current
        const initialSrc = curSub && curIdx >= 0 && curSub.source.length > 0 ? curSub.source[curIdx]?.text || '' : ''
        const initialTgt = curSub && curIdx >= 0 && curSub.target.length > 0 ? curSub.target[curIdx]?.text || '' : '··· 正在播放间隙 ···'

        drawCanvas(canvas, initialTitle, initialTime, initialSrc, initialTgt)

        if (!video.srcObject) {
          // @ts-ignore
          video.srcObject = canvas.captureStream(15)
          await video.play().catch(() => {})
        }

        await video.requestPictureInPicture()
        setIsCanvasPipActive(true)
        setIsDesktopPipActive(true)

        video.addEventListener(
          'leavepictureinpicture',
          () => {
            setIsCanvasPipActive(false)
            setIsDesktopPipActive(false)
          },
          { once: true }
        )
        return
      } catch (err: any) {
        console.warn('Canvas Video PiP failed:', err)
      }
    }

    // 3. Fallback: Open in-app floating bar
    setFloatLyricsOpen(true)
    alert('当前浏览器环境未能唤起系统独立画中画小窗，已为您在应用内开启悬浮台本歌词。')
  }, [setupPipWindow, drawCanvas])

  return (
    <PlayerContext.Provider
      value={{
        currentTrack,
        currentItem,
        isPlaying,
        currentTime,
        duration,
        volume,
        playbackRate,
        loop,
        subtitles,
        activeSubtitleIndex,
        floatLyricsOpen,
        isDesktopPipActive,
        sleepTimerOption,
        sleepTimerRemaining,
        playlist,
        hasNextTrack,
        hasPrevTrack,
        playNextTrack,
        playPrevTrack,
        setPlaylist,
        playTrack,
        togglePlay,
        pause,
        resume,
        seek,
        skipBackward,
        skipForward,
        setVolume,
        setPlaybackRate,
        toggleLoop,
        toggleFloatLyrics,
        toggleDesktopPip,
        setSleepTimer,
        loadSubtitles,
      }}
    >
      {children}
      <canvas ref={canvasRef} width={640} height={160} style={{ display: 'none' }} />
      <video
        ref={videoRef}
        playsInline
        muted
        style={{
          position: 'fixed',
          width: 1,
          height: 1,
          bottom: 0,
          right: 0,
          opacity: 0.01,
          pointerEvents: 'none',
        }}
      />
    </PlayerContext.Provider>
  )
}

export function usePlayer() {
  const ctx = useContext(PlayerContext)
  if (!ctx) throw new Error('usePlayer must be used within PlayerProvider')
  return ctx
}
