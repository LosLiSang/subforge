import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Volume1,
  Maximize2,
  Repeat,
  MessageSquareText,
} from 'lucide-react'
import { usePlayer } from '../../context/PlayerContext'

function formatSeconds(sec: number): string {
  if (!sec || isNaN(sec)) return '00:00'
  const total = Math.floor(sec)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
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
    subtitles,
    activeSubtitleIndex,
    floatLyricsOpen,
    togglePlay,
    seek,
    setVolume,
    setPlaybackRate,
    toggleLoop,
    toggleFloatLyrics,
  } = usePlayer()

  const [rateMenuOpen, setRateMenuOpen] = useState(false)

  if (!currentTrack) {
    return null
  }

  const activeSub =
    activeSubtitleIndex >= 0 && subtitles
      ? subtitles.target[activeSubtitleIndex] || subtitles.source[activeSubtitleIndex]
      : null

  const coverUrl = currentItem ? `/covers/${currentItem.item_id}` : '/static/subforge-icon.svg'

  return (
    <footer className="global-player-bar">
      {/* Left: Track information */}
      <div className="player-left">
        <Link
          to={`/tracks/${currentTrack.track_id}/play`}
          className="player-cover-link"
          title="打开播放页"
        >
          <img
            src={coverUrl}
            alt="cover"
            className="player-cover"
            onError={(e) => {
              ;(e.target as HTMLElement).style.display = 'none'
            }}
          />
        </Link>
        <div className="player-info">
          <Link
            to={`/tracks/${currentTrack.track_id}/play`}
            className="player-title"
            title={currentTrack.title}
          >
            {currentTrack.title}
          </Link>
          <div className="player-sub">
            {currentItem?.title || '未知作品'}
          </div>
        </div>
      </div>

      {/* Center: Playback control & Timeline */}
      <div className="player-center">
        <div className="player-controls">
          <button
            type="button"
            onClick={toggleLoop}
            className={`player-btn ${loop ? 'text-accent active' : ''}`}
            title={loop ? '循环播放：开' : '循环播放：关'}
          >
            <Repeat size={16} />
          </button>

          <button
            type="button"
            onClick={togglePlay}
            className="player-play-btn"
            title={isPlaying ? '暂停' : '播放'}
          >
            {isPlaying ? <Pause size={20} /> : <Play size={20} className="ml-0.5" />}
          </button>

          <div className="relative">
            <button
              type="button"
              onClick={() => setRateMenuOpen(!rateMenuOpen)}
              className="player-btn text-xs font-semibold px-2"
              title="播放倍速"
            >
              {playbackRate}x
            </button>
            {rateMenuOpen && (
              <div className="speed-menu">
                {[0.5, 0.75, 1.0, 1.25, 1.5, 2.0].map((rate) => (
                  <button
                    key={rate}
                    type="button"
                    className={`speed-item ${playbackRate === rate ? 'active' : ''}`}
                    onClick={() => {
                      setPlaybackRate(rate)
                      setRateMenuOpen(false)
                    }}
                  >
                    {rate}x
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="player-progress-bar-row">
          <span className="time-text">{formatSeconds(currentTime)}</span>
          <input
            type="range"
            min={0}
            max={duration || 100}
            step={0.1}
            value={currentTime}
            onChange={(e) => seek(parseFloat(e.target.value))}
            className="progress-slider"
          />
          <span className="time-text">{formatSeconds(duration)}</span>
        </div>

        {activeSub && (
          <div className="player-mini-lyric" title={activeSub.text}>
            {activeSub.text}
          </div>
        )}
      </div>

      {/* Right: Volume & Float Lyric & Fullscreen */}
      <div className="player-right">
        <button
          type="button"
          onClick={toggleFloatLyrics}
          className={`player-btn ${floatLyricsOpen ? 'text-accent active' : ''}`}
          title="桌面悬浮歌词"
        >
          <MessageSquareText size={18} />
        </button>

        <div className="volume-control-group">
          <button
            type="button"
            onClick={() => setVolume(volume === 0 ? 1 : 0)}
            className="player-btn"
            title={`音量: ${Math.round(volume * 100)}%`}
          >
            {volume === 0 ? (
              <VolumeX size={18} />
            ) : volume <= 1 ? (
              <Volume1 size={18} />
            ) : (
              <Volume2 size={18} className="text-accent" />
            )}
          </button>
          <input
            type="range"
            min={0}
            max={3.0}
            step={0.05}
            value={volume}
            onChange={(e) => setVolume(parseFloat(e.target.value))}
            className="volume-slider"
            title={`${Math.round(volume * 100)}%`}
          />
          <span className="volume-label font-mono text-xs">{Math.round(volume * 100)}%</span>
        </div>

        <Link
          to={`/tracks/${currentTrack.track_id}/play`}
          className="player-btn"
          title="转至全屏播放详情"
        >
          <Maximize2 size={18} />
        </Link>
      </div>
    </footer>
  )
}
