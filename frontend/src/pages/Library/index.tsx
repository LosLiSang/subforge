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

  const formatSize = (bytes: number) => {
    if (!bytes) return '0 MB'
    return `${(bytes / 1048576).toFixed(1)} MB`
  }

  return (
    <>
      <section className="works-head">
        <h1>作品库</h1>
        <div className="library-toolbar">
          <input
            id="work-search"
            className="works-search"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                setPage(1)
                fetchItems()
              }
            }}
            placeholder="搜索标题 / RJ 号…"
            aria-label="搜索作品"
          />

          {allCreators.length > 0 && (
            <select
              value={selectedCreatorId}
              onChange={(e) => {
                setSelectedCreatorId(e.target.value)
                setPage(1)
              }}
              className="custom-select-trigger"
              style={{ width: 'auto', padding: '6px 12px' }}
            >
              <option value="">全部创作者</option>
              {allCreators.map((c) => (
                <option key={c.creator_id} value={c.creator_id}>
                  {c.name} ({c.item_count || 0})
                </option>
              ))}
            </select>
          )}

          <div className="works-actions">
            <button
              type="button"
              onClick={() => setImportSingleOpen(true)}
              id="pick-audio"
            >
              <svg
                className="btn-ic"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                aria-hidden="true"
              >
                <path d="M12 5v14M5 12h14" />
              </svg>
              导入
            </button>
            <button
              type="button"
              onClick={() => setImportFolderOpen(true)}
              className="ghost small"
              title="导入 RJ 文件夹"
            >
              文件夹
            </button>
            <button
              type="button"
              onClick={() => setImportUrlOpen(true)}
              className="ghost small"
              title="从链接下载导入"
            >
              链接
            </button>
          </div>
        </div>
      </section>

      {loading ? (
        <div className="empty" style={{ padding: '60px 0', textAlign: 'center' }}>
          <p>正在加载作品库…</p>
        </div>
      ) : items.length === 0 ? (
        <div className="empty" style={{ padding: '60px 0', textAlign: 'center' }}>
          <p>暂无符合条件的作品</p>
          <small style={{ color: 'var(--fg-faint)', marginTop: 6, display: 'block' }}>
            可以通过上方按钮导入音频或扫描本地作品目录
          </small>
        </div>
      ) : (
        <div className="works-grid">
          {items.map((item) => (
            <Link key={item.item_id} to={`/items/${item.item_id}`} className="work-card">
              <div className={`work-cover ${item.kind === 'rj_work' ? 'cover-rj' : 'cover-stream'}`}>
                <img
                  src={item.cover_url}
                  alt=""
                  loading="lazy"
                  className="work-cover-img"
                  onError={(e) => {
                    ;(e.target as HTMLElement).style.opacity = '0.3'
                  }}
                />
                <span className="work-kind">
                  {item.rj_code || (item.kind === 'rj_work' ? 'RJ' : 'LIVE')}
                </span>
                <span className="work-size">{formatSize(item.total_size)}</span>
              </div>

              <div className="work-body">
                <h2>{item.title}</h2>
                <div className="work-meta">
                  {item.creators &&
                    item.creators.slice(0, 2).map((c) => (
                      <span key={c.creator_id} className={`creator-tag creator-tag-${c.kind}`}>
                        {c.name}
                      </span>
                    ))}
                  {item.subtitle_status === 'bilingual' && <span className="chip sub-ok">双语 ✓</span>}
                  {item.subtitle_status === 'zh' && <span className="chip sub-ok">中字 ✓</span>}
                  {item.subtitle_status === 'jp' && <span className="chip sub-ok">日字 ✓</span>}
                  {item.subtitle_status === 'none' && <span className="chip sub-none">未生成</span>}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <nav className="library-pagination">
          <span className="pagination-summary">
            共 {total} 部作品 · 第 {page} / {totalPages} 页
          </span>
          <div className="pagination-controls">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="pagination-nav"
            >
              上一页
            </button>
            {Array.from({ length: totalPages }).map((_, i) => (
              <button
                key={i + 1}
                type="button"
                className={`pagination-page ${page === i + 1 ? 'active' : ''}`}
                onClick={() => setPage(i + 1)}
              >
                {i + 1}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="pagination-nav"
            >
              下一页
            </button>
          </div>
        </nav>
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
    </>
  )
}
