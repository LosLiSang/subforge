import React, { createContext, useContext, useEffect, useRef, useState, useMemo } from 'react'
import type { Item, Track, SubtitlesData } from '../types'
import { api } from '../api/client'

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
  playTrack: (item: Item, track: Track, startTime?: number) => void
  togglePlay: () => void
  pause: () => void
  resume: () => void
  seek: (seconds: number) => void
  setVolume: (v: number) => void
  setPlaybackRate: (rate: number) => void
  toggleLoop: () => void
  toggleFloatLyrics: () => void
  loadSubtitles: (trackId: string) => Promise<void>
}

const PlayerContext = createContext<PlayerContextType | null>(null)

export function PlayerProvider({ children }: { children: React.ReactNode }) {
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

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const gainNodeRef = useRef<GainNode | null>(null)

  useEffect(() => {
    const audio = new Audio()
    audio.preload = 'metadata'
    audioRef.current = audio

    audio.addEventListener('timeupdate', () => {
      setCurrentTime(audio.currentTime)
    })
    audio.addEventListener('durationchange', () => {
      if (audio.duration && !isNaN(audio.duration)) {
        setDuration(audio.duration)
      }
    })
    audio.addEventListener('play', () => setIsPlaying(true))
    audio.addEventListener('pause', () => setIsPlaying(false))
    audio.addEventListener('ended', () => {
      setIsPlaying(false)
    })

    return () => {
      audio.pause()
      audio.src = ''
    }
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
    } catch (e) {
      setSubtitles(null)
    }
  }

  const playTrack = async (item: Item, track: Track, startTime = 0) => {
    setCurrentItem(item)
    setCurrentTrack(track)
    setSubtitles(null)
    loadSubtitles(track.track_id)

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
  }

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
        playTrack,
        togglePlay,
        pause,
        resume,
        seek,
        setVolume,
        setPlaybackRate,
        toggleLoop,
        toggleFloatLyrics,
        loadSubtitles,
      }}
    >
      {children}
    </PlayerContext.Provider>
  )
}

export function usePlayer() {
  const ctx = useContext(PlayerContext)
  if (!ctx) throw new Error('usePlayer must be used within PlayerProvider')
  return ctx
}
