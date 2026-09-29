import React, { useState, useEffect, useMemo } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  Search,
  Plus,
  FolderPlus,
  Download,
  LayoutGrid,
  List,
  Play,
  ChevronLeft,
  ChevronRight,
  X,
} from 'lucide-react'
import { api } from '../../api/client'
import type { Item, Creator } from '../../types'
import { usePlayer } from '../../context/PlayerContext'
import { ImportModal } from './ImportModal'
import { ImportFolderModal } from './ImportFolderModal'
import { ImportUrlModal } from './ImportUrlModal'
import { WorkCard } from '../../components/WorkCard'

function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const idx = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, idx)).toFixed(1)} ${units[idx]}`
}

export function LibraryPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { playTrack } = usePlayer()

  const [items, setItems] = useState<Item[]>([])
  const [creators, setCreators] = useState<Creator[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCreator, setSelectedCreator] = useState(() => searchParams.get('creator') || searchParams.get('creator_id') || '')
  const [selectedTag, setSelectedTag] = useState(() => searchParams.get('tag') || '')
  const [subFilter, setSubFilter] = useState<'all' | 'bilingual' | 'zh' | 'jp' | 'none'>('all')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [totalCount, setTotalCount] = useState(0)

  // Modals
  const [importOpen, setImportOpen] = useState(false)
  const [folderOpen, setFolderOpen] = useState(false)
  const [urlOpen, setUrlOpen] = useState(false)

  // Continue listening state
  const [recentTrack, setRecentTrack] = useState<{
    item: Item
    track: any
    position: number
    duration: number
  } | null>(null)

  const loadItems = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('page', String(page))
      params.set('limit', '18')
      if (searchQuery.trim()) params.set('q', searchQuery.trim())
      if (selectedCreator) params.set('creator', selectedCreator)
      if (selectedTag) params.set('tag', selectedTag)

      const res = await api.get<{
        items: Item[]
        total: number
        page: number
        pages: number
      }>(`/api/library/items?${params.toString()}`)
      setItems(res.items || [])
      setTotalPages(res.pages || 1)
      setTotalCount(res.total || 0)
    } catch (err) {
      console.error('Failed to load library items:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadItems()
  }, [page, searchQuery, selectedCreator, selectedTag])

  useEffect(() => {
    const c = searchParams.get('creator') || searchParams.get('creator_id') || ''
    if (c !== selectedCreator) setSelectedCreator(c)
    const t = searchParams.get('tag') || ''
    if (t !== selectedTag) setSelectedTag(t)
    const q = searchParams.get('q') || searchParams.get('search') || ''
    if (q && q !== searchQuery) setSearchQuery(q)
  }, [searchParams])

  useEffect(() => {
    api.get<any>('/api/creators/list')
      .then((res) => {
        const list = Array.isArray(res) ? res : (res.creators || res.all_creators || [])
        setCreators(list)
      })
      .catch(() => {})

    try {
      const saved = localStorage.getItem('sf.recent_listen')
      if (saved) {
        const parsed = JSON.parse(saved)
        if (parsed.item && parsed.track) {
          setRecentTrack(parsed)
        }
      }
    } catch {}
  }, [])

  const filteredItems = useMemo(() => {
    if (subFilter === 'all') return items
    return items.filter((item) => item.subtitle_status === subFilter)
  }, [items, subFilter])

  const handleQuickPlay = async (e: React.MouseEvent, item: Item) => {
    e.preventDefault()
    e.stopPropagation()
    try {
      const detail = await api.get<{ tracks: any[] }>(`/api/items/${item.item_id}`)
      const playable = detail.tracks.find((t) => t.has_media && t.status !== 'failed') || detail.tracks[0]
      if (playable) {
        playTrack(item, playable)
      } else {
        navigate(`/items/${item.item_id}`)
      }
    } catch {
      navigate(`/items/${item.item_id}`)
    }
  }

  const handleResumeRecent = () => {
    if (recentTrack) {
      playTrack(recentTrack.item, recentTrack.track, recentTrack.position)
    }
  }

  const handleDismissRecent = (e: React.MouseEvent) => {
    e.stopPropagation()
    setRecentTrack(null)
    localStorage.removeItem('sf.recent_listen')
  }

  return (
    <div className="library-container">
      {/* Header & Main Actions */}
      <div className="page-header">
        <div className="page-title-wrap">
          <h1 className="page-title">作品库</h1>
          <span className="page-subtitle">
            共 {totalCount} 部音声作品，支持本地 RJ 音声管理、双语字幕播放与流式转写
          </span>
        </div>

        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button type="button" className="btn btn-primary" onClick={() => setImportOpen(true)}>
            <Plus size={16} />
            导入音频
          </button>
          <button type="button" className="btn" onClick={() => setFolderOpen(true)}>
            <FolderPlus size={16} />
            扫描目录
          </button>
          <button type="button" className="btn" onClick={() => setUrlOpen(true)}>
            <Download size={16} />
            从链接导入
          </button>
        </div>
      </div>

      {/* Continue Listening Shelf */}
      {recentTrack && (
        <div className="continue-card" onClick={handleResumeRecent} style={{ cursor: 'pointer' }}>
          <div className="continue-cover">
            <img
              src={recentTrack.item.cover_url || '/covers/default'}
              alt=""
              onError={(e) => ((e.target as HTMLElement).style.opacity = '0.3')}
            />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--accent-base)' }}>
                继续收听
              </span>
              <span className="chip chip-rj">{recentTrack.item.rj_code || 'ASMR'}</span>
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#fff', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {recentTrack.track.title}
            </div>
            <div style={{ fontSize: 12, color: 'var(--fg-dim)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {recentTrack.item.title}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button type="button" className="btn btn-primary btn-sm" onClick={handleResumeRecent}>
              <Play size={13} fill="currentColor" />
              恢复播放
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-circle btn-sm"
              onClick={handleDismissRecent}
              title="移除"
            >
              <X size={15} />
            </button>
          </div>
        </div>
      )}

      {/* Filter and View Toolbar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 16,
          marginBottom: 20,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flex: 1, minWidth: 260 }}>
          <div style={{ position: 'relative', width: 260 }}>
            <Search
              size={15}
              style={{ position: 'absolute', left: 10, top: 10, color: 'var(--fg-faint)' }}
            />
            <input
              type="text"
              className="input-field"
              style={{ paddingLeft: 32 }}
              placeholder="搜索标题、RJ 号、原名…"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value)
                setPage(1)
              }}
            />
          </div>

          <select
            className="select-field"
            value={selectedCreator}
            onChange={(e) => {
              setSelectedCreator(e.target.value)
              setPage(1)
            }}
          >
            <option value="">全部创作者 ({creators.length})</option>
            {creators.map((c) => (
              <option key={c.creator_id} value={c.creator_id}>
                {c.kind === 'voice_actor' ? '🎙️ ' : '🏢 '}
                {c.name} {c.item_count ? `(${c.item_count})` : ''}
              </option>
            ))}
          </select>

          {selectedTag && (
            <span
              className="btn btn-sm btn-ghost"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: 'var(--accent-soft)', color: 'var(--accent-base)' }}
              title="点击清除标签筛选"
              onClick={() => setSelectedTag('')}
            >
              标签: {selectedTag} <X size={13} />
            </span>
          )}
        </div>

        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          {/* Subtitle status pills */}
          <div style={{ display: 'flex', gap: 6 }}>
            {[
              { key: 'all', label: '全部' },
              { key: 'bilingual', label: '双语已就绪 ✓' },
              { key: 'zh', label: '仅中字' },
              { key: 'jp', label: '仅日文' },
              { key: 'none', label: '未转写' },
            ].map((p) => (
              <button
                key={p.key}
                type="button"
                className={`btn btn-sm ${subFilter === p.key ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setSubFilter(p.key as any)}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* View toggle */}
          <div style={{ display: 'flex', background: 'rgba(255, 255, 255, 0.05)', borderRadius: 'var(--radius-sm)', padding: 2 }}>
            <button
              type="button"
              className={`btn btn-sm ${viewMode === 'grid' ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setViewMode('grid')}
              title="海报网格视图"
            >
              <LayoutGrid size={15} />
            </button>
            <button
              type="button"
              className={`btn btn-sm ${viewMode === 'list' ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setViewMode('list')}
              title="详细列表视图"
            >
              <List size={15} />
            </button>
          </div>
        </div>
      </div>

      {/* Main Works View */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-dim)' }}>
          <p>正在载入作品库…</p>
        </div>
      ) : filteredItems.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-dim)' }}>
          <p>暂无符合条件的作品</p>
          <small style={{ color: 'var(--fg-faint)', marginTop: 8, display: 'block' }}>
            可通过右上角按钮导入本地音频或扫描作品目录
          </small>
        </div>
      ) : viewMode === 'list' ? (
        <div className="works-table-container">
          <table className="works-table">
            <thead>
              <tr>
                <th style={{ width: 60 }}>封面</th>
                <th>标题 / RJ 号</th>
                <th>创作者</th>
                <th>字幕状态</th>
                <th>大小</th>
                <th style={{ textAlign: 'right', width: 140 }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredItems.map((item) => (
                <tr key={item.item_id}>
                  <td>
                    <Link to={`/items/${item.item_id}`} style={{ display: 'block', width: 44, height: 44, borderRadius: 6, overflow: 'hidden' }}>
                      <img
                        src={item.cover_url || '/covers/default'}
                        alt=""
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                        onError={(e) => ((e.target as HTMLElement).style.opacity = '0.3')}
                      />
                    </Link>
                  </td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Link
                        to={`/items/${item.item_id}`}
                        style={{ fontWeight: 600, color: 'var(--fg-main)' }}
                        title={item.title}
                      >
                        {item.title}
                      </Link>
                      {item.rj_code && <span className="chip chip-rj">{item.rj_code}</span>}
                    </div>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {item.creators &&
                        item.creators.slice(0, 2).map((c) => (
                          <span
                            key={c.creator_id}
                            className={`chip ${c.kind === 'voice_actor' ? 'chip-creator' : 'chip-circle'}`}
                          >
                            {c.name}
                          </span>
                        ))}
                    </div>
                  </td>
                  <td>
                    {item.subtitle_status === 'bilingual' && (
                      <span className="sub-badge sub-bilingual">双语 ✓</span>
                    )}
                    {item.subtitle_status === 'zh' && (
                      <span className="sub-badge sub-zh">中字 ✓</span>
                    )}
                    {item.subtitle_status === 'jp' && (
                      <span className="sub-badge sub-jp">日字 ✓</span>
                    )}
                    {item.subtitle_status === 'none' && (
                      <span className="sub-badge sub-none">未转写</span>
                    )}
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--fg-dim)' }}>
                    {formatBytes(item.total_size)}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center' }}>
                      <button
                        type="button"
                        className="btn btn-sm btn-primary btn-circle"
                        onClick={(e) => handleQuickPlay(e, item)}
                        title="快捷播放"
                      >
                        <Play size={13} fill="currentColor" />
                      </button>
                      <Link to={`/items/${item.item_id}`} className="btn btn-sm btn-ghost">
                        详情
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="works-grid">
          {filteredItems.map((item) => (
            <WorkCard
              key={item.item_id}
              item={item}
              onQuickPlay={(e, it) => handleQuickPlay(e, it)}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, marginTop: 36 }}>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            <ChevronLeft size={16} />
            上一页
          </button>
          <span style={{ fontSize: 13, color: 'var(--fg-dim)' }}>
            第 {page} / {totalPages} 页
          </span>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          >
            下一页
            <ChevronRight size={16} />
          </button>
        </div>
      )}

      {/* Modals */}
      <ImportModal
        isOpen={importOpen}
        onClose={() => setImportOpen(false)}
        onSuccess={() => loadItems()}
      />
      <ImportFolderModal
        isOpen={folderOpen}
        onClose={() => setFolderOpen(false)}
        onSuccess={() => loadItems()}
      />
      <ImportUrlModal
        isOpen={urlOpen}
        onClose={() => setUrlOpen(false)}
        onSuccess={() => {
          loadItems()
          navigate('/tasks')
        }}
      />
    </div>
  )
}
