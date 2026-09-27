import { useEffect, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { ArrowLeft, X, Sparkles } from 'lucide-react'
import { api } from '../../api/client'
import type { ItemDetailData } from '../../types'
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
    <>
      <Link className="back-link" to="/">← 返回作品库</Link>

      <section className="work-hero">
        <div className="work-hero-left">
          <div className={`work-hero-cover ${item.kind === 'rj_work' ? 'cover-rj' : 'cover-stream'}`}>
            <img
              className="work-cover-img"
              src={item.cover_url}
              alt=""
              loading="lazy"
              onError={(e) => ((e.target as HTMLElement).style.display = 'none')}
            />
            <span className="work-kind">{item.kind === 'rj_work' ? 'RJ' : 'LIVE'}</span>
          </div>
        </div>

        <div className="work-hero-info">
          <h1>{item.title}</h1>
          <div className="work-meta">
            {item.rj_code && (
              <a
                className="chip chip-rj"
                href={dlsiteUrl || '#'}
                target="_blank"
                rel="noreferrer"
              >
                {item.rj_code}
              </a>
            )}
            {item.creators &&
              item.creators.map((c) => (
                <span key={c.creator_id} className={`creator-tag creator-tag-${c.kind}`}>
                  {c.name}
                </span>
              ))}
            <span className="chip chip-tracks">{tracks.length} 音轨</span>
          </div>

          <div className="status-summary">
            <h3 className="dash-h2">音轨状态</h3>
            <div className="status-bars">
              <div className="status-bar-row sc-playable">
                <span className="status-label"><span className="status-dot"></span>已完成字幕</span>
                <div className="status-bar-track">
                  <div
                    className="status-bar-fill"
                    style={{ width: `${tracks.length ? (overview.playable_count / tracks.length) * 100 : 0}%` }}
                  />
                </div>
                <span className="status-count">{overview.playable_count}</span>
              </div>
            </div>
          </div>
        </div>

        <div className="work-hero-actions">
          {overview.first_playable_track_id && (
            <button
              type="button"
              className="small work-action-button work-action-primary work-action-play"
              onClick={() => {
                const track = tracks.find((t) => t.track_id === overview.first_playable_track_id)
                if (track) playTrack(item, track)
              }}
            >
              ▶ 开始播放
            </button>
          )}
          <button
            type="button"
            className="small work-action-button work-action-settings"
            onClick={() => {
              setProcessTrackId(null)
              setProcessScope('incomplete')
              setProcessModalOpen(true)
            }}
          >
            处理未完成音轨
          </button>
          <button
            type="button"
            className="small work-action-button work-edit-button work-action-edit"
            onClick={handleOpenEdit}
          >
            编辑作品
          </button>
          <button
            type="button"
            className="small work-action-button"
            onClick={handleReplaceCover}
          >
            更换封面
          </button>
          <button
            type="button"
            className="small work-action-button danger"
            onClick={handleDeleteItem}
          >
            删除作品
          </button>
        </div>
      </section>

      <section className="item-overview work-overview-below">
        <h2 className="dash-h2">概览</h2>
        <div className="stats-grid">
          <div className="stat-card">
            <span className="stat-num">{overview.track_count}</span>
            <span className="stat-label">音轨</span>
          </div>
          <div className="stat-card">
            <span className="stat-num">{overview.total_duration_label}</span>
            <span className="stat-label">总时长</span>
          </div>
          <div className="stat-card">
            <span className="stat-num">{(overview.total_size / 1048576).toFixed(1)} MB</span>
            <span className="stat-label">总大小</span>
          </div>
          <div className="stat-card">
            <span className="stat-num">{overview.playable_count}</span>
            <span className="stat-label">可播放</span>
          </div>
          <div className="stat-card">
            <span className="stat-num">{overview.processing_count}</span>
            <span className="stat-label">处理中</span>
          </div>
          <div className="stat-card">
            <span className="stat-num small">{overview.failed_count}</span>
            <span className="stat-label">失败</span>
          </div>
        </div>
      </section>

      <section style={{ marginTop: 24 }}>
        <h2 className="dash-h2" style={{ marginBottom: 12 }}>音轨列表 ({tracks.length})</h2>
        <div className="tracks-list" style={{ display: 'grid', gap: 8 }}>
          {tracks.map((track) => (
            <article key={track.track_id} className="track-row" data-track-id={track.track_id}>
              <span className={`status-badge status-${track.status}`}>{track.status}</span>
              <span className="track-duration">{track.duration_label}</span>
              <span className="track-size">{(track.size / 1048576).toFixed(1)} MB</span>
              <span className="track-subs">
                {track.has_source_sub ? <span className="chip sub-ok">源语 ✓</span> : <span className="chip sub-none">源语 –</span>}
                {track.has_target_sub ? <span className="chip sub-ok">译 ✓</span> : <span className="chip sub-none">译 –</span>}
              </span>
              <span style={{ flex: 1, minWidth: 0, fontWeight: 600 }} className="truncate">
                {track.title}
              </span>
              <button
                type="button"
                className="menu-action"
                onClick={() => playTrack(item, track)}
              >
                ▶ 就地播放
              </button>
              <Link to={`/tracks/${track.track_id}/play`} className="menu-action">
                打开播放页
              </Link>
              <button
                type="button"
                className="menu-action"
                onClick={() => {
                  setProcessTrackId(track.track_id)
                  setProcessModalOpen(true)
                }}
              >
                处理…
              </button>
              {track.has_target_sub && (
                <a
                  href={`/api/tracks/${track.track_id}/subtitles/zh/download`}
                  download
                  className="menu-action"
                >
                  下载字幕
                </a>
              )}
              <button
                type="button"
                className="menu-action danger"
                onClick={() => handleDeleteTrack(track.track_id)}
              >
                删除音轨
              </button>
            </article>
          ))}
        </div>
      </section>

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
    </>
  )
}
