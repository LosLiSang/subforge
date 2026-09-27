import React, { useEffect, useRef, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  Play,
  Pause,
  ArrowLeft,
  Edit3,
  Split,
  Merge,
  History,
  RotateCcw,
  Sparkles,
  Volume2,
  Check,
  X,
  Languages,
} from 'lucide-react'
import { api } from '../../api/client'
import type { Track, Item, SubtitlesData, SubtitleEntry } from '../../types'
import { usePlayer } from '../../context/PlayerContext'

function fmtTime(sec: number): string {
  if (!sec || isNaN(sec)) return '00:00'
  const total = Math.floor(sec)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

export function PlayerPage() {
  const { trackId } = useParams<{ trackId: string }>()
  const {
    currentTrack,
    currentItem,
    isPlaying,
    currentTime,
    duration,
    playTrack,
    togglePlay,
    seek,
    activeSubtitleIndex,
    subtitles,
    loadSubtitles,
  } = usePlayer()

  const [track, setTrack] = useState<Track | null>(null)
  const [item, setItem] = useState<Item | null>(null)
  const [mode, setMode] = useState<'bilingual' | 'zh' | 'jp'>('bilingual')
  const [editMode, setEditMode] = useState(false)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editText, setEditText] = useState('')
  const [editTargetText, setEditTargetText] = useState('')

  // Segment Reprocess
  const [reprocessModalOpen, setReprocessModalOpen] = useState(false)
  const [reprocessStart, setReprocessStart] = useState(0)
  const [reprocessEnd, setReprocessEnd] = useState(0)
  const [asrProfiles, setAsrProfiles] = useState<any[]>([])
  const [llmProfiles, setLlmProfiles] = useState<any[]>([])
  const [selectedAsr, setSelectedAsr] = useState('')
  const [selectedLlm, setSelectedLlm] = useState('')
  const [reprocessing, setReprocessing] = useState(false)

  const activeLineRef = useRef<HTMLDivElement | null>(null)
  const subtitleContainerRef = useRef<HTMLDivElement | null>(null)

  // Load track info
  useEffect(() => {
    if (!trackId) return
    const init = async () => {
      try {
        const subsData = await api.get<SubtitlesData>(`/api/tracks/${trackId}/subtitles`)
        // Fetch track metadata
        const itemDetail = await api.get<{ item: Item; tracks: Track[]; available_profiles: any }>(
          `/items/${trackId}/detail` // or find from library
        ).catch(async () => {
          // Fallback scan from items
          const list = await api.get<{ items: Item[] }>('/api/library/items?limit=100')
          for (const it of list.items) {
            const d = await api.get<{ item: Item; tracks: Track[] }>(`/api/items/${it.item_id}`)
            const found = d.tracks.find((t) => t.track_id === trackId)
            if (found) {
              return { item: d.item, tracks: d.tracks, available_profiles: null }
            }
          }
          return null
        })

        if (itemDetail) {
          const t = itemDetail.tracks.find((x) => x.track_id === trackId)
          if (t) {
            setTrack(t)
            setItem(itemDetail.item)
            if (!currentTrack || currentTrack.track_id !== trackId) {
              playTrack(itemDetail.item, t)
            }
          }
        }
        loadSubtitles(trackId)
      } catch (err) {
        console.error('Failed to init player page:', err)
      }
    }
    init()
  }, [trackId])

  // Auto scroll to active line
  useEffect(() => {
    if (activeLineRef.current && !editMode) {
      activeLineRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      })
    }
  }, [activeSubtitleIndex, editMode])

  const handleEditSave = async (index: number) => {
    if (!trackId) return
    try {
      const sourceEntry = subtitles?.source[index]
      const targetEntry = subtitles?.target[index]
      if (targetEntry) {
        await api.post(`/api/tracks/${trackId}/subtitles/edit`, {
          language: 'zh',
          index: index + 1,
          start: targetEntry.start,
          end: targetEntry.end,
          text: editTargetText,
        })
      }
      if (sourceEntry) {
        await api.post(`/api/tracks/${trackId}/subtitles/edit`, {
          language: 'ja',
          index: index + 1,
          start: sourceEntry.start,
          end: sourceEntry.end,
          text: editText,
        })
      }
      setEditingIndex(null)
      loadSubtitles(trackId)
    } catch (err: any) {
      alert('保存字幕失败: ' + err.message)
    }
  }

  const handleOpenReprocess = async (start: number, end: number) => {
    setReprocessStart(start)
    setReprocessEnd(end)
    try {
      const profiles = await api.get<{ asr_profiles: any[]; llm_profiles: any[] }>('/api/profiles')
      setAsrProfiles(profiles.asr_profiles || [])
      setLlmProfiles(profiles.llm_profiles || [])
      if (profiles.asr_profiles?.length > 0) setSelectedAsr(profiles.asr_profiles[0].profile_id)
      if (profiles.llm_profiles?.length > 0) setSelectedLlm(profiles.llm_profiles[0].profile_id)
    } catch {}
    setReprocessModalOpen(true)
  }

  const handleSubmitReprocess = async () => {
    if (!trackId) return
    setReprocessing(true)
    try {
      await api.post(`/api/tracks/${trackId}/segments/reprocess`, {
        start: reprocessStart,
        end: reprocessEnd,
        asr_profile_id: selectedAsr,
        llm_profile_id: selectedLlm,
      })
      setReprocessModalOpen(false)
      alert('片段重识别任务已提交！可在任务中心查看进度并在完成后采纳候选。')
    } catch (err: any) {
      alert('提交片段重跑失败: ' + err.message)
    } finally {
      setReprocessing(false)
    }
  }

  const sourceEntries = subtitles?.source || []
  const targetEntries = subtitles?.target || []
  const maxLen = Math.max(sourceEntries.length, targetEntries.length)
  const currentSourceLine = activeSubtitleIndex >= 0 ? sourceEntries[activeSubtitleIndex]?.text : null
  const currentTargetLine = activeSubtitleIndex >= 0 ? targetEntries[activeSubtitleIndex]?.text : null

  return (
    <>
      <Link className="back-link" to={item ? `/items/${item.item_id}` : '/'}>
        ← 返回作品
      </Link>

      <section className="player">
        <div className="work-hero">
          <div className={`work-hero-cover ${item?.kind === 'rj_work' ? 'cover-rj' : 'cover-stream'}`}>
            <img
              className="work-cover-img"
              src={item?.cover_url}
              alt=""
              onError={(e) => ((e.target as HTMLElement).style.display = 'none')}
            />
            <span className="work-kind">{item?.kind === 'rj_work' ? 'RJ' : 'LIVE'}</span>
          </div>
          <div className="work-hero-info">
            <h1>{track?.title || currentTrack?.title}</h1>
            <div className="work-meta">
              {item?.rj_code && <span className="chip chip-rj">{item.rj_code}</span>}
              <span className="chip chip-tracks">{item?.title || '正在播放'}</span>
            </div>
          </div>
        </div>

        <div className="player-controls">
          <button
            type="button"
            className="play-btn"
            onClick={togglePlay}
            aria-label="播放/暂停"
          >
            {isPlaying ? (
              <svg className="ic-pause" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="5" width="4" height="14" rx="1" />
                <rect x="14" y="5" width="4" height="14" rx="1" />
              </svg>
            ) : (
              <svg className="ic-play" viewBox="0 0 24 24" fill="currentColor">
                <path d="M8 5.14v13.72a1 1 0 0 0 1.52.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86A1 1 0 0 0 8 5.14z" />
              </svg>
            )}
          </button>
          <input
            type="range"
            id="play-seek"
            min={0}
            max={duration || 0}
            step={0.1}
            value={currentTime || 0}
            onChange={(e) => seek(parseFloat(e.target.value))}
            aria-label="进度"
          />
          <span className="player-controls-time">
            {fmtTime(currentTime)} / {fmtTime(duration)}
          </span>
        </div>

        <div className="subtitle-mode" role="group" aria-label="字幕模式">
          <span className="subtitle-label">字幕模式</span>
          <button
            type="button"
            className={mode === 'bilingual' ? 'active' : ''}
            onClick={() => setMode('bilingual')}
          >
            双语
          </button>
          <button
            type="button"
            className={mode === 'jp' ? 'active' : ''}
            onClick={() => setMode('jp')}
          >
            仅原文
          </button>
          <button
            type="button"
            className={mode === 'zh' ? 'active' : ''}
            onClick={() => setMode('zh')}
          >
            仅译文
          </button>
          <span className="subtitle-mode-divider" aria-hidden="true" />
          <button
            type="button"
            className={`ghost small ${editMode ? 'active' : ''}`}
            onClick={() => setEditMode(!editMode)}
          >
            {editMode ? '完成校对' : '✏️ 校对模式'}
          </button>
        </div>

        <div className="subtitles">
          {mode !== 'zh' && (
            <div data-subtitle-panel="source">
              <small>日文原文</small>
              <p>{currentSourceLine || '—'}</p>
            </div>
          )}
          {mode !== 'jp' && (
            <div data-subtitle-panel="target">
              <small>中文翻译</small>
              <p>{currentTargetLine || '—'}</p>
            </div>
          )}
        </div>

        <div style={{ marginTop: 24 }} ref={subtitleContainerRef}>
          <h3 className="dash-h2" style={{ marginBottom: 12 }}>
            全部字幕对齐表 ({maxLen})
          </h3>

          {maxLen === 0 ? (
            <div className="empty" style={{ padding: '40px 0', textAlign: 'center' }}>
              <p>该音轨暂无字幕数据</p>
            </div>
          ) : (
            <div style={{ display: 'grid', gap: 6 }}>
              {Array.from({ length: maxLen }).map((_, idx) => {
                const src = sourceEntries[idx]
                const tgt = targetEntries[idx]
                const isActive = idx === activeSubtitleIndex
                const isEditing = editMode && editingIndex === idx
                const startTime = tgt ? tgt.start : src ? src.start : 0
                const endTime = tgt ? tgt.end : src ? src.end : 0

                return (
                  <div
                    key={idx}
                    ref={isActive ? activeLineRef : null}
                    onClick={() => {
                      if (!editMode) seek(startTime)
                    }}
                    className={`transcript-row ${isActive ? 'active' : ''}`}
                    style={{ cursor: 'pointer', padding: '10px 14px' }}
                  >
                    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', width: '100%' }}>
                      <span className="transcript-time" style={{ fontFamily: 'var(--font-mono)', fontSize: '.84rem' }}>
                        {fmtTime(startTime)}
                      </span>

                      <div style={{ flex: 1, minWidth: 0, display: 'grid', gap: 4 }}>
                        {isEditing ? (
                          <div style={{ display: 'grid', gap: 6 }}>
                            {mode !== 'zh' && (
                              <input
                                type="text"
                                value={editText}
                                onChange={(e) => setEditText(e.target.value)}
                                placeholder="日文原文"
                              />
                            )}
                            {mode !== 'jp' && (
                              <input
                                type="text"
                                value={editTargetText}
                                onChange={(e) => setEditTargetText(e.target.value)}
                                placeholder="中文译文"
                              />
                            )}
                            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
                              <button type="button" className="ghost small" onClick={() => setEditingIndex(null)}>
                                取消
                              </button>
                              <button type="button" className="small" onClick={() => handleEditSave(idx)}>
                                保存
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            {mode !== 'zh' && src && (
                              <div style={{ fontSize: '.9rem', color: 'var(--glass-dim)' }}>
                                {src.text}
                              </div>
                            )}
                            {mode !== 'jp' && tgt && (
                              <div style={{ fontSize: '.95rem', color: 'var(--glass-text)', fontWeight: 500 }}>
                                {tgt.text}
                              </div>
                            )}
                          </>
                        )}
                      </div>

                      {editMode && !isEditing && (
                        <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                          <button
                            type="button"
                            className="ghost small"
                            onClick={(e) => {
                              e.stopPropagation()
                              setEditingIndex(idx)
                              setEditText(src?.text || '')
                              setEditTargetText(tgt?.text || '')
                            }}
                          >
                            编辑
                          </button>
                          <button
                            type="button"
                            className="ghost small"
                            onClick={(e) => {
                              e.stopPropagation()
                              handleOpenReprocess(startTime, endTime)
                            }}
                          >
                            重跑
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </section>

      {/* Segment Reprocess Modal */}
      {reprocessModalOpen && (
        <div className="modal-backdrop">
          <div className="modal-dialog">
            <div className="modal-header">
              <h3 className="modal-title flex items-center gap-2">
                <Sparkles size={18} className="text-accent" />
                疑难音频片段重新识别与翻译
              </h3>
              <button
                type="button"
                onClick={() => setReprocessModalOpen(false)}
                className="modal-close-btn"
              >
                <X size={18} />
              </button>
            </div>

            <div className="modal-body space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-sm font-medium">起始时间 (秒)</label>
                  <input
                    type="number"
                    step={0.1}
                    value={reprocessStart}
                    onChange={(e) => setReprocessStart(parseFloat(e.target.value) || 0)}
                    className="input-text"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium">结束时间 (秒)</label>
                  <input
                    type="number"
                    step={0.1}
                    value={reprocessEnd}
                    onChange={(e) => setReprocessEnd(parseFloat(e.target.value) || 0)}
                    className="input-text"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">精细识别 ASR 模型</label>
                <select
                  value={selectedAsr}
                  onChange={(e) => setSelectedAsr(e.target.value)}
                  className="input-text"
                >
                  {asrProfiles.map((p) => (
                    <option key={p.profile_id} value={p.profile_id}>
                      {p.name} ({p.provider || 'faster-whisper'})
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">翻译大模型 (LLM)</label>
                <select
                  value={selectedLlm}
                  onChange={(e) => setSelectedLlm(e.target.value)}
                  className="input-text"
                >
                  {llmProfiles.map((p) => (
                    <option key={p.profile_id} value={p.profile_id}>
                      {p.name} ({p.model})
                    </option>
                  ))}
                </select>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  onClick={() => setReprocessModalOpen(false)}
                  className="btn btn-secondary"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleSubmitReprocess}
                  disabled={reprocessing}
                  className="btn btn-primary"
                >
                  {reprocessing ? '正在提交...' : '确认发起片段重跑'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
