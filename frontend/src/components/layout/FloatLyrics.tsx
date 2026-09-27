import React from 'react'
import { X } from 'lucide-react'
import { usePlayer } from '../../context/PlayerContext'

export function FloatLyrics() {
  const { floatLyricsOpen, toggleFloatLyrics, subtitles, activeSubtitleIndex } = usePlayer()

  if (!floatLyricsOpen || !subtitles) return null

  const targetLine =
    activeSubtitleIndex >= 0 && subtitles.target.length > 0
      ? subtitles.target[activeSubtitleIndex]?.text
      : null
  const sourceLine =
    activeSubtitleIndex >= 0 && subtitles.source.length > 0
      ? subtitles.source[activeSubtitleIndex]?.text
      : null

  return (
    <div className="float-lyrics-container">
      <div className="float-lyrics-header">
        <span className="text-xs font-semibold text-fg-dim">字幕同步</span>
        <button
          type="button"
          onClick={toggleFloatLyrics}
          className="p-1 hover:text-white"
        >
          <X size={14} />
        </button>
      </div>
      <div className="float-lyrics-body">
        {sourceLine && <p className="source-lyric">{sourceLine}</p>}
        {targetLine && <p className="target-lyric">{targetLine}</p>}
        {!sourceLine && !targetLine && <p className="idle-lyric">暂无对齐字幕</p>}
      </div>
    </div>
  )
}
