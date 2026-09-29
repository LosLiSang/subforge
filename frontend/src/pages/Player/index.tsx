import React, { useEffect, useRef, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  ArrowLeft,
  Sparkles,
  Edit3,
  MapPin,
  ZoomIn,
  ZoomOut,
  Check,
  X,
  Trash2,
  PictureInPicture,
  FileText,
} from 'lucide-react'
import { api } from '../../api/client'
import type { Track, Item } from '../../types'
import { usePlayer } from '../../context/PlayerContext'
import { useFont } from '../../context/FontContext'

function fmtTime(sec: number): string {
  if (!sec || isNaN(sec)) return '00:00'
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

export function PlayerPage() {
  const { trackId } = useParams<{ trackId: string }>()
  const { fontSettings, updateFontSettings } = useFont()
  const {
    currentTrack,
    currentItem,
    subtitles,
    activeSubtitleIndex,
    floatLyricsOpen,
    toggleFloatLyrics,
    isDesktopPipActive,
    toggleDesktopPip,
    playTrack,
    seek,
    loadSubtitles,
  } = usePlayer()

  const [track, setTrack] = useState<Track | null>(null)
  const [item, setItem] = useState<Item | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [displayMode, setDisplayMode] = useState<'bilingual' | 'ja' | 'zh'>('bilingual')
  const [editMode, setEditMode] = useState(false)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editTextJa, setEditTextJa] = useState('')
  const [editTextZh, setEditTextZh] = useState('')

  // Reprocess modal
  const [reprocessOpen, setReprocessOpen] = useState(false)
  const [reprocessStart, setReprocessStart] = useState(0)
  const [reprocessEnd, setReprocessEnd] = useState(10)
  const [asrProfiles, setAsrProfiles] = useState<any[]>([])
  const [llmProfiles, setLlmProfiles] = useState<any[]>([])
  const [selectedAsr, setSelectedAsr] = useState('')
  const [selectedLlm, setSelectedLlm] = useState('')
  const [submittingReprocess, setSubmittingReprocess] = useState(false)

  const activeLineRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!trackId) return
    if (currentTrack?.track_id === trackId && currentItem) {
      setTrack(currentTrack)
      setItem(currentItem)
      setLoading(false)
    } else {
      setLoading(true)
      setError(null)
      api.get<{ track: Track; item: Item }>(`/api/tracks/${trackId}`)
        .then((res) => {
          if (res && res.track && res.item) {
            setTrack(res.track)
            setItem(res.item)
            playTrack(res.item, res.track)
            setLoading(false)
          } else {
            fallbackFromItems()
          }
        })
        .catch(() => {
          fallbackFromItems()
        })
    }
    loadSubtitles(trackId)

    function fallbackFromItems() {
      api.get<any[]>('/api/items')
        .then((items) => {
          if (Array.isArray(items)) {
            const matchedItem = items.find((it) => it.tracks?.some((t: any) => t.track_id === trackId))
            const matchedTrack = matchedItem?.tracks?.find((t: any) => t.track_id === trackId)
            if (matchedItem && matchedTrack) {
              setTrack(matchedTrack)
              setItem(matchedItem)
              playTrack(matchedItem, matchedTrack)
              setLoading(false)
              return
            }
          }
          setError('未找到该音轨元数据')
          setLoading(false)
        })
        .catch((e: any) => {
          setError(e.message || '加载音轨失败')
          setLoading(false)
        })
    }

    Promise.all([
      api.get<{ asr_profiles: any[]; llm_profiles: any[] }>('/api/profiles'),
      api.get<any>('/api/settings').catch(() => null),
    ])
      .then(([res, sets]) => {
        setAsrProfiles(res.asr_profiles || [])
        setLlmProfiles(res.llm_profiles || [])
        const defProc = sets?.default_processing
        if (defProc?.asr_profile_id) {
          setSelectedAsr(defProc.asr_profile_id)
        } else if (res.asr_profiles?.length > 0) {
          setSelectedAsr(res.asr_profiles[0].profile_id)
        }
        if (defProc?.llm_profile_id) {
          setSelectedLlm(defProc.llm_profile_id)
        } else if (res.llm_profiles?.length > 0) {
          setSelectedLlm(res.llm_profiles[0].profile_id)
        }
      })
      .catch(() => {})
  }, [trackId])

  // Smooth scroll active subtitle line into view
  useEffect(() => {
    if (!editMode && activeLineRef.current) {
      activeLineRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      })
    }
  }, [activeSubtitleIndex, editMode])

  const sourceEntries = subtitles?.source || []
  const targetEntries = subtitles?.target || []
  const maxLen = Math.max(sourceEntries.length, targetEntries.length)

  const activeSource = activeSubtitleIndex >= 0 ? sourceEntries[activeSubtitleIndex] : null
  const activeTarget = activeSubtitleIndex >= 0 ? targetEntries[activeSubtitleIndex] : null

  const handleScrollToActive = () => {
    activeLineRef.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    })
  }

  const handleAdjustTime = async (idx: number, delta: number) => {
    if (!trackId) return
    const src = sourceEntries[idx]
    const tgt = targetEntries[idx]
    try {
      if (tgt) {
        await api.post(`/api/tracks/${trackId}/subtitles/edit`, {
          language: 'zh',
          index: idx + 1,
          start: Math.max(0, +(tgt.start + delta).toFixed(2)),
          end: Math.max(0.1, +(tgt.end + delta).toFixed(2)),
          text: tgt.text,
        })
      }
      if (src) {
        await api.post(`/api/tracks/${trackId}/subtitles/edit`, {
          language: 'ja',
          index: idx + 1,
          start: Math.max(0, +(src.start + delta).toFixed(2)),
          end: Math.max(0.1, +(src.end + delta).toFixed(2)),
          text: src.text,
        })
      }
      loadSubtitles(trackId)
    } catch (err: any) {
      alert('微调时间轴失败: ' + err.message)
    }
  }

  const handleDeleteLine = async (idx: number) => {
    if (!trackId) return
    if (!confirm(`确定要删除第 ${idx + 1} 行字幕吗？`)) return
    try {
      const formData = new FormData()
      formData.append('action', 'delete')
      formData.append('index', String(idx + 1))
      await api.postForm(`/api/tracks/${trackId}/subtitles/structure`, formData)
      loadSubtitles(trackId)
    } catch (err: any) {
      alert('删除字幕行失败: ' + err.message)
    }
  }

  const handleSaveLine = async (idx: number) => {
    if (!trackId) return
    const src = sourceEntries[idx]
    const tgt = targetEntries[idx]
    try {
      if (src && editTextJa !== src.text) {
        await api.post(`/api/tracks/${trackId}/subtitles/edit`, {
          language: 'ja',
          index: idx + 1,
          start: src.start,
          end: src.end,
          text: editTextJa,
        })
      }
      if (tgt && editTextZh !== tgt.text) {
        await api.post(`/api/tracks/${trackId}/subtitles/edit`, {
          language: 'zh',
          index: idx + 1,
          start: tgt.start,
          end: tgt.end,
          text: editTextZh,
        })
      }
      setEditingIndex(null)
      loadSubtitles(trackId)
    } catch (err: any) {
      alert('保存修改失败: ' + err.message)
    }
  }

  const handleOpenReprocess = (start: number, end: number) => {
    setReprocessStart(Math.max(0, Math.floor(start)))
    setReprocessEnd(Math.ceil(end))
    setReprocessOpen(true)
  }

  const handleSubmitReprocess = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!trackId) return
    setSubmittingReprocess(true)
    try {
      const formData = new FormData()
      formData.append('start_time', String(reprocessStart))
      formData.append('end_time', String(reprocessEnd))
      formData.append('start_seconds', String(reprocessStart))
      formData.append('end_seconds', String(reprocessEnd))
      if (selectedAsr) {
        formData.append('processor', 'gemini')
        formData.append('asr_profile_id', selectedAsr)
      } else {
        formData.append('processor', 'whisper')
      }
      if (selectedLlm) formData.append('llm_profile_id', selectedLlm)

      await api.postForm(`/api/tracks/${trackId}/segments/reprocess`, formData)
      setReprocessOpen(false)
      alert('重跑任务已提交至任务队列，可在「任务中心」查看处理进度并在就绪后采纳候选。')
    } catch (err: any) {
      alert('提交重跑失败: ' + err.message)
    } finally {
      setSubmittingReprocess(false)
    }
  }

  if (loading && !track) {
    return (
      <div className="player-page-container" style={{ textAlign: 'center', padding: '100px 0', color: 'var(--fg-dim)' }}>
        <p>正在加载双语台本播放器…</p>
      </div>
    )
  }

  if (error && !track && !currentTrack) {
    return (
      <div className="player-page-container" style={{ textAlign: 'center', padding: '80px 0' }}>
        <p style={{ color: 'var(--color-red)', marginBottom: 16 }}>{error}</p>
        <Link to="/" className="btn btn-ghost">
          <ArrowLeft size={16} />
          返回作品库
        </Link>
      </div>
    )
  }

  return (
    <div className="player-page-container">
      {/* Sticky Top Header & Controls Toolbar */}
      <div className="player-sticky-header">
        {/* Navigation */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <Link
            to={item ? `/items/${item.item_id}` : '/'}
            className="btn btn-ghost btn-sm"
          >
            <ArrowLeft size={16} />
            {item ? `返回《${item.title}》` : '返回作品库'}
          </Link>

          {/* Track Title Info */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {item?.rj_code && <span className="chip chip-rj">{item.rj_code}</span>}
            <span style={{ fontWeight: 600, color: 'var(--fg-main)' }}>
              {track?.title || '正在播放'}
            </span>
          </div>
        </div>

        {/* Subtitles Mode & Controls Toolbar */}
        <div
          className="player-toolbar-card"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '12px 18px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            gap: 16,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', gap: 6 }}>
          <button
            type="button"
            className={`btn btn-sm ${displayMode === 'bilingual' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setDisplayMode('bilingual')}
          >
            双语对照
          </button>
          <button
            type="button"
            className={`btn btn-sm ${displayMode === 'ja' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setDisplayMode('ja')}
          >
            仅日文
          </button>
          <button
            type="button"
            className={`btn btn-sm ${displayMode === 'zh' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setDisplayMode('zh')}
          >
            仅中文
          </button>

          <span style={{ width: 1, height: 18, background: 'var(--border-subtle)', margin: '0 4px', alignSelf: 'center' }} />

          <button
            type="button"
            className={`btn btn-sm ${isDesktopPipActive ? 'btn-primary' : 'btn-ghost'}`}
            onClick={toggleDesktopPip}
            title={
              isDesktopPipActive
                ? '关闭独立桌面歌词小窗'
                : '开启独立桌面歌词小窗（置顶悬浮在其他所有应用与桌面之上）'
            }
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <PictureInPicture size={14} />
            {isDesktopPipActive ? '关闭桌面歌词' : '桌面歌词'}
          </button>

          <button
            type="button"
            className={`btn btn-sm ${floatLyricsOpen ? 'btn-primary' : 'btn-ghost'}`}
            onClick={toggleFloatLyrics}
            title={floatLyricsOpen ? '关闭应用内悬浮条' : '开启应用内悬浮条（在页面内自由拖拽）'}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <FileText size={14} />
            悬浮歌词
          </button>
        </div>

        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', background: 'rgba(255, 255, 255, 0.05)', borderRadius: 'var(--radius-sm)', padding: 2 }}>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              style={{ padding: '4px 6px' }}
              onClick={() => updateFontSettings({ subtitleFontSize: Math.max(12, fontSettings.subtitleFontSize - 1) })}
              title="缩小台本字号"
            >
              <ZoomOut size={13} />
            </button>
            <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', padding: '0 4px', color: 'var(--fg-dim)' }}>
              {fontSettings.subtitleFontSize}px
            </span>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              style={{ padding: '4px 6px' }}
              onClick={() => updateFontSettings({ subtitleFontSize: Math.min(26, fontSettings.subtitleFontSize + 1) })}
              title="放大台本字号"
            >
              <ZoomIn size={13} />
            </button>
          </div>

          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={handleScrollToActive}
            title="平滑滚动至当前朗读台本"
          >
            <MapPin size={14} style={{ color: 'var(--accent-base)' }} />
            定位当前句
          </button>

          <button
            type="button"
            className={`btn btn-sm ${editMode ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => {
              setEditMode(!editMode)
              setEditingIndex(null)
            }}
          >
            <Edit3 size={14} />
            {editMode ? '完成校对' : '校对模式'}
          </button>
        </div>
      </div>
      </div>

      {/* Current Active Line Big Preview Box */}
      {(activeSource || activeTarget) && (
        <div
          style={{
            padding: '18px 24px',
            background: 'linear-gradient(135deg, rgba(22, 27, 34, 0.95) 0%, rgba(14, 18, 26, 0.98) 100%)',
            border: '1px solid var(--border-strong)',
            borderLeft: '4px solid var(--accent-base)',
            borderRadius: 'var(--radius-lg)',
            marginBottom: 24,
            boxShadow: 'var(--shadow-md)',
            textAlign: 'center',
          }}
        >
          {displayMode !== 'zh' && activeSource && (
            <div style={{ fontSize: 15, color: '#93c5fd', marginBottom: 6, fontWeight: 500 }}>
              {activeSource.text}
            </div>
          )}
          {displayMode !== 'ja' && activeTarget && (
            <div style={{ fontSize: 18, color: '#ffffff', fontWeight: 700, letterSpacing: '-0.01em' }}>
              {activeTarget.text}
            </div>
          )}
        </div>
      )}

      {/* Bilingual Script Flow */}
      <div className="script-flow-container">
        {maxLen === 0 ? (
          <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-dim)' }}>
            <p>该音轨暂无字幕数据</p>
            <small style={{ color: 'var(--fg-faint)', marginTop: 8, display: 'block' }}>
              可返回作品详情页发起 ASR 语音识别与双语翻译
            </small>
          </div>
        ) : (
          Array.from({ length: maxLen }).map((_, idx) => {
            const src = sourceEntries[idx]
            const tgt = targetEntries[idx]
            const startTime = src?.start ?? tgt?.start ?? 0
            const endTime = src?.end ?? tgt?.end ?? startTime + 5
            const isActive = idx === activeSubtitleIndex
            const isEditing = editingIndex === idx

            return (
              <div
                key={idx}
                ref={isActive ? activeLineRef : null}
                className={`transcript-row ${isActive ? 'active' : ''}`}
                onClick={() => {
                  if (!isEditing) seek(startTime)
                }}
              >
                <span className="transcript-time" title="点击跳转时间">
                  {fmtTime(startTime)}
                </span>

                <div className="script-text-block">
                  {isEditing ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
                      {displayMode !== 'zh' && (
                        <input
                          type="text"
                          className="input-field"
                          value={editTextJa}
                          onChange={(e) => setEditTextJa(e.target.value)}
                          placeholder="日文原文"
                        />
                      )}
                      {displayMode !== 'ja' && (
                        <input
                          type="text"
                          className="input-field"
                          value={editTextZh}
                          onChange={(e) => setEditTextZh(e.target.value)}
                          placeholder="中文译文"
                        />
                      )}
                      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={(e) => {
                            e.stopPropagation()
                            setEditingIndex(null)
                          }}
                        >
                          取消
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm btn-primary"
                          onClick={(e) => {
                            e.stopPropagation()
                            handleSaveLine(idx)
                          }}
                        >
                          <Check size={14} />
                          保存
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      {displayMode !== 'zh' && src && (
                        <div className="script-source-text">{src.text}</div>
                      )}
                      {displayMode !== 'ja' && tgt && (
                        <div className="script-target-text">{tgt.text}</div>
                      )}
                    </>
                  )}
                </div>

                {!isEditing && (
                  <div className="script-line-tools" onClick={(e) => e.stopPropagation()}>
                    {editMode ? (
                      <>
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          style={{ padding: '2px 6px', fontSize: 11, fontFamily: 'var(--font-mono)' }}
                          onClick={() => handleAdjustTime(idx, -0.5)}
                          title="时间轴提前 0.5 秒"
                        >
                          -0.5s
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          style={{ padding: '2px 6px', fontSize: 11, fontFamily: 'var(--font-mono)' }}
                          onClick={() => handleAdjustTime(idx, 0.5)}
                          title="时间轴延后 0.5 秒"
                        >
                          +0.5s
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={() => {
                            setEditingIndex(idx)
                            setEditTextJa(src?.text || '')
                            setEditTextZh(tgt?.text || '')
                          }}
                          title="编辑该行文字"
                        >
                          <Edit3 size={13} />
                          校对
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={() => handleDeleteLine(idx)}
                          title="删除该行台本（可用于清理无声音多余条目）"
                          style={{ color: '#f87171' }}
                        >
                          <Trash2 size={13} />
                          删除
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        onClick={() => handleOpenReprocess(startTime, endTime)}
                        title="重跑本句 ASR / 翻译"
                      >
                        <Sparkles size={13} />
                        重跑
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>

      {/* Segment Reprocess Modal */}
      {reprocessOpen && (
        <div className="modal-overlay" onClick={() => setReprocessOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">局部音频疑难句重跑</h3>
              <button
                type="button"
                className="btn btn-ghost btn-circle"
                onClick={() => setReprocessOpen(false)}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSubmitReprocess}>
              <div className="modal-body">
                <p style={{ fontSize: 13, color: 'var(--fg-dim)' }}>
                  截取该时间片段单独发起 ASR 转写与 LLM 翻译，完成后将自动替换对应台本行。
                </p>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                      起始时间 (秒)
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      className="input-field"
                      value={reprocessStart}
                      onChange={(e) => setReprocessStart(parseFloat(e.target.value) || 0)}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                      结束时间 (秒)
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      className="input-field"
                      value={reprocessEnd}
                      onChange={(e) => setReprocessEnd(parseFloat(e.target.value) || 0)}
                    />
                  </div>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                    ASR 引擎
                  </label>
                  <select
                    className="select-field"
                    style={{ width: '100%' }}
                    value={selectedAsr}
                    onChange={(e) => setSelectedAsr(e.target.value)}
                  >
                    {asrProfiles.map((p) => (
                      <option key={p.profile_id} value={p.profile_id}>
                        {p.name} ({p.provider} - {p.model})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                    LLM 翻译模型
                  </label>
                  <select
                    className="select-field"
                    style={{ width: '100%' }}
                    value={selectedLlm}
                    onChange={(e) => setSelectedLlm(e.target.value)}
                  >
                    {llmProfiles.map((p) => (
                      <option key={p.profile_id} value={p.profile_id}>
                        {p.name} ({p.provider} - {p.model})
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setReprocessOpen(false)}
                  disabled={submittingReprocess}
                >
                  取消
                </button>
                <button type="submit" className="btn btn-primary" disabled={submittingReprocess}>
                  <Sparkles size={14} />
                  {submittingReprocess ? '正在提交…' : '提交重跑'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
