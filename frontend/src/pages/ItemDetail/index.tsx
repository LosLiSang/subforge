import React, { useEffect, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  Play,
  Edit,
  Trash2,
  Sparkles,
  Download,
  ArrowLeft,
  Clock,
  ExternalLink,
  Layers,
  Image as ImageIcon,
  Check,
  X,
} from 'lucide-react'
import { api } from '../../api/client'
import type { ItemDetailData, Track } from '../../types'
import { usePlayer } from '../../context/PlayerContext'

export function ItemDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { playTrack } = usePlayer()

  const [data, setData] = useState<ItemDetailData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Edit modal
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editOrigTitle, setEditOrigTitle] = useState('')
  const [editRjCode, setEditRjCode] = useState('')
  const [editTags, setEditTags] = useState('')
  const [allCreators, setAllCreators] = useState<any[]>([])
  const [editCreatorIds, setEditCreatorIds] = useState<string[]>([])

  // Process modal
  const [processModalOpen, setProcessModalOpen] = useState(false)
  const [processTrackId, setProcessTrackId] = useState<string | null>(null)
  const [selectedAsrProfile, setSelectedAsrProfile] = useState('')
  const [selectedLlmProfile, setSelectedLlmProfile] = useState('')
  const [processScope, setProcessScope] = useState<'incomplete' | 'all'>('incomplete')

  // Inline track renaming
  const [renamingTrackId, setRenamingTrackId] = useState<string | null>(null)
  const [newTrackTitle, setNewTrackTitle] = useState('')

  const fetchDetail = async () => {
    if (!id) return
    setLoading(true)
    try {
      const res = await api.get<ItemDetailData>(`/api/items/${id}`)
      setData(res)
      if (res.available_profiles?.asr_profiles?.length > 0) {
        setSelectedAsrProfile(res.available_profiles.asr_profiles[0].profile_id)
      }
      if (res.available_profiles?.llm_profiles?.length > 0) {
        setSelectedLlmProfile(res.available_profiles.llm_profiles[0].profile_id)
      }
    } catch (err: any) {
      setError(err.message || '加载作品详情失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDetail()
  }, [id])

  const handleOpenEdit = async () => {
    if (!data) return
    setEditTitle(data.item.title)
    setEditOrigTitle(data.item.original_title || '')
    setEditRjCode(data.item.rj_code || '')
    setEditTags(data.item.tags?.join(', ') || '')
    setEditCreatorIds(data.item.creator_ids || [])
    try {
      const creators = await api.get<any[]>('/api/creators/list')
      setAllCreators(creators || [])
    } catch {}
    setEditModalOpen(true)
  }

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!id) return
    try {
      await api.post(`/items/${id}/edit`, {
        title: editTitle.trim(),
        original_title: editOrigTitle.trim(),
        rj_code: editRjCode.trim(),
        creator_ids: editCreatorIds,
        tags: editTags
          .split(/[,，\s]+/)
          .map((t) => t.trim())
          .filter(Boolean),
        kind: data?.item.kind || 'stream_archive',
      })
      setEditModalOpen(false)
      fetchDetail()
    } catch (err: any) {
      alert('保存修改失败: ' + err.message)
    }
  }

  const handleDeleteItem = async () => {
    if (!id || !confirm('确定要删除这部作品吗？关联文件将移入回收站。')) return
    try {
      await api.post(`/items/${id}/trash`)
      navigate('/')
    } catch (err: any) {
      alert('删除作品失败: ' + err.message)
    }
  }

  const handleReplaceCover = async () => {
    if (!id) return
    try {
      const pickerRes = await api.post<{ selection_id: string }>('/picker/image')
      if (pickerRes.selection_id) {
        await api.post(`/items/${id}/cover`, { selection_id: pickerRes.selection_id })
        fetchDetail()
      }
    } catch (err: any) {
      alert('更换封面失败: ' + err.message)
    }
  }

  const handleStartProcess = async () => {
    if (!id) return
    try {
      if (processTrackId) {
        await api.post(`/tracks/${processTrackId}/process`, {
          model_profile_id: selectedAsrProfile || undefined,
          translation_profile_id: selectedLlmProfile || undefined,
        })
      } else {
        await api.post(`/items/${id}/process`, {
          model_profile_id: selectedAsrProfile || undefined,
          translation_profile_id: selectedLlmProfile || undefined,
          scope: processScope,
        })
      }
      setProcessModalOpen(false)
      setProcessTrackId(null)
      alert('已成功创建字幕生成任务，可在任务中心查看进度！')
      fetchDetail()
    } catch (err: any) {
      alert('发起处理任务失败: ' + err.message)
    }
  }

  const handleSaveTrackRename = async (trackId: string) => {
    if (!newTrackTitle.trim()) return
    try {
      await api.post(`/tracks/${trackId}/rename`, { title: newTrackTitle.trim() })
      setRenamingTrackId(null)
      fetchDetail()
    } catch (err: any) {
      alert('重命名音轨失败: ' + err.message)
    }
  }

  const handleDeleteTrack = async (trackId: string) => {
    if (!confirm('确定要从作品中删除该音轨吗？')) return
    try {
      await api.post(`/tracks/${trackId}/delete`)
      fetchDetail()
    } catch (err: any) {
      alert('删除音轨失败: ' + err.message)
    }
  }

  if (loading) {
    return <div className="page-container text-center py-20 text-fg-dim">正在加载作品详情...</div>
  }

  if (error || !data) {
    return (
      <div className="page-container py-12 text-center space-y-4">
        <div className="text-red-400">{error || '未找到该作品'}</div>
        <Link to="/" className="btn btn-secondary inline-flex items-center gap-1.5">
          <ArrowLeft size={16} /> 返回作品库
        </Link>
      </div>
    )
  }

  const { item, tracks, overview } = data
  const dlsiteUrl = item.rj_code
    ? `https://www.dlsite.com/maniax/work/=/product_id/${item.rj_code}.html`
    : null

  return (
    <div className="page-container space-y-8">
      {/* Navigation breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-fg-dim">
        <Link to="/" className="hover:text-white flex items-center gap-1">
          <ArrowLeft size={14} /> 作品库
        </Link>
        <span>/</span>
        <span className="text-fg truncate max-w-md">{item.title}</span>
      </div>

      {/* Item Hero Overview */}
      <div className="item-detail-hero">
        <div className="item-hero-cover-wrapper group">
          <img
            src={item.cover_url}
            alt={item.title}
            className="item-hero-cover"
            onError={(e) => {
              ;(e.target as HTMLElement).style.opacity = '0.3'
            }}
          />
          <button
            type="button"
            onClick={handleReplaceCover}
            className="cover-replace-overlay"
            title="更换封面图片"
          >
            <ImageIcon size={20} />
            <span>更换封面</span>
          </button>
        </div>

        <div className="item-hero-info">
          <div className="flex items-center gap-2 flex-wrap">
            {item.rj_code && (
              <span className="badge badge-accent text-sm font-mono">{item.rj_code}</span>
            )}
            {dlsiteUrl && (
              <a
                href={dlsiteUrl}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-accent hover:underline flex items-center gap-1"
              >
                DLsite <ExternalLink size={12} />
              </a>
            )}
          </div>

          <h1 className="text-2xl font-bold tracking-tight text-white">{item.title}</h1>
          {item.original_title && (
            <div className="text-sm text-fg-dim font-mono">{item.original_title}</div>
          )}

          {/* Creators */}
          <div className="flex flex-wrap items-center gap-2 text-sm pt-1">
            <span className="text-fg-faint">创作者:</span>
            {item.creators && item.creators.length > 0 ? (
              item.creators.map((c) => (
                <span key={c.creator_id} className="creator-pill">
                  {c.name}
                  <span className="text-xs text-fg-faint ml-1">
                    ({c.kind === 'voice_actor' ? '声优' : '社团'})
                  </span>
                </span>
              ))
            ) : (
              <span className="text-fg-dim">暂无</span>
            )}
          </div>

          {/* Tags */}
          {item.tags && item.tags.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 pt-1">
              {item.tags.map((t) => (
                <span key={t} className="tag-chip">
                  {t}
                </span>
              ))}
            </div>
          )}

          {/* Stats metrics */}
          <div className="flex items-center gap-6 text-sm text-fg-dim pt-2 border-t border-line">
            <span className="flex items-center gap-1.5">
              <Layers size={16} /> 共 {tracks.length} 音轨
            </span>
            <span className="flex items-center gap-1.5">
              <Clock size={16} /> 总时长: {overview.total_duration_label}
            </span>
            <span>已完成字幕: {overview.playable_count}</span>
          </div>

          {/* Action buttons */}
          <div className="flex flex-wrap items-center gap-3 pt-3">
            {overview.first_playable_track_id && (
              <button
                type="button"
                onClick={() => {
                  const track = tracks.find((t) => t.track_id === overview.first_playable_track_id)
                  if (track) playTrack(item, track)
                }}
                className="btn btn-primary flex items-center gap-2"
              >
                <Play size={18} />
                播放第一轨
              </button>
            )}

            <button
              type="button"
              onClick={() => {
                setProcessTrackId(null)
                setProcessScope('incomplete')
                setProcessModalOpen(true)
              }}
              className="btn btn-secondary flex items-center gap-2"
            >
              <Sparkles size={16} className="text-accent" />
              生成字幕任务
            </button>

            <button
              type="button"
              onClick={handleOpenEdit}
              className="btn btn-secondary flex items-center gap-1.5"
            >
              <Edit size={16} />
              编辑信息
            </button>

            <button
              type="button"
              onClick={handleDeleteItem}
              className="btn btn-danger flex items-center gap-1.5 ml-auto"
            >
              <Trash2 size={16} />
              删除作品
            </button>
          </div>
        </div>
      </div>

      {/* Tracks List Table */}
      <div className="bg-panel rounded-xl border border-line overflow-hidden">
        <div className="p-4 border-b border-line flex justify-between items-center">
          <h2 className="text-base font-semibold">音轨列表 ({tracks.length})</h2>
        </div>

        <div className="divide-y divide-line">
          {tracks.map((track, idx) => (
            <div
              key={track.track_id}
              className="p-3.5 hover:bg-panel-2 transition flex items-center justify-between gap-4 group"
            >
              <div className="flex items-center gap-3 flex-1 min-w-0">
                <span className="text-sm font-mono text-fg-faint w-6 text-right flex-none">
                  {idx + 1}
                </span>

                {renamingTrackId === track.track_id ? (
                  <div className="flex items-center gap-2 flex-1">
                    <input
                      type="text"
                      value={newTrackTitle}
                      onChange={(e) => setNewTrackTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleSaveTrackRename(track.track_id)
                        if (e.key === 'Escape') setRenamingTrackId(null)
                      }}
                      autoFocus
                      className="input-text text-sm py-1"
                    />
                    <button
                      type="button"
                      onClick={() => handleSaveTrackRename(track.track_id)}
                      className="p-1 hover:text-green-400"
                    >
                      <Check size={16} />
                    </button>
                    <button
                      type="button"
                      onClick={() => setRenamingTrackId(null)}
                      className="p-1 hover:text-red-400"
                    >
                      <X size={16} />
                    </button>
                  </div>
                ) : (
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm truncate text-white">
                        {track.title}
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          setRenamingTrackId(track.track_id)
                          setNewTrackTitle(track.title)
                        }}
                        className="opacity-0 group-hover:opacity-100 p-0.5 text-fg-dim hover:text-white"
                        title="重命名"
                      >
                        <Edit size={12} />
                      </button>
                    </div>
                    <div className="text-xs text-fg-dim flex items-center gap-3 mt-0.5">
                      <span>{track.duration_label}</span>
                      {track.has_target_sub && track.has_source_sub && (
                        <span className="text-green-400">双语字幕就绪</span>
                      )}
                      {track.has_target_sub && !track.has_source_sub && (
                        <span className="text-blue-400">仅中文字幕</span>
                      )}
                      {track.has_source_sub && !track.has_target_sub && (
                        <span className="text-yellow-400">仅日文字幕</span>
                      )}
                      {!track.has_source_sub && !track.has_target_sub && (
                        <span className="text-fg-faint">未生成字幕</span>
                      )}
                    </div>
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 flex-none">
                {track.has_media && (
                  <button
                    type="button"
                    onClick={() => playTrack(item, track)}
                    className="btn btn-secondary btn-sm flex items-center gap-1.5"
                  >
                    <Play size={14} /> 播放
                  </button>
                )}

                <button
                  type="button"
                  onClick={() => {
                    setProcessTrackId(track.track_id)
                    setProcessModalOpen(true)
                  }}
                  className="btn btn-secondary btn-sm flex items-center gap-1"
                  title="为该音轨生成或重跑字幕"
                >
                  <Sparkles size={14} className="text-accent" /> 生成字幕
                </button>

                {track.has_target_sub && (
                  <a
                    href={`/api/tracks/${track.track_id}/subtitles/zh/download`}
                    download
                    className="btn btn-secondary btn-sm p-1.5 text-fg-dim hover:text-white"
                    title="下载中文字幕 (SRT)"
                  >
                    <Download size={15} />
                  </a>
                )}

                <button
                  type="button"
                  onClick={() => handleDeleteTrack(track.track_id)}
                  className="btn btn-danger btn-sm p-1.5"
                  title="删除该音轨"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Edit Item Modal */}
      {editModalOpen && (
        <div className="modal-backdrop">
          <div className="modal-dialog">
            <div className="modal-header">
              <h3 className="modal-title">编辑作品信息</h3>
              <button
                type="button"
                onClick={() => setEditModalOpen(false)}
                className="modal-close-btn"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSaveEdit} className="modal-body space-y-4">
              <div className="space-y-1">
                <label className="text-sm font-medium">作品标题</label>
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="input-text"
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-sm font-medium">RJ 号</label>
                  <input
                    type="text"
                    value={editRjCode}
                    onChange={(e) => setEditRjCode(e.target.value)}
                    className="input-text"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium">日文原名</label>
                  <input
                    type="text"
                    value={editOrigTitle}
                    onChange={(e) => setEditOrigTitle(e.target.value)}
                    className="input-text"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">创作者 (按住 Ctrl 多选)</label>
                <select
                  multiple
                  value={editCreatorIds}
                  onChange={(e) => {
                    const options = Array.from(e.target.selectedOptions, (option) => option.value)
                    setEditCreatorIds(options)
                  }}
                  className="input-text h-24"
                >
                  {allCreators.map((c) => (
                    <option key={c.creator_id} value={c.creator_id}>
                      {c.name} ({c.kind === 'voice_actor' ? '声优' : '社团'})
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">标签</label>
                <input
                  type="text"
                  value={editTags}
                  onChange={(e) => setEditTags(e.target.value)}
                  className="input-text"
                />
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  onClick={() => setEditModalOpen(false)}
                  className="btn btn-secondary"
                >
                  取消
                </button>
                <button type="submit" className="btn btn-primary">
                  保存更改
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Process Task Modal */}
      {processModalOpen && (
        <div className="modal-backdrop">
          <div className="modal-dialog">
            <div className="modal-header">
              <h3 className="modal-title flex items-center gap-2">
                <Sparkles size={18} className="text-accent" />
                {processTrackId ? '生成单轨字幕' : '批量生成字幕'}
              </h3>
              <button
                type="button"
                onClick={() => setProcessModalOpen(false)}
                className="modal-close-btn"
              >
                <X size={18} />
              </button>
            </div>

            <div className="modal-body space-y-4">
              {!processTrackId && (
                <div className="space-y-1">
                  <label className="text-sm font-medium">处理范围</label>
                  <div className="flex gap-4 pt-1">
                    <label className="flex items-center gap-2 text-sm cursor-pointer">
                      <input
                        type="radio"
                        name="scope"
                        checked={processScope === 'incomplete'}
                        onChange={() => setProcessScope('incomplete')}
                        className="accent-accent"
                      />
                      仅未完成音轨 ({overview.actionable_incomplete_count})
                    </label>
                    <label className="flex items-center gap-2 text-sm cursor-pointer">
                      <input
                        type="radio"
                        name="scope"
                        checked={processScope === 'all'}
                        onChange={() => setProcessScope('all')}
                        className="accent-accent"
                      />
                      全部可播放音轨 ({tracks.length})
                    </label>
                  </div>
                </div>
              )}

              <div className="space-y-1">
                <label className="text-sm font-medium">语音识别模型 (ASR)</label>
                <select
                  value={selectedAsrProfile}
                  onChange={(e) => setSelectedAsrProfile(e.target.value)}
                  className="input-text"
                >
                  {data.available_profiles?.asr_profiles?.map((p: any) => (
                    <option key={p.profile_id} value={p.profile_id}>
                      {p.name} ({p.provider || 'faster-whisper'})
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">翻译模型 (LLM)</label>
                <select
                  value={selectedLlmProfile}
                  onChange={(e) => setSelectedLlmProfile(e.target.value)}
                  className="input-text"
                >
                  {data.available_profiles?.llm_profiles?.map((p: any) => (
                    <option key={p.profile_id} value={p.profile_id}>
                      {p.name} ({p.model})
                    </option>
                  ))}
                </select>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  onClick={() => setProcessModalOpen(false)}
                  className="btn btn-secondary"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleStartProcess}
                  className="btn btn-primary"
                >
                  开始处理任务
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
