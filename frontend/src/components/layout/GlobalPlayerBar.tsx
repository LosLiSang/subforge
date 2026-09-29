import React, { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  RotateCcw,
  RotateCw,
  Moon,
  Volume1,
  Volume2,
  VolumeX,
  Maximize2,
  Repeat,
  Check,
  PictureInPicture,
} from 'lucide-react'
import { usePlayer } from '../../context/PlayerContext'

function formatSeconds(sec: number): string {
  if (!sec || isNaN(sec)) return '00:00'
  const total = Math.floor(sec)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const p = (n: number) => String(n).padStart(2, '0')
  return h ? `${h}:${p(m)}:${p(s)}` : `${p(m)}:${p(s)}`
}

export function GlobalPlayerBar() {
  const {
    currentTrack,
    currentItem,
    isPlaying,
    currentTime,
    duration,
    volume,
    playbackRate,
    loop,
    floatLyricsOpen,
    sleepTimerOption,
    sleepTimerRemaining,
    hasPrevTrack,
    hasNextTrack,
    playPrevTrack,
    playNextTrack,
    togglePlay,
    seek,
    skipBackward,
    skipForward,
    setVolume,
    setPlaybackRate,
    toggleLoop,
    toggleFloatLyrics,
    isDesktopPipActive,
    toggleDesktopPip,
    setSleepTimer,
  } = usePlayer()

  const [sleepMenuOpen, setSleepMenuOpen] = useState(false)
  const [prevVolume, setPrevVolume] = useState(1.0)
  const sleepMenuRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (sleepMenuRef.current && !sleepMenuRef.current.contains(e.target as Node)) {
        setSleepMenuOpen(false)
      }
    }
    if (sleepMenuOpen) {
      document.addEventListener('mousedown', handleOutsideClick)
    }
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick)
    }
  }, [sleepMenuOpen])

  if (!currentTrack) return null

  const coverUrl = currentItem ? `/covers/${currentItem.item_id}` : '/covers/default'
  const progressPercent = duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0
  const volumePercent = Math.min(100, Math.round((volume / 3.0) * 100))

  const handleCycleSpeed = () => {
    const rates = [1.0, 1.25, 1.5, 2.0, 0.75]
    const idx = rates.indexOf(playbackRate)
    const next = idx === -1 || idx === rates.length - 1 ? rates[0] : rates[idx + 1]
    setPlaybackRate(next)
  }

  const toggleMute = () => {
    if (volume > 0) {
      setPrevVolume(volume)
      setVolume(0)
    } else {
      setVolume(prevVolume || 1.0)
    }
  }

  const formatRemainingMinutes = (sec: number | null) => {
    if (sec === null) return ''
    const mins = Math.ceil(sec / 60)
    return `${mins}m`
  }

  return (
    <div id="player-bar" className="player-bar">
      {/* Responsive Top Scrubber for Mobile / Small Screens */}
      <div className="player-bar-mobile-progress" style={{ '--progress-pct': `${progressPercent}%` } as React.CSSProperties}>
        <input
          type="range"
          className="player-bar-seek mobile-seek"
          min={0}
          max={duration || 0}
          step={0.1}
          value={currentTime || 0}
          onChange={(e) => seek(parseFloat(e.target.value))}
          aria-label="播放进度"
        />
      </div>

      <div className="player-bar-row">
        {/* Left: Track and Item Meta */}
        <div className="player-bar-info">
          <Link
            className="player-bar-cover"
            to={`/tracks/${currentTrack.track_id}/play`}
            title="打开沉浸式双语播放页"
          >
            <img
              src={coverUrl}
              alt=""
              onError={(e) => ((e.target as HTMLElement).style.display = 'none')}
            />
          </Link>

          <div className="player-bar-meta">
            <Link
              className="player-bar-title"
              to={`/tracks/${currentTrack.track_id}/play`}
              title={currentTrack.title}
            >
              {currentTrack.title}
            </Link>
            {currentItem && (
              <span className="player-bar-subtext" title={currentItem.title}>
                {currentItem.rj_code ? `[${currentItem.rj_code}] ` : ''}
                {currentItem.title}
              </span>
            )}
          </div>
        </div>

        {/* Center: Controls matching Image #3 */}
        <div className="player-bar-center">
          {/* Main 5 Control Buttons */}
          <div className="player-bar-buttons">
            {/* Previous track |◄ */}
            <button
              type="button"
              className="player-bar-btn nav-btn"
              onClick={playPrevTrack}
              disabled={!hasPrevTrack}
              title={hasPrevTrack ? '上一曲' : '没有上一曲'}
              aria-label="上一曲"
            >
              <SkipBack size={17} fill="currentColor" />
            </button>

            {/* Rewind 5s ⟲ 5 */}
            <button
              type="button"
              className="player-bar-btn skip-btn rewind-5"
              onClick={() => skipBackward(5)}
              title="快退 5 秒"
              aria-label="快退 5 秒"
            >
              <RotateCcw size={18} />
              <span className="skip-badge">5</span>
            </button>

            {/* Play / Pause ▶ */}
            <button
              type="button"
              className="player-bar-toggle-round"
              onClick={togglePlay}
              aria-label={isPlaying ? '暂停' : '播放'}
            >
              {isPlaying ? (
                <Pause size={18} fill="currentColor" />
              ) : (
                <Play size={18} fill="currentColor" style={{ marginLeft: 2 }} />
              )}
            </button>

            {/* Forward 30s ⟳ 30 */}
            <button
              type="button"
              className="player-bar-btn skip-btn forward-30"
              onClick={() => skipForward(30)}
              title="快进 30 秒"
              aria-label="快进 30 秒"
            >
              <RotateCw size={18} />
              <span className="skip-badge">30</span>
            </button>

            {/* Next track ►| */}
            <button
              type="button"
              className="player-bar-btn nav-btn"
              onClick={playNextTrack}
              disabled={!hasNextTrack}
              title={hasNextTrack ? '下一曲' : '没有下一曲'}
              aria-label="下一曲"
            >
              <SkipForward size={17} fill="currentColor" />
            </button>
          </div>

          {/* Progress Bar with times in one unified row */}
          <div className="player-bar-progress-wrap">
            <span className="player-bar-time current">{formatSeconds(currentTime)}</span>
            <div
              className="player-slider-track"
              style={{ '--progress-pct': `${progressPercent}%` } as React.CSSProperties}
            >
              <input
                type="range"
                className="player-bar-seek"
                min={0}
                max={duration || 0}
                step={0.1}
                value={currentTime || 0}
                onChange={(e) => seek(parseFloat(e.target.value))}
                aria-label="播放进度"
              />
            </div>
            <span className="player-bar-time total">{formatSeconds(duration)}</span>
          </div>
        </div>

        {/* Right: Volume & Tools matching Image #3 */}
        <div className="player-bar-tools">
          {/* Volume Control Bar matching Image #3 */}
          <div className="player-bar-volume-group" title="音量控制，最高支持 300% 硬件增益">
            <button
              type="button"
              className="volume-mute-btn"
              onClick={toggleMute}
              aria-label={volume === 0 ? '恢复音量' : '静音'}
            >
              {volume === 0 ? <VolumeX size={16} /> : <Volume1 size={16} />}
            </button>
            <div
              className="volume-slider-wrap"
              style={{ '--vol-pct': `${volumePercent}%` } as React.CSSProperties}
            >
              <input
                type="range"
                className="volume-slider"
                min={0}
                max={3.0}
                step={0.01}
                value={volume}
                onChange={(e) => setVolume(parseFloat(e.target.value))}
                title={`音量: ${Math.round(volume * 100)}%`}
                aria-label="音量大小"
              />
            </div>
            <button
              type="button"
              className="volume-mute-btn"
              onClick={() => setVolume(Math.min(3.0, volume + 0.2))}
              title="增大音量"
              aria-label="增大音量"
            >
              <Volume2 size={16} />
            </button>
            <span className="volume-percent">{Math.round(volume * 100)}%</span>
          </div>

          {/* Loop / Repeat */}
          <button
            type="button"
            className={`player-bar-btn ${loop ? 'active' : ''}`}
            onClick={toggleLoop}
            title={loop ? '循环播放：单曲循环' : '循环播放：列表顺序'}
            aria-label="循环播放"
          >
            <Repeat size={15} />
          </button>

          {/* Playback speed */}
          <button
            type="button"
            className="player-speed-btn"
            onClick={handleCycleSpeed}
            title="切换播放倍速"
          >
            {playbackRate}x
          </button>

          {/* Sleep Timer */}
          <div className="sleep-timer-container" ref={sleepMenuRef}>
            <button
              type="button"
              className={`player-bar-btn ${sleepTimerOption ? 'active' : ''}`}
              onClick={() => setSleepMenuOpen((prev) => !prev)}
              title={
                sleepTimerOption
                  ? `睡眠定时器：${typeof sleepTimerOption === 'number' ? formatRemainingMinutes(sleepTimerRemaining) : '本轨结束'}`
                  : '设置睡眠定时器'
              }
            >
              <Moon size={16} />
              {sleepTimerOption && (
                <span className="sleep-badge">
                  {typeof sleepTimerOption === 'number' ? formatRemainingMinutes(sleepTimerRemaining) : '轨'}
                </span>
              )}
            </button>

            {sleepMenuOpen && (
              <div className="sleep-timer-menu">
                <div className="sleep-menu-header">睡眠定时器</div>
                <button
                  type="button"
                  className={sleepTimerOption === null ? 'selected' : ''}
                  onClick={() => {
                    setSleepTimer(null)
                    setSleepMenuOpen(false)
                  }}
                >
                  关闭 {sleepTimerOption === null && <Check size={14} />}
                </button>
                {[15, 30, 45, 60].map((m) => (
                  <button
                    key={m}
                    type="button"
                    className={sleepTimerOption === m ? 'selected' : ''}
                    onClick={() => {
                      setSleepTimer(m)
                      setSleepMenuOpen(false)
                    }}
                  >
                    {m} 分钟 {sleepTimerOption === m && <Check size={14} />}
                  </button>
                ))}
                <button
                  type="button"
                  className={sleepTimerOption === 'end-of-track' ? 'selected' : ''}
                  onClick={() => {
                    setSleepTimer('end-of-track')
                    setSleepMenuOpen(false)
                  }}
                >
                  当前音轨结束时 {sleepTimerOption === 'end-of-track' && <Check size={14} />}
                </button>
              </div>
            )}
          </div>

          {/* Desktop Picture-in-Picture Lyrics */}
          <button
            type="button"
            className={`player-bar-btn ${isDesktopPipActive ? 'active' : ''}`}
            onClick={toggleDesktopPip}
            title={
              isDesktopPipActive
                ? '关闭桌面歌词（独立置顶小窗）'
                : '开启桌面歌词（独立置顶小窗，悬浮在其他应用与桌面之上）'
            }
            aria-label="独立桌面置顶歌词小窗"
          >
            <PictureInPicture size={16} />
          </button>

          {/* In-App Float Lyrics */}
          <button
            type="button"
            className={`player-bar-btn lyrics-btn ${floatLyricsOpen ? 'active' : ''}`}
            onClick={toggleFloatLyrics}
            title="切换应用内悬浮台本歌词条"
            aria-label="应用内悬浮台本歌词条"
          >
            词
          </button>

          {/* Full Player View */}
          <Link
            to={`/tracks/${currentTrack.track_id}/play`}
            className="player-bar-btn"
            title="进入双语沉浸播放页（全屏对照与校对）"
          >
            <Maximize2 size={16} />
          </Link>
        </div>
      </div>
    </div>
  )
}
