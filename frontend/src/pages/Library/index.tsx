import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Search,
  Plus,
  FolderPlus,
  Globe,
  Play,
  Tag,
  Clock,
  Layers,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { api } from '../../api/client'
import type { Item, Creator } from '../../types'
import { usePlayer } from '../../context/PlayerContext'
import { ImportModal } from './ImportModal'
import { ImportFolderModal } from './ImportFolderModal'
import { ImportUrlModal } from './ImportUrlModal'

export function LibraryPage() {
  const [items, setItems] = useState<Item[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [limit] = useState(12)
  const [totalPages, setTotalPages] = useState(1)
  const [search, setSearch] = useState('')
  const [selectedTag, setSelectedTag] = useState('')
  const [selectedCreatorId, setSelectedCreatorId] = useState('')
  const [sortBy, setSortBy] = useState('created_desc')
  const [allTags, setAllTags] = useState<string[]>([])
  const [allCreators, setAllCreators] = useState<Creator[]>([])
  const [loading, setLoading] = useState(true)

  const [importSingleOpen, setImportSingleOpen] = useState(false)
  const [importFolderOpen, setImportFolderOpen] = useState(false)
  const [importUrlOpen, setImportUrlOpen] = useState(false)

  const { playTrack } = usePlayer()

  const fetchItems = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('page', String(page))
      params.set('limit', String(limit))
      params.set('sort', sortBy)
      if (search.trim()) params.set('q', search.trim())
      if (selectedTag) params.set('tag', selectedTag)
      if (selectedCreatorId) params.set('creator', selectedCreatorId)

      const res = await api.get<{
        items: Item[]
        total: number
        page: number
        total_pages: number
        all_tags: string[]
        all_creators: Creator[]
      }>(`/api/library/items?${params.toString()}`)

      setItems(res.items || [])
      setTotal(res.total || 0)
      setTotalPages(res.total_pages || 1)
      setAllTags(res.all_tags || [])
      setAllCreators(res.all_creators || [])
    } catch (err) {
      console.error('Failed to fetch items:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchItems()
  }, [page, sortBy, selectedTag, selectedCreatorId])

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setPage(1)
    fetchItems()
  }

  const handlePlayFirstTrack = async (e: React.MouseEvent, item: Item) => {
    e.preventDefault()
    e.stopPropagation()
    try {
      const detail = await api.get<{ tracks: any[] }>(`/api/items/${item.item_id}`)
      if (detail.tracks && detail.tracks.length > 0) {
        const firstPlayable = detail.tracks.find((t) => t.has_media) || detail.tracks[0]
        playTrack(item, firstPlayable)
      }
    } catch (err) {
      console.error('Failed to play first track:', err)
    }
  }

  return (
    <div className="page-container space-y-6">
      {/* Header & Controls */}
      <div className="page-header flex flex-wrap justify-between items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">作品库</h1>
          <p className="text-sm text-fg-dim mt-0.5">
            共 {total} 部作品 · 本地 ASMR 与同人音声媒体库
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setImportSingleOpen(true)}
            className="btn btn-secondary flex items-center gap-1.5"
          >
            <Plus size={16} />
            导入音频
          </button>
          <button
            type="button"
            onClick={() => setImportFolderOpen(true)}
            className="btn btn-secondary flex items-center gap-1.5"
          >
            <FolderPlus size={16} />
            导入文件夹
          </button>
          <button
            type="button"
            onClick={() => setImportUrlOpen(true)}
            className="btn btn-primary flex items-center gap-1.5"
          >
            <Globe size={16} />
            从链接导入
          </button>
        </div>
      </div>

      {/* Search & Filter Bar */}
      <div className="bg-panel p-4 rounded-xl border border-line space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <form onSubmit={handleSearchSubmit} className="flex-1 min-w-[240px] relative">
            <Search
              size={18}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-dim"
            />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索标题、RJ号、声优..."
              className="input-text pl-9 w-full"
            />
          </form>

          <div className="flex items-center gap-2">
            <select
              value={selectedCreatorId}
              onChange={(e) => {
                setSelectedCreatorId(e.target.value)
                setPage(1)
              }}
              className="input-text w-auto text-sm"
            >
              <option value="">全部创作者</option>
              {allCreators.map((c) => (
                <option key={c.creator_id} value={c.creator_id}>
                  {c.name} ({c.item_count || 0})
                </option>
              ))}
            </select>

            <select
              value={sortBy}
              onChange={(e) => {
                setSortBy(e.target.value)
                setPage(1)
              }}
              className="input-text w-auto text-sm"
            >
              <option value="created_desc">最新添加</option>
              <option value="created_asc">最早添加</option>
              <option value="title_asc">标题升序</option>
              <option value="title_desc">标题降序</option>
              <option value="duration_desc">时长最长</option>
              <option value="duration_asc">时长最短</option>
            </select>
          </div>
        </div>

        {allTags.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 pt-1 text-xs">
            <span className="text-fg-faint flex items-center gap-1">
              <Tag size={12} /> 标签:
            </span>
            <button
              type="button"
              onClick={() => {
                setSelectedTag('')
                setPage(1)
              }}
              className={`tag-chip ${!selectedTag ? 'active' : ''}`}
            >
              全部
            </button>
            {allTags.slice(0, 15).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => {
                  setSelectedTag(selectedTag === t ? '' : t)
                  setPage(1)
                }}
                className={`tag-chip ${selectedTag === t ? 'active' : ''}`}
              >
                {t}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Work Cards Grid */}
      {loading ? (
        <div className="text-center py-20 text-fg-dim text-sm">正在加载作品库...</div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <p className="text-fg-dim text-base">暂无符合条件的作品</p>
          <p className="text-fg-faint text-xs mt-1">可以通过上方按钮导入音频或扫描本地作品目录</p>
        </div>
      ) : (
        <div className="works-grid">
          {items.map((item) => (
            <Link
              key={item.item_id}
              to={`/items/${item.item_id}`}
              className="work-card group"
            >
              <div className="work-cover-wrapper">
                <img
                  src={item.cover_url}
                  alt={item.title}
                  loading="lazy"
                  className="work-cover-img"
                  onError={(e) => {
                    ;(e.target as HTMLElement).style.opacity = '0.3'
                  }}
                />
                {item.rj_code && (
                  <span className="rj-badge">{item.rj_code}</span>
                )}
                <button
                  type="button"
                  onClick={(e) => handlePlayFirstTrack(e, item)}
                  className="card-play-overlay-btn"
                  title="立即播放"
                >
                  <Play size={20} className="ml-0.5" />
                </button>
                {item.subtitle_status === 'bilingual' && (
                  <span className="sub-status-pill pill-bilingual">双语</span>
                )}
                {item.subtitle_status === 'zh' && (
                  <span className="sub-status-pill pill-zh">中字</span>
                )}
                {item.subtitle_status === 'jp' && (
                  <span className="sub-status-pill pill-jp">日字</span>
                )}
              </div>

              <div className="work-meta">
                <h3 className="work-title" title={item.title}>
                  {item.title}
                </h3>

                <div className="work-creators truncate">
                  {item.creators && item.creators.length > 0 ? (
                    item.creators.map((c) => c.name).join(' / ')
                  ) : (
                    <span className="text-fg-faint">未知声优</span>
                  )}
                </div>

                <div className="work-stats-row">
                  <span className="flex items-center gap-1">
                    <Layers size={12} /> {item.track_count} 音轨
                  </span>
                  <span className="flex items-center gap-1">
                    <Clock size={12} /> {item.total_duration_label}
                  </span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="pagination-bar">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="page-btn"
          >
            <ChevronLeft size={16} /> 上一页
          </button>
          <span className="page-indicator text-sm text-fg-dim">
            第 {page} / {totalPages} 页
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="page-btn"
          >
            下一页 <ChevronRight size={16} />
          </button>
        </div>
      )}

      {/* Modals */}
      <ImportModal
        isOpen={importSingleOpen}
        onClose={() => setImportSingleOpen(false)}
        onSuccess={fetchItems}
        creators={allCreators}
      />
      <ImportFolderModal
        isOpen={importFolderOpen}
        onClose={() => setImportFolderOpen(false)}
        onSuccess={fetchItems}
      />
      <ImportUrlModal
        isOpen={importUrlOpen}
        onClose={() => setImportUrlOpen(false)}
        onSuccess={fetchItems}
        creators={allCreators}
      />
    </div>
  )
}
