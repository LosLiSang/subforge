import React, { useState, useEffect, useRef, useMemo } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Play,
  Pause,
  Sparkles,
  Edit3,
  Image,
  Trash2,
  ExternalLink,
  Download,
  FileText,
  Check,
  X,
  Plus,
  RotateCcw,
  RefreshCw,
  Globe,
} from 'lucide-react'
import { api } from '../../api/client'
import type { ItemDetailData, Track, Creator } from '../../types'
import { usePlayer } from '../../context/PlayerContext'

const STORAGE_KEY_COL_WIDTHS = 'subforge.item_detail.col_widths'

interface ColumnWidths {
  index: number
  play: number
  title: number
  duration: number
  status: number
  size: number
  actions: number
}

const DEFAULT_COL_WIDTHS: ColumnWidths = {
  index: 44,
  play: 48,
  title: 360,
  duration: 90,
  status: 110,
  size: 96,
  actions: 250,
}

const MIN_COL_WIDTHS: Record<keyof ColumnWidths, number> = {
  index: 36,
  play: 44,
  title: 140,
  duration: 70,
  status: 80,
  size: 75,
  actions: 180,
}

function loadSavedColWidths(): ColumnWidths {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_COL_WIDTHS)
    if (saved) {
      const parsed = JSON.parse(saved)
      return { ...DEFAULT_COL_WIDTHS, ...parsed }
    }
  } catch {}
  return { ...DEFAULT_COL_WIDTHS }
}

function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const idx = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, idx)).toFixed(1)} ${units[idx]}`
}

export function ItemDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { currentTrack, isPlaying, playTrack, togglePlay } = usePlayer()

  const [data, setData] = useState<ItemDetailData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Resizable table columns
  const [colWidths, setColWidths] = useState<ColumnWidths>(loadSavedColWidths)
  const [activeResizingCol, setActiveResizingCol] = useState<string | null>(null)
  const colWidthsRef = useRef(colWidths)
  colWidthsRef.current = colWidths

  const saveColWidths = (widths: ColumnWidths) => {
    try {
      localStorage.setItem(STORAGE_KEY_COL_WIDTHS, JSON.stringify(widths))
    } catch {}
  }

  const handleResetColWidths = () => {
    setColWidths({ ...DEFAULT_COL_WIDTHS })
    colWidthsRef.current = { ...DEFAULT_COL_WIDTHS }
    try {
      localStorage.removeItem(STORAGE_KEY_COL_WIDTHS)
    } catch {}
  }

  const handleResetSingleCol = (key: keyof ColumnWidths) => {
    setColWidths((prev) => {
      const next = { ...prev, [key]: DEFAULT_COL_WIDTHS[key] }
      colWidthsRef.current = next
      saveColWidths(next)
      return next
    })
  }

  const startResizing = (colKey: keyof ColumnWidths, e: React.MouseEvent, fromLeft = false) => {
    e.preventDefault()
    e.stopPropagation()
    setActiveResizingCol(colKey)
    const th = e.currentTarget.closest('th') as HTMLElement | null
    const startWidth = th ? th.offsetWidth : colWidthsRef.current[colKey]
    const startX = e.clientX

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const delta = fromLeft ? startX - moveEvent.clientX : moveEvent.clientX - startX
      const minWidth = MIN_COL_WIDTHS[colKey] || 40
      const newWidth = Math.max(minWidth, Math.round(startWidth + delta))
      setColWidths((prev) => {
        const next = { ...prev, [colKey]: newWidth }
        colWidthsRef.current = next
        return next
      })
    }

    const handleMouseUp = () => {
      setActiveResizingCol(null)
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      saveColWidths(colWidthsRef.current)
    }

    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }

  const hasCustomWidths = Object.keys(DEFAULT_COL_WIDTHS).some(
    (k) => colWidths[k as keyof ColumnWidths] !== DEFAULT_COL_WIDTHS[k as keyof ColumnWidths]
  )

  const totalColWidth =
    colWidths.index +
    colWidths.play +
    colWidths.title +
    colWidths.duration +
    colWidths.status +
    colWidths.size +
    colWidths.actions

  // Modals
  const [editOpen, setEditOpen] = useState(false)
  const [processOpen, setProcessOpen] = useState(false)
  const [selectedTrackId, setSelectedTrackId] = useState<string | null>(null)

  // Edit form state
  const [editTitle, setEditTitle] = useState('')
  const [editOrigTitle, setEditOrigTitle] = useState('')
  const [editRjCode, setEditRjCode] = useState('')
  const [editTags, setEditTags] = useState('')
  const [editCreatorIds, setEditCreatorIds] = useState<string[]>([])
  const [allCreators, setAllCreators] = useState<Creator[]>([])
  const [submittingEdit, setSubmittingEdit] = useState(false)
  const [syncingDlsite, setSyncingDlsite] = useState(false)

  // Enhanced Tag Editing State
  const [editTagsList, setEditTagsList] = useState<string[]>([])
  const [newTagInput, setNewTagInput] = useState('')
  const [libraryTags, setLibraryTags] = useState<string[]>([])
  const [rawTagMode, setRawTagMode] = useState(false)

  // Enhanced Creator Adding State
  const [showAddCreator, setShowAddCreator] = useState(false)
  const [newCreatorName, setNewCreatorName] = useState('')
  const [newCreatorKind, setNewCreatorKind] = useState<'voice_actor' | 'circle'>('voice_actor')
  const [creatingCreator, setCreatingCreator] = useState(false)
  const [creatorFilterText, setCreatorFilterText] = useState('')

  // Process form state
  const [selectedAsr, setSelectedAsr] = useState('')
  const [selectedLlm, setSelectedLlm] = useState('')
  const [processMode, setProcessMode] = useState<'from_scratch' | 'retranslate' | 'continue'>('from_scratch')
  const [submittingProcess, setSubmittingProcess] = useState(false)

  const loadItem = async () => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const res = await api.get<ItemDetailData>(`/api/items/${id}`)
      setData(res)
      setEditTitle(res.item.title || '')
      setEditOrigTitle(res.item.original_title || '')
      setEditRjCode(res.item.rj_code || '')
      setEditTags((res.item.tags || []).join(', '))
      setEditTagsList(res.item.tags || [])
      setEditCreatorIds(res.item.creator_ids || [])
      if (res.available_profiles) {
        const defProc = res.available_profiles.default_processing
        if (defProc) {
          if (defProc.asr_provider === 'model' && defProc.asr_profile_id) {
            setSelectedAsr(`model:${defProc.asr_profile_id}`)
          } else if (defProc.asr_provider === 'deepgram') {
            setSelectedAsr('deepgram')
          } else {
            setSelectedAsr(`local:${defProc.whisper_model || 'large-v3'}`)
          }
          if (defProc.llm_profile_id) {
            setSelectedLlm(defProc.llm_profile_id)
          } else if (res.available_profiles.llm_profiles?.length > 0) {
            setSelectedLlm(res.available_profiles.llm_profiles[0].profile_id || '')
          }
        } else {
          if (res.available_profiles.asr_profiles?.length > 0) {
            setSelectedAsr(`model:${res.available_profiles.asr_profiles[0].profile_id}`)
          } else {
            setSelectedAsr('local:large-v3')
          }
          if (res.available_profiles.llm_profiles?.length > 0) {
            setSelectedLlm(res.available_profiles.llm_profiles[0].profile_id || '')
          }
        }
      }
    } catch (err: any) {
      setError('加载作品详情失败: ' + (err.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadItem()
    api.get<any>('/api/creators/list')
      .then((res) => {
        const list = Array.isArray(res) ? res : (res.creators || res.all_creators || [])
        setAllCreators(list)
      })
      .catch(() => {})
    api.get<{ all_tags?: string[] }>('/api/library/items?limit=1')
      .then((res) => {
        if (res.all_tags) setLibraryTags(res.all_tags)
      })
      .catch(() => {})
  }, [id])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '100px 0', color: 'var(--fg-dim)' }}>
        <p>正在加载作品详情…</p>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <p style={{ color: 'var(--color-red)', marginBottom: 16 }}>{error || '未找到该作品'}</p>
        <Link to="/" className="btn btn-ghost">
          <ArrowLeft size={16} />
          返回作品库
        </Link>
      </div>
    )
  }

  const { item, tracks, overview } = data
  const rawCoverUrl = item.cover_url || `/covers/${item.item_id}`
  const coverUrl = rawCoverUrl.includes('?v=')
    ? rawCoverUrl
    : `${rawCoverUrl}${item.updated_at ? (rawCoverUrl.includes('?') ? `&v=${encodeURIComponent(item.updated_at)}` : `?v=${encodeURIComponent(item.updated_at)}`) : ''}`
  const completedSubTracks = tracks.filter((t) => t.has_source_sub && t.has_target_sub).length
  const subPercent = tracks.length > 0 ? Math.round((completedSubTracks / tracks.length) * 100) : 0
  const defProc = data.available_profiles?.default_processing
  const isDefaultAsr = (val: string) => {
    if (!defProc) return false
    if (defProc.asr_provider === 'model') return val === `model:${defProc.asr_profile_id}`
    if (defProc.asr_provider === 'deepgram') return val === 'deepgram'
    return val === `local:${defProc.whisper_model || 'large-v3'}`
  }
  const isDefaultLlm = (pid: string) => defProc?.llm_profile_id === pid

  const handlePlayFirst = () => {
    const first = tracks.find((t) => t.has_media && t.status !== 'failed') || tracks[0]
    if (first) {
      playTrack(item, first)
    }
  }

  const handleToggleTrack = (track: Track) => {
    if (currentTrack?.track_id === track.track_id) {
      togglePlay()
    } else {
      playTrack(item, track)
    }
  }

  const handleChangeCover = async () => {
    try {
      const res = await api.post<{ selection_id?: string; cancelled?: boolean }>('/picker/image')
      if (res.selection_id) {
        const formData = new FormData()
        formData.append('selection_id', res.selection_id)
        await api.postForm(`/items/${item.item_id}/cover`, formData)
        loadItem()
      }
    } catch (err: any) {
      alert('更换封面失败: ' + err.message)
    }
  }

  const handleDeleteItem = async () => {
    if (!window.confirm(`确定要将作品《${item.title}》移入回收站吗？`)) return
    try {
      await api.post(`/api/items/${item.item_id}/trash`)
      navigate('/')
    } catch (err: any) {
      alert('删除作品失败: ' + err.message)
    }
  }

  const handleDeleteTrack = async (track: Track) => {
    if (!window.confirm(`确定要删除音轨《${track.title}》吗？`)) return
    try {
      await api.post(`/api/tracks/${track.track_id}/delete`)
      loadItem()
    } catch (err: any) {
      alert('删除音轨失败: ' + err.message)
    }
  }

  const handleOpenProcess = (trackId?: string) => {
    setSelectedTrackId(trackId || null)
    if (trackId) {
      const tr = data?.tracks.find((t) => t.track_id === trackId)
      setProcessMode(tr?.has_target_sub ? 'from_scratch' : 'continue')
    } else {
      setProcessMode('continue')
    }
    setProcessOpen(true)
  }

  const handleSubmitProcess = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmittingProcess(true)
    try {
      const formData = new FormData()
      if (selectedAsr.startsWith('model:')) {
        formData.append('asr_provider', 'model')
        formData.append('asr_profile_id', selectedAsr.replace('model:', ''))
      } else if (selectedAsr === 'deepgram') {
        formData.append('asr_provider', 'deepgram')
      } else if (selectedAsr.startsWith('local:')) {
        formData.append('asr_provider', 'local')
        formData.append('whisper_model', selectedAsr.replace('local:', ''))
      } else {
        formData.append('asr_provider', 'local')
      }
      if (selectedLlm) formData.append('llm_profile_id', selectedLlm)
      formData.append('mode', processMode)

      if (selectedTrackId) {
        await api.postForm(`/api/tracks/${selectedTrackId}/process`, formData)
      } else {
        formData.append('scope', processMode === 'from_scratch' ? 'all' : 'incomplete')
        await api.postForm(`/api/items/${item.item_id}/process`, formData)
      }
      setProcessOpen(false)
      navigate('/tasks')
    } catch (err: any) {
      alert('发起处理任务失败: ' + err.message)
    } finally {
      setSubmittingProcess(false)
    }
  }

  const availableQuickTags = useMemo(() => {
    const existing = new Set(editTagsList.map((t) => t.toLowerCase()))
    return libraryTags.filter((t) => !existing.has(t.toLowerCase()))
  }, [libraryTags, editTagsList])

  const filteredCreators = useMemo(() => {
    if (!creatorFilterText.trim()) return allCreators
    const q = creatorFilterText.trim().toLowerCase()
    return allCreators.filter((c) => c.name.toLowerCase().includes(q))
  }, [allCreators, creatorFilterText])

  const handleAddTag = (raw: string) => {
    if (!raw.trim()) return
    const parts = raw.split(/[,/、，\n]+/).map((s) => s.trim().replace(/^#/, '')).filter(Boolean)
    if (parts.length === 0) return
    setEditTagsList((prev) => {
      const set = new Set(prev.map((t) => t.toLowerCase()))
      const next = [...prev]
      for (const p of parts) {
        if (!set.has(p.toLowerCase())) {
          set.add(p.toLowerCase())
          next.push(p)
        }
      }
      return next
    })
    setNewTagInput('')
  }

  const handleRemoveTag = (tagToRemove: string) => {
    setEditTagsList((prev) => prev.filter((t) => t.toLowerCase() !== tagToRemove.toLowerCase()))
  }

  const handleCreateCreator = async () => {
    const name = newCreatorName.trim()
    if (!name) return
    setCreatingCreator(true)
    try {
      const res = await api.post<Creator>('/api/creators', {
        name,
        kind: newCreatorKind,
      })
      if (res && res.creator_id) {
        setAllCreators((prev) => {
          if (prev.some((c) => c.creator_id === res.creator_id)) return prev
          return [res, ...prev]
        })
        setEditCreatorIds((prev) => {
          if (prev.includes(res.creator_id)) return prev
          return [...prev, res.creator_id]
        })
        setNewCreatorName('')
        setShowAddCreator(false)
      }
    } catch (err: any) {
      alert('添加创作者失败: ' + (err.message || '未知错误'))
    } finally {
      setCreatingCreator(false)
    }
  }

  const handleSubmitEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmittingEdit(true)
    try {
      const formData = new FormData()
      formData.append('title', editTitle)
      formData.append('original_title', editOrigTitle)
      formData.append('rj_code', editRjCode)

      let finalTags = [...editTagsList]
      if (!rawTagMode && newTagInput.trim()) {
        const parts = newTagInput.split(/[,/、，\n]+/).map((s) => s.trim().replace(/^#/, '')).filter(Boolean)
        for (const p of parts) {
          if (!finalTags.some((t) => t.toLowerCase() === p.toLowerCase())) {
            finalTags.push(p)
          }
        }
      }
      formData.append('tags', rawTagMode ? editTags : finalTags.join(', '))
      editCreatorIds.forEach((cid) => formData.append('creator_ids', cid))

      await api.postForm(`/items/${item.item_id}/edit`, formData)
      setEditOpen(false)
      loadItem()
    } catch (err: any) {
      alert('保存修改失败: ' + err.message)
    } finally {
      setSubmittingEdit(false)
    }
  }

  const handleSyncDlsite = async () => {
    if (!item?.rj_code) return
    setSyncingDlsite(true)
    try {
      const res = await api.post<{ ok: boolean; message?: string; error?: string }>(`/api/items/${item.item_id}/sync-dlsite`)
      if (res.ok) {
        await loadItem()
      } else {
        alert(res.error || '同步 DLsite 信息失败')
      }
    } catch (err: any) {
      alert('同步失败: ' + (err.message || '未知错误'))
    } finally {
      setSyncingDlsite(false)
    }
  }

  return (
    <div className="item-detail-container">
      {/* Back button */}
      <div style={{ marginBottom: 16 }}>
        <Link to="/" className="btn btn-ghost btn-sm">
          <ArrowLeft size={16} />
          返回作品库
        </Link>
      </div>

      {/* Immersive Hero Backdrop & Metadata */}
      <div className="detail-hero">
        <div
          className="hero-backdrop"
          style={{ backgroundImage: `url(${coverUrl})` }}
        />

        <div className="hero-content">
          <div className="hero-poster">
            <img
              src={coverUrl}
              alt=""
              onError={(e) => ((e.target as HTMLElement).style.opacity = '0.3')}
            />
          </div>

          <div className="hero-info">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {item.rj_code && (
                <a
                  href={`https://www.dlsite.com/maniax/work/=/product_id/${item.rj_code}.html`}
                  target="_blank"
                  rel="noreferrer"
                  className="chip chip-rj"
                  title="在 DLsite 官网打开"
                >
                  {item.rj_code}
                  <ExternalLink size={11} style={{ marginLeft: 2 }} />
                </a>
              )}
              <span className="chip" style={{ background: 'rgba(255, 255, 255, 0.08)' }}>
                {overview?.track_count ?? tracks.length} 音轨
              </span>
              <span className="chip" style={{ background: 'rgba(255, 255, 255, 0.08)' }}>
                {overview?.total_duration_label || item.total_duration_label || '00:00'}
              </span>
            </div>

            <h1 className="hero-title">{item.title}</h1>
            {item.original_title && (
              <div className="hero-orig-title">{item.original_title}</div>
            )}

            <div className="hero-chips">
              {item.creators && item.creators.length > 0 ? (
                item.creators.map((c) => (
                  <span
                    key={c.creator_id}
                    className={`chip ${c.kind === 'voice_actor' ? 'chip-creator' : 'chip-circle'}`}
                  >
                    {c.kind === 'voice_actor' ? '🎙️ ' : '🏢 '}
                    {c.name}
                  </span>
                ))
              ) : item.author ? (
                <span className="chip chip-creator">🎙️ {item.author}</span>
              ) : null}
              {item.tags &&
                item.tags.map((t, idx) => (
                  <span
                    key={idx}
                    className="chip chip-tag"
                    style={{ cursor: 'pointer' }}
                    title={`在作品库中筛选标签 #${t}`}
                    onClick={() => navigate(`/library?tag=${encodeURIComponent(t)}`)}
                  >
                    #{t}
                  </span>
                ))}
            </div>

            {/* Subtitle Progress */}
            <div style={{ maxWidth: 360, marginTop: 4 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 4 }}>
                <span>双语字幕完成度</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: subPercent === 100 ? 'var(--color-green)' : 'var(--accent-base)' }}>
                  {completedSubTracks} / {tracks.length} 轨 ({subPercent}%)
                </span>
              </div>
              <div style={{ width: '100%', height: 6, background: 'rgba(255, 255, 255, 0.1)', borderRadius: 99, overflow: 'hidden' }}>
                <div
                  style={{
                    width: `${subPercent}%`,
                    height: '100%',
                    background: subPercent === 100 ? 'var(--color-green)' : 'var(--accent-base)',
                    transition: 'width 0.3s ease',
                  }}
                />
              </div>
            </div>

            {/* Action buttons */}
            <div className="hero-actions">
              <button type="button" className="btn btn-primary" onClick={handlePlayFirst}>
                <Play size={16} fill="currentColor" />
                开始播放
              </button>

              {overview.actionable_incomplete_count > 0 && (
                <button
                  type="button"
                  className="btn"
                  style={{ background: 'var(--accent-soft)', color: 'var(--accent-base)', borderColor: 'var(--accent-border)' }}
                  onClick={() => handleOpenProcess()}
                >
                  <Sparkles size={15} />
                  处理未完成音轨 ({overview.actionable_incomplete_count})
                </button>
              )}

              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setEditTitle(item.title || '')
                  setEditOrigTitle(item.original_title || '')
                  setEditRjCode(item.rj_code || '')
                  const curTags = item.tags || []
                  setEditTagsList(curTags)
                  setEditTags(curTags.join(', '))
                  setEditCreatorIds(item.creator_ids || [])
                  setNewTagInput('')
                  setShowAddCreator(false)
                  setNewCreatorName('')
                  setEditOpen(true)
                }}
              >
                <Edit3 size={15} />
                编辑作品
              </button>

              {item.rj_code && (
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={handleSyncDlsite}
                  disabled={syncingDlsite}
                  title="自动从 DLsite 获取社团、声优、标签、封面与发售日"
                >
                  <RefreshCw size={15} className={syncingDlsite ? 'spin' : ''} />
                  {syncingDlsite ? '正在同步…' : '从 DLsite 同步'}
                </button>
              )}

              <button type="button" className="btn btn-ghost" onClick={handleChangeCover}>
                <Image size={15} />
                更换封面
              </button>

              <button type="button" className="btn btn-ghost btn-danger" onClick={handleDeleteItem}>
                <Trash2 size={15} />
                删除
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Overview Stats Grid */}
      <div className="card-grid" style={{ marginBottom: 32 }}>
        <div className="stat-card">
          <span className="stat-value">{overview?.track_count ?? tracks.length}</span>
          <span className="stat-label">总音轨数</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{overview?.total_duration_label || item.total_duration_label || '00:00'}</span>
          <span className="stat-label">总播放时长</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">
            {formatBytes(overview?.total_size ?? item.total_size ?? tracks.reduce((acc, t) => acc + (t.size || 0), 0))}
          </span>
          <span className="stat-label">媒体总体积</span>
        </div>
        <div className="stat-card">
          <span className="stat-value" style={{ color: 'var(--color-green)' }}>
            {completedSubTracks}
          </span>
          <span className="stat-label">已生成双语字幕</span>
        </div>
      </div>

      {/* Tracklist Section */}
      <div className="card-panel">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <h3 style={{ fontSize: 16, fontWeight: 700 }}>音轨列表 ({tracks.length})</h3>
            {hasCustomWidths && (
              <button
                type="button"
                className="btn btn-ghost btn-xs"
                onClick={handleResetColWidths}
                title="重置所有列宽为默认值"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--fg-dim)' }}
              >
                <RotateCcw size={12} />
                重置列宽
              </button>
            )}
          </div>
          <span style={{ fontSize: 12, color: 'var(--fg-dim)' }}>
            拖动表头分隔线调整列宽（双击还原），点击标题就地试听或「播放台本」
          </span>
        </div>

        <div className="works-table-container">
          <table
            className="works-table"
            style={{
              tableLayout: 'fixed',
              width: '100%',
              minWidth: totalColWidth,
            }}
          >
            <colgroup>
              <col style={{ width: colWidths.index }} />
              <col style={{ width: colWidths.play }} />
              <col style={{ width: 'auto' }} />
              <col style={{ width: colWidths.duration }} />
              <col style={{ width: colWidths.status }} />
              <col style={{ width: colWidths.size }} />
              <col style={{ width: colWidths.actions }} />
            </colgroup>
            <thead>
              <tr>
                <th style={{ textAlign: 'center' }}>
                  #
                  <div
                    className={`table-resizer ${activeResizingCol === 'index' ? 'is-active' : ''}`}
                    onMouseDown={(e) => startResizing('index', e)}
                    onDoubleClick={() => handleResetSingleCol('index')}
                    title="拖动调整序号列宽，双击恢复默认"
                  />
                </th>
                <th style={{ textAlign: 'center' }}>
                  <div
                    className={`table-resizer ${activeResizingCol === 'play' ? 'is-active' : ''}`}
                    onMouseDown={(e) => startResizing('play', e)}
                    onDoubleClick={() => handleResetSingleCol('play')}
                    title="拖动调整播放列宽，双击恢复默认"
                  />
                </th>
                <th>
                  音轨标题
                  <div
                    className={`table-resizer ${activeResizingCol === 'title' ? 'is-active' : ''}`}
                    onMouseDown={(e) => startResizing('title', e)}
                    onDoubleClick={() => handleResetSingleCol('title')}
                    title="拖动调整标题列宽，双击恢复默认"
                  />
                </th>
                <th style={{ textAlign: 'center' }}>
                  时长
                  <div
                    className={`table-resizer ${activeResizingCol === 'duration' ? 'is-active' : ''}`}
                    onMouseDown={(e) => startResizing('duration', e)}
                    onDoubleClick={() => handleResetSingleCol('duration')}
                    title="拖动调整时长列宽，双击恢复默认"
                  />
                </th>
                <th style={{ textAlign: 'center' }}>
                  字幕状态
                  <div
                    className={`table-resizer ${activeResizingCol === 'status' ? 'is-active' : ''}`}
                    onMouseDown={(e) => startResizing('status', e)}
                    onDoubleClick={() => handleResetSingleCol('status')}
                    title="拖动调整状态列宽，双击恢复默认"
                  />
                </th>
                <th style={{ textAlign: 'center' }}>
                  大小
                  <div
                    className={`table-resizer ${activeResizingCol === 'size' ? 'is-active' : ''}`}
                    onMouseDown={(e) => startResizing('size', e)}
                    onDoubleClick={() => handleResetSingleCol('size')}
                    title="拖动调整大小列宽，双击恢复默认"
                  />
                </th>
                <th style={{ textAlign: 'right' }}>
                  <div
                    className={`table-resizer table-resizer-left ${activeResizingCol === 'actions' ? 'is-active' : ''}`}
                    onMouseDown={(e) => startResizing('actions', e, true)}
                    onDoubleClick={() => handleResetSingleCol('actions')}
                    title="拖动调整操作列宽，双击恢复默认"
                  />
                  操作
                </th>
              </tr>
            </thead>
            <tbody>
              {tracks.map((track, idx) => {
                const isCurrent = currentTrack?.track_id === track.track_id
                return (
                  <tr key={track.track_id} style={{ background: isCurrent ? 'var(--accent-soft)' : undefined }}>
                    <td style={{ textAlign: 'center', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--fg-faint)' }}>
                      {idx + 1}
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <button
                        type="button"
                        className="btn btn-sm btn-primary btn-circle"
                        onClick={() => handleToggleTrack(track)}
                        title={isCurrent && isPlaying ? '暂停' : '就地播放'}
                      >
                        {isCurrent && isPlaying ? (
                          <Pause size={13} fill="currentColor" />
                        ) : (
                          <Play size={13} fill="currentColor" style={{ marginLeft: 2 }} />
                        )}
                      </button>
                    </td>
                    <td style={{ overflow: 'hidden' }}>
                      <div
                        style={{
                          fontWeight: 600,
                          color: isCurrent ? 'var(--accent-base)' : 'var(--fg-main)',
                          cursor: 'pointer',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                        onClick={() => handleToggleTrack(track)}
                        title={track.title}
                      >
                        {track.title}
                      </div>
                    </td>
                    <td style={{ textAlign: 'center', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--fg-dim)', whiteSpace: 'nowrap' }}>
                      {track.duration_label || '00:00'}
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <div style={{ display: 'flex', justifyContent: 'center' }}>
                        {track.has_source_sub && track.has_target_sub ? (
                          <span className="sub-badge sub-bilingual">双语 ✓</span>
                        ) : track.has_source_sub ? (
                          <span className="sub-badge sub-jp">仅日文</span>
                        ) : track.has_target_sub ? (
                          <span className="sub-badge sub-zh">仅中字</span>
                        ) : (
                          <span className="sub-badge sub-none">未转写</span>
                        )}
                      </div>
                    </td>
                    <td style={{ textAlign: 'center', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--fg-dim)', whiteSpace: 'nowrap' }}>
                      {formatBytes(track.size)}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center' }}>
                        <Link
                          to={`/tracks/${track.track_id}/play`}
                          className="btn btn-sm"
                          style={{ background: 'var(--accent-soft)', color: 'var(--accent-base)' }}
                          title="打开沉浸式双语台本播放器"
                        >
                          <FileText size={13} />
                          播放台本
                        </Link>

                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={() => handleOpenProcess(track.track_id)}
                          title="发起 ASR 识别与 LLM 翻译"
                        >
                          <Sparkles size={13} />
                          处理
                        </button>

                        {track.has_target_sub ? (
                          <a
                            href={`/tracks/${track.track_id}/subtitles/zh/download`}
                            download
                            className="btn btn-sm btn-ghost btn-circle"
                            style={{ width: 30, height: 30, padding: 0 }}
                            title="下载中文字幕 (.srt)"
                          >
                            <Download size={13} />
                          </a>
                        ) : (
                          <span style={{ width: 30, height: 30, display: 'inline-block' }} />
                        )}

                        <button
                          type="button"
                          className="btn btn-sm btn-ghost btn-circle btn-danger"
                          onClick={() => handleDeleteTrack(track)}
                          title="删除音轨"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Batch / Single Process Modal */}
      {processOpen && (
        <div className="modal-overlay" onClick={() => setProcessOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">
                {selectedTrackId ? '发起单轨语音识别与翻译' : '批量处理作品音轨'}
              </h3>
              <button
                type="button"
                className="btn btn-ghost btn-circle"
                onClick={() => setProcessOpen(false)}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSubmitProcess}>
              <div className="modal-body">
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <label style={{ fontSize: 12, color: 'var(--fg-dim)' }}>
                      ASR 语音识别引擎 (可手动切换)
                    </label>
                    <Link to="/settings" style={{ fontSize: 11, color: 'var(--accent-base)' }}>
                      在设置中更改默认
                    </Link>
                  </div>
                  <select
                    className="select-field"
                    style={{ width: '100%' }}
                    value={selectedAsr}
                    onChange={(e) => setSelectedAsr(e.target.value)}
                  >
                    <optgroup label="本地离线 Whisper (faster-whisper GPU/CPU)">
                      <option value="local:large-v3">
                        本地 Faster-Whisper (large-v3 - 最高精度) {isDefaultAsr('local:large-v3') ? '★ [默认]' : ''}
                      </option>
                      <option value="local:medium">
                        本地 Faster-Whisper (medium - 均衡显存) {isDefaultAsr('local:medium') ? '★ [默认]' : ''}
                      </option>
                      <option value="local:base">
                        本地 Faster-Whisper (base - 快速轻量) {isDefaultAsr('local:base') ? '★ [默认]' : ''}
                      </option>
                    </optgroup>
                    {data.available_profiles?.asr_profiles && data.available_profiles.asr_profiles.length > 0 && (
                      <optgroup label="API / 自定义音频转写模型 (OpenAI / Gemini)">
                        {data.available_profiles.asr_profiles.map((p: any) => (
                          <option key={p.profile_id} value={`model:${p.profile_id}`}>
                            {p.name} ({p.model}) {isDefaultAsr(`model:${p.profile_id}`) ? '★ [默认]' : ''}
                          </option>
                        ))}
                      </optgroup>
                    )}
                    <optgroup label="云端极速转写">
                      <option value="deepgram">
                        Deepgram Nova-3 (云端) {isDefaultAsr('deepgram') ? '★ [默认]' : ''}
                      </option>
                    </optgroup>
                  </select>
                </div>

                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <label style={{ fontSize: 12, color: 'var(--fg-dim)' }}>
                      LLM 双语翻译模型 (可手动切换)
                    </label>
                    <Link to="/settings" style={{ fontSize: 11, color: 'var(--accent-base)' }}>
                      在设置中更改默认
                    </Link>
                  </div>
                  <select
                    className="select-field"
                    style={{ width: '100%' }}
                    value={selectedLlm}
                    onChange={(e) => setSelectedLlm(e.target.value)}
                  >
                    {data.available_profiles?.llm_profiles?.map((p: any) => (
                      <option key={p.profile_id} value={p.profile_id}>
                        {p.name} ({p.model}) {isDefaultLlm(p.profile_id) ? '★ [默认]' : ''}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                    处理方式
                  </label>
                  <select
                    className="select-field"
                    style={{ width: '100%' }}
                    value={processMode}
                    onChange={(e) => setProcessMode(e.target.value as any)}
                  >
                    <option value="from_scratch">从头进行 ASR 语音识别与双语翻译（重新生成）</option>
                    <option value="retranslate">仅重新翻译（沿用已有 ASR 日语文本）</option>
                    <option value="continue">断点续跑（沿用原配置继续未完成部分）</option>
                  </select>
                </div>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setProcessOpen(false)}
                  disabled={submittingProcess}
                >
                  取消
                </button>
                <button type="submit" className="btn btn-primary" disabled={submittingProcess}>
                  <Sparkles size={14} />
                  {submittingProcess ? '正在提交…' : '立即开始任务'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Item Modal */}
      {editOpen && (
        <div className="modal-overlay" onClick={() => setEditOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">编辑作品元数据</h3>
              <button
                type="button"
                className="btn btn-ghost btn-circle"
                onClick={() => setEditOpen(false)}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSubmitEdit}>
              <div className="modal-body">
                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                    作品标题 *
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    required
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                    日文原名
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={editOrigTitle}
                    onChange={(e) => setEditOrigTitle(e.target.value)}
                  />
                </div>

                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <label style={{ fontSize: 12, color: 'var(--fg-dim)' }}>
                      RJ 号
                    </label>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      style={{ fontSize: 11, padding: '2px 8px', height: 'auto', color: 'var(--accent-base)' }}
                      onClick={async () => {
                        if (!editRjCode.trim()) return
                        try {
                          const res = await api.get<{ ok: boolean; data: any }>(`/api/dlsite/${editRjCode.trim()}`)
                          if (res.ok && res.data) {
                            if (res.data.title && !editTitle) setEditTitle(res.data.title)
                            if (res.data.tags && res.data.tags.length > 0) {
                              setEditTagsList(res.data.tags)
                              setEditTags(res.data.tags.join(', '))
                            }
                            const newCreatorIds = [...editCreatorIds]
                            if (res.data.circle) {
                              let circle = allCreators.find((c) => c.kind === 'circle' && c.name.toLowerCase() === res.data.circle.toLowerCase())
                              if (!circle) {
                                try {
                                  circle = await api.post<Creator>('/api/creators', { name: res.data.circle, kind: 'circle' })
                                  if (circle) setAllCreators((prev) => [circle!, ...prev])
                                } catch {}
                              }
                              if (circle && !newCreatorIds.includes(circle.creator_id)) {
                                newCreatorIds.push(circle.creator_id)
                              }
                            }
                            if (Array.isArray(res.data.voice_actors)) {
                              for (const va of res.data.voice_actors) {
                                let vaCreator = allCreators.find((c) => c.kind === 'voice_actor' && c.name.toLowerCase() === va.toLowerCase())
                                if (!vaCreator) {
                                  try {
                                    vaCreator = await api.post<Creator>('/api/creators', { name: va, kind: 'voice_actor' })
                                    if (vaCreator) setAllCreators((prev) => [vaCreator!, ...prev])
                                  } catch {}
                                }
                                if (vaCreator && !newCreatorIds.includes(vaCreator.creator_id)) {
                                  newCreatorIds.push(vaCreator.creator_id)
                                }
                              }
                            }
                            setEditCreatorIds(newCreatorIds)
                          }
                        } catch {}
                      }}
                    >
                      <Globe size={12} />
                      从 DLsite 填充
                    </button>
                  </div>
                  <input
                    type="text"
                    className="input-field"
                    value={editRjCode}
                    onChange={(e) => setEditRjCode(e.target.value.toUpperCase())}
                  />
                </div>

                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <label style={{ fontSize: 12, color: 'var(--fg-dim)' }}>
                      标签 {editTagsList.length > 0 && `(已选 ${editTagsList.length})`}
                    </label>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      style={{ fontSize: 11, padding: '2px 6px', height: 'auto', color: 'var(--fg-dim)' }}
                      onClick={() => {
                        if (!rawTagMode) {
                          setEditTags(editTagsList.join(', '))
                        } else {
                          const parts = editTags.split(/[,/、，\n]+/).map((s) => s.trim().replace(/^#/, '')).filter(Boolean)
                          setEditTagsList(Array.from(new Set(parts)))
                        }
                        setRawTagMode(!rawTagMode)
                      }}
                    >
                      {rawTagMode ? '切回标签徽章' : '纯文本模式'}
                    </button>
                  </div>

                  {!rawTagMode ? (
                    <div>
                      {/* Current selected tags chips */}
                      <div
                        style={{
                          display: 'flex',
                          flexWrap: 'wrap',
                          gap: 6,
                          padding: '6px 8px',
                          background: 'rgba(255, 255, 255, 0.03)',
                          border: '1px solid var(--border-subtle)',
                          borderRadius: 'var(--radius-sm)',
                          minHeight: 38,
                          marginBottom: 8,
                          alignItems: 'center',
                        }}
                      >
                        {editTagsList.length === 0 ? (
                          <span style={{ fontSize: 12, color: 'var(--fg-faint)' }}>暂无标签，可输入或在下方点击快速添加</span>
                        ) : (
                          editTagsList.map((tag) => (
                            <span
                              key={tag}
                              className="chip chip-tag"
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 4,
                                padding: '2px 7px',
                                fontSize: 12,
                              }}
                            >
                              🏷️ {tag}
                              <button
                                type="button"
                                onClick={() => handleRemoveTag(tag)}
                                style={{
                                  background: 'transparent',
                                  border: 'none',
                                  padding: 0,
                                  cursor: 'pointer',
                                  color: 'inherit',
                                  opacity: 0.7,
                                  display: 'flex',
                                  alignItems: 'center',
                                }}
                                title="删除标签"
                              >
                                <X size={12} />
                              </button>
                            </span>
                          ))
                        )}
                      </div>

                      {/* Add new tag input bar */}
                      <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
                        <input
                          type="text"
                          className="input-field"
                          style={{ flex: 1, height: 30, fontSize: 12 }}
                          value={newTagInput}
                          onChange={(e) => setNewTagInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault()
                              handleAddTag(newTagInput)
                            }
                          }}
                          placeholder="输入标签名（回车或逗号分隔批量添加）…"
                        />
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          style={{ height: 30, padding: '0 10px', fontSize: 12 }}
                          onClick={() => handleAddTag(newTagInput)}
                        >
                          <Plus size={13} />
                          添加标签
                        </button>
                      </div>

                      {/* Quick-add suggestions from existing library tags */}
                      {availableQuickTags.length > 0 && (
                        <div style={{ marginBottom: 4 }}>
                          <div style={{ fontSize: 11, color: 'var(--fg-faint)', marginBottom: 4 }}>
                            作品库已有标签（点击添加）：
                          </div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, maxHeight: 68, overflowY: 'auto' }}>
                            {availableQuickTags.slice(0, 30).map((t: string) => (
                              <button
                                key={t}
                                type="button"
                                className="chip"
                                style={{
                                  cursor: 'pointer',
                                  background: 'rgba(255, 255, 255, 0.05)',
                                  fontSize: 11,
                                  padding: '1px 6px',
                                  lineHeight: '18px',
                                }}
                                onClick={() => handleAddTag(t)}
                              >
                                + {t}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <input
                      type="text"
                      className="input-field"
                      value={editTags}
                      onChange={(e) => {
                        setEditTags(e.target.value)
                        const parts = e.target.value.split(/[,/、，\n]+/).map((s) => s.trim().replace(/^#/, '')).filter(Boolean)
                        setEditTagsList(Array.from(new Set(parts)))
                      }}
                      placeholder="如: 耳かき, 添い寝, 囁き"
                    />
                  )}
                </div>

                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <label style={{ fontSize: 12, color: 'var(--fg-dim)' }}>
                      关联创作者 {editCreatorIds.length > 0 && `(已选 ${editCreatorIds.length})`}
                    </label>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      style={{ fontSize: 11, padding: '2px 8px', height: 'auto', color: 'var(--accent-base)' }}
                      onClick={() => setShowAddCreator(!showAddCreator)}
                    >
                      <Plus size={12} />
                      {showAddCreator ? '收起新增' : '新增创作者'}
                    </button>
                  </div>

                  {/* Inline Add Creator Form */}
                  {showAddCreator && (
                    <div
                      style={{
                        display: 'flex',
                        gap: 8,
                        alignItems: 'center',
                        padding: '8px 10px',
                        background: 'rgba(255, 255, 255, 0.03)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: 'var(--radius-sm)',
                        marginBottom: 10,
                        flexWrap: 'wrap',
                      }}
                    >
                      <input
                        type="text"
                        className="input-field"
                        style={{ flex: 1, minWidth: 130, height: 30, fontSize: 12 }}
                        placeholder="创作者/声优/社团名称…"
                        value={newCreatorName}
                        onChange={(e) => setNewCreatorName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            handleCreateCreator()
                          }
                        }}
                      />
                      <select
                        className="select-field"
                        style={{ height: 30, fontSize: 12, padding: '2px 8px' }}
                        value={newCreatorKind}
                        onChange={(e) => setNewCreatorKind(e.target.value as 'voice_actor' | 'circle')}
                      >
                        <option value="voice_actor">🎙️ 声优 (CV)</option>
                        <option value="circle">🏢 社团 (Circle)</option>
                      </select>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        style={{ height: 30, padding: '0 10px', fontSize: 12 }}
                        onClick={handleCreateCreator}
                        disabled={creatingCreator || !newCreatorName.trim()}
                      >
                        <Plus size={13} />
                        {creatingCreator ? '添加中…' : '添加'}
                      </button>
                    </div>
                  )}

                  {/* Search/filter existing creators if list is long */}
                  {allCreators.length > 8 && (
                    <div style={{ marginBottom: 6 }}>
                      <input
                        type="text"
                        className="input-field"
                        style={{ height: 26, fontSize: 11, padding: '2px 8px' }}
                        placeholder="筛选已有创作者…"
                        value={creatorFilterText}
                        onChange={(e) => setCreatorFilterText(e.target.value)}
                      />
                    </div>
                  )}

                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', maxHeight: 120, overflowY: 'auto' }}>
                    {filteredCreators.map((c: Creator) => {
                      const active = editCreatorIds.includes(c.creator_id)
                      return (
                        <button
                          key={c.creator_id}
                          type="button"
                          className={`chip ${active ? (c.kind === 'voice_actor' ? 'chip-creator' : 'chip-circle') : 'chip-tag'}`}
                          onClick={() => {
                            setEditCreatorIds((prev) =>
                              prev.includes(c.creator_id)
                                ? prev.filter((i) => i !== c.creator_id)
                                : [...prev, c.creator_id]
                            )
                          }}
                          style={{ cursor: 'pointer' }}
                        >
                          {active && <Check size={12} />}
                          {c.kind === 'voice_actor' ? '🎙️ ' : '🏢 '}
                          {c.name}
                        </button>
                      )
                    })}
                  </div>
                </div>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setEditOpen(false)}
                  disabled={submittingEdit}
                >
                  取消
                </button>
                <button type="submit" className="btn btn-primary" disabled={submittingEdit}>
                  {submittingEdit ? '正在保存…' : '保存修改'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
