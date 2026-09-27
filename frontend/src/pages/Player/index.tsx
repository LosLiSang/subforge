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

function formatSeconds(sec: number): string {
  if (!sec || isNaN(sec)) return '00:00.0'
  const m = Math.floor(sec / 60)
  const s = (sec % 60).toFixed(1)
  return `${m.toString().padStart(2, '0')}:${parseFloat(s) < 10 ? '0' : ''}${s}`
}

export function PlayerPage() {
  const { trackId } = useParams<{ trackId: string }>()
  const {
    currentTrack,
    currentItem,
    isPlaying,
    currentTime,
    duration,
    volume,
    playTrack,
    togglePlay,
    seek,
    setVolume,
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

  // History / Snapshots
  const [snapshots, setSnapshots] = useState<string[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)

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

  const handleRestoreSnapshot = async (snapshot: string) => {
    if (!trackId || !confirm(`确认回滚至快照 ${snapshot} 吗？`)) return
    try {
      await api.post(`/api/tracks/${trackId}/subtitles/restore/${snapshot}`)
      setHistoryOpen(false)
      loadSubtitles(trackId)
    } catch (err: any) {
      alert('恢复快照失败: ' + err.message)
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

  return (
    <div className="player-fullscreen-page">
      {/* Top Navbar */}
      <div className="player-top-nav">
        <Link
          to={item ? `/items/${item.item_id}` : '/'}
          className="text-fg-dim hover:text-white flex items-center gap-1.5 text-sm"
        >
          <ArrowLeft size={16} /> 返回作品详情
        </Link>

        <div className="flex-1 text-center min-w-0 px-4">
          <h2 className="text-base font-semibold text-white truncate">
            {track?.title || currentTrack?.title || '正在播放'}
          </h2>
          <div className="text-xs text-fg-dim">{item?.title || currentItem?.title}</div>
        </div>

        {/* Subtitle mode controls */}
        <div className="flex items-center gap-2">
          <div className="flex rounded bg-panel-2 border border-line p-0.5 text-xs">
            <button
              type="button"
              onClick={() => setMode('bilingual')}
              className={`px-2 py-1 rounded ${mode === 'bilingual' ? 'bg-accent text-white font-medium' : 'text-fg-dim'}`}
            >
              双语对照
            </button>
            <button
              type="button"
              onClick={() => setMode('zh')}
              className={`px-2 py-1 rounded ${mode === 'zh' ? 'bg-accent text-white font-medium' : 'text-fg-dim'}`}
            >
              仅中文
            </button>
            <button
              type="button"
              onClick={() => setMode('jp')}
              className={`px-2 py-1 rounded ${mode === 'jp' ? 'bg-accent text-white font-medium' : 'text-fg-dim'}`}
            >
              仅日文
            </button>
          </div>

          <button
            type="button"
            onClick={() => setEditMode(!editMode)}
            className={`btn btn-secondary btn-sm flex items-center gap-1 ${editMode ? 'text-accent border-accent' : ''}`}
            title="开启/退出字幕校对与编辑模式"
          >
            <Edit3 size={14} />
            {editMode ? '完成校对' : '字幕校对'}
          </button>
        </div>
      </div>

      {/* Main Subtitles Surface */}
      <div className="player-subtitles-viewport" ref={subtitleContainerRef}>
        {maxLen === 0 ? (
          <div className="text-center py-28 space-y-3">
            <Languages size={40} className="mx-auto text-fg-faint" />
            <p className="text-fg-dim text-sm">该音轨暂无字幕</p>
            <p className="text-fg-faint text-xs">可返回作品详情页发起 ASR 语音识别与翻译流水线</p>
          </div>
        ) : (
          <div className="subtitles-list">
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
                  className={`subtitle-row ${isActive ? 'active' : ''} ${isEditing ? 'editing' : ''}`}
                >
                  {/* Timestamp & Index */}
                  <div className="subtitle-time-col">
                    <span className="font-mono text-xs text-fg-faint">
                      {formatSeconds(startTime)}
                    </span>
                    {editMode && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          handleOpenReprocess(startTime, endTime)
                        }}
                        className="reprocess-chip"
                        title="重跑该片段"
                      >
                        <Sparkles size={11} /> 重跑
                      </button>
                    )}
                  </div>

                  {/* Text display / editing */}
                  <div className="subtitle-content-col">
                    {isEditing ? (
                      <div className="space-y-2 w-full py-1">
                        {mode !== 'zh' && (
                          <input
                            type="text"
                            value={editText}
                            onChange={(e) => setEditText(e.target.value)}
                            className="input-text text-sm py-1 font-sans"
                            placeholder="日文原文"
                          />
                        )}
                        {mode !== 'jp' && (
                          <input
                            type="text"
                            value={editTargetText}
                            onChange={(e) => setEditTargetText(e.target.value)}
                            className="input-text text-sm py-1 font-sans text-accent"
                            placeholder="中文译文"
                          />
                        )}
                        <div className="flex gap-2 justify-end">
                          <button
                            type="button"
                            onClick={() => setEditingIndex(null)}
                            className="btn btn-secondary btn-sm"
                          >
                            取消
                          </button>
                          <button
                            type="button"
                            onClick={() => handleEditSave(idx)}
                            className="btn btn-primary btn-sm flex items-center gap-1"
                          >
                            <Check size={14} /> 保存
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-1">
                        {mode !== 'zh' && src && (
                          <p className="subtitle-jp-line">{src.text}</p>
                        )}
                        {mode !== 'jp' && tgt && (
                          <p className="subtitle-zh-line">{tgt.text}</p>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Row edit button */}
                  {editMode && !isEditing && (
                    <div className="subtitle-action-col">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          setEditingIndex(idx)
                          setEditText(src?.text || '')
                          setEditTargetText(tgt?.text || '')
                        }}
                        className="p-1 text-fg-dim hover:text-white"
                        title="编辑该行"
                      >
                        <Edit3 size={15} />
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

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
    </div>
  )
}
