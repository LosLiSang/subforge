import { Link } from 'react-router-dom'
import { usePlayer } from '../../context/PlayerContext'

function formatSeconds(sec: number): string {
  if (!sec || isNaN(sec)) return '--:--'
  const total = Math.floor(sec)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const p = (n: number) => String(n).padStart(2, '0')
  return h ? `${h}:${p(m)}:${p(s)}` : `${m}:${p(s)}`
}

export function GlobalPlayerBar() {
  const {
    currentTrack,
    currentItem,
    isPlaying,
    currentTime,
    duration,
    volume,
    floatLyricsOpen,
    togglePlay,
    seek,
    setVolume,
    toggleFloatLyrics,
  } = usePlayer()

  if (!currentTrack) return null

  const coverUrl = currentItem ? `/covers/${currentItem.item_id}` : '/static/subforge-icon.svg'

  return (
    <div id="player-bar" className="player-bar">
      <div className="player-bar-row">
        <Link
          className="player-bar-cover"
          to={`/tracks/${currentTrack.track_id}/play`}
          title="打开播放页"
        >
          <img
            src={coverUrl}
            alt=""
            onError={(e) => ((e.target as HTMLElement).style.display = 'none')}
          />
        </Link>

        <Link
          className="player-bar-title"
          to={`/tracks/${currentTrack.track_id}/play`}
          title={currentTrack.title}
        >
          {currentTrack.title}
        </Link>

        <div className="player-bar-progress-wrap">
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
          <span className="player-bar-time">{formatSeconds(currentTime)}</span>
        </div>

        <button
          type="button"
          className="ghost small player-bar-toggle"
          onClick={togglePlay}
          aria-label={isPlaying ? '暂停' : '播放'}
        >
          {isPlaying ? (
            <svg className="ic-pause" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" style={{ width: 14, height: 14 }}>
              <rect x="6" y="5" width="4" height="14" rx="1" />
              <rect x="14" y="5" width="4" height="14" rx="1" />
            </svg>
          ) : (
            <svg className="ic-play" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" style={{ width: 14, height: 14 }}>
              <path d="M8 5.14v13.72a1 1 0 0 0 1.52.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86A1 1 0 0 0 8 5.14z" />
            </svg>
          )}
        </button>

        <label className="player-bar-volume" title="音量，最高 300%">
          <span aria-hidden="true">🔊</span>
          <input
            type="range"
            min={0}
            max={3.0}
            step={0.01}
            value={volume}
            onChange={(e) => setVolume(parseFloat(e.target.value))}
            title={`${Math.round(volume * 100)}%`}
          />
          <output>{Math.round(volume * 100)}%</output>
        </label>

        <button
          type="button"
          className={`ghost small ${floatLyricsOpen ? 'active' : ''}`}
          onClick={toggleFloatLyrics}
          title="桌面悬浮歌词"
        >
          词
        </button>

        <Link
          to={`/tracks/${currentTrack.track_id}/play`}
          className="ghost small"
          title="打开播放页"
        >
          ⛶
        </Link>
      </div>
    </div>
  )
}
