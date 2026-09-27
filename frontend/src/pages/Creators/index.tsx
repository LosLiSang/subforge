import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import type { Creator } from '../../types'

export function CreatorsPage() {
  const [creators, setCreators] = useState<Creator[]>([])
  const [search, setSearch] = useState('')
  const [currentKind, setCurrentKind] = useState<'all' | 'voice_actor' | 'circle'>('all')
  const [loading, setLoading] = useState(true)

  // Add creator state
  const [addOpen, setAddOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newKind, setNewKind] = useState<'voice_actor' | 'circle'>('voice_actor')

  // Rename state
  const [renameTarget, setRenameTarget] = useState<Creator | null>(null)
  const [editName, setEditName] = useState('')

  const fetchCreators = async () => {
    setLoading(true)
    try {
      const data = await api.get<Creator[]>('/api/creators/list')
      setCreators(data || [])
    } catch (err) {
      console.error('Failed to fetch creators:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchCreators()
  }, [])

  const handleAddCreator = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newName.trim()) return
    try {
      await api.post('/api/creators', {
        name: newName.trim(),
        kind: newKind,
      })
      setAddOpen(false)
      setNewName('')
      fetchCreators()
    } catch (err: any) {
      alert('添加创作者失败: ' + err.message)
    }
  }

  const handleRename = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!renameTarget || !editName.trim()) return
    try {
      await api.post('/creators', {
        action: 'rename',
        creator_id: renameTarget.creator_id,
        name: editName.trim(),
      })
      setRenameTarget(null)
      fetchCreators()
    } catch (err: any) {
      alert('重命名失败: ' + err.message)
    }
  }

  const handleDelete = async (creator: Creator) => {
    if (!confirm(`确定要删除创作者 "${creator.name}" 吗？`)) return
    try {
      await api.post('/creators', {
        action: 'delete',
        creator_id: creator.creator_id,
      })
      fetchCreators()
    } catch (err: any) {
      alert('删除失败: ' + err.message)
    }
  }

  const filtered = creators.filter((c) => {
    if (currentKind !== 'all' && c.kind !== currentKind) return false
    if (search.trim() && !c.name.toLowerCase().includes(search.trim().toLowerCase())) return false
    return true
  })

  return (
    <>
      <div className="page-head">
        <div>
          <h1>创作者</h1>
          <p className="page-sub">
            分类管理音声声优 (CV) 与社团组织，维护作品关联关系
          </p>
        </div>

        <button
          type="button"
          onClick={() => setAddOpen(true)}
          className="primary"
        >
          <svg className="btn-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
          添加创作者
        </button>
      </div>

      <nav className="tab-bar creator-tabs" role="tablist">
        <button
          type="button"
          onClick={() => setCurrentKind('all')}
          className={`tab ${currentKind === 'all' ? 'active' : ''}`}
        >
          全部 ({creators.length})
        </button>
        <button
          type="button"
          onClick={() => setCurrentKind('voice_actor')}
          className={`tab ${currentKind === 'voice_actor' ? 'active' : ''}`}
        >
          声优 ({creators.filter((c) => c.kind === 'voice_actor').length})
        </button>
        <button
          type="button"
          onClick={() => setCurrentKind('circle')}
          className={`tab ${currentKind === 'circle' ? 'active' : ''}`}
        >
          社团 ({creators.filter((c) => c.kind === 'circle').length})
        </button>
      </nav>

      <section className="tab-panel active">
        <input
          type="search"
          className="creator-list-search"
          placeholder="搜索创作者…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ marginBottom: 16 }}
        />

        {loading ? (
          <p className="empty">加载创作者列表中…</p>
        ) : filtered.length === 0 ? (
          <p className="empty">暂无创作者数据。</p>
        ) : (
          <div className="creator-list">
            {filtered.map((c) => (
              <article
                key={c.creator_id}
                className="creator-row"
                data-creator-name={c.name}
              >
                <div className="creator-row-main">
                  <Link
                    className="creator-row-link"
                    to={`/?creator=${c.creator_id}`}
                    title="在作品库中筛选该创作者"
                  >
                    <span className={`creator-tag creator-tag-${c.kind}`}>{c.name}</span>
                  </Link>
                  <span>{c.item_count || 0} 部作品</span>
                </div>

                <div className="creator-row-menu-wrap" style={{ display: 'flex', gap: 6 }}>
                  <button
                    type="button"
                    className="ghost small"
                    onClick={() => {
                      setRenameTarget(c)
                      setEditName(c.name)
                    }}
                  >
                    修改
                  </button>
                  <button
                    type="button"
                    className="danger ghost small"
                    onClick={() => handleDelete(c)}
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* Add Modal */}
      {addOpen && (
        <div className="modal-backdrop">
          <div className="modal-dialog">
            <div className="modal-header">
              <h3 className="modal-title">添加创作者</h3>
            </div>
            <form onSubmit={handleAddCreator} className="modal-body space-y-4">
              <div className="space-y-1">
                <label className="text-sm font-medium">创作者名称</label>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="例: 秋野かえで"
                  className="input-text"
                  required
                />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">创作者类型</label>
                <select
                  value={newKind}
                  onChange={(e) => setNewKind(e.target.value as any)}
                  className="input-text"
                >
                  <option value="voice_actor">声优 (Voice Actor)</option>
                  <option value="circle">社团 (Circle)</option>
                </select>
              </div>
              <div className="modal-footer">
                <button
                  type="button"
                  onClick={() => setAddOpen(false)}
                  className="btn btn-secondary"
                >
                  取消
                </button>
                <button type="submit" className="btn btn-primary">
                  确认添加
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Rename Modal */}
      {renameTarget && (
        <div className="modal-backdrop">
          <div className="modal-dialog">
            <div className="modal-header">
              <h3 className="modal-title">重命名创作者</h3>
            </div>
            <form onSubmit={handleRename} className="modal-body space-y-4">
              <div className="space-y-1">
                <label className="text-sm font-medium">新名称</label>
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="input-text"
                  required
                />
              </div>
              <div className="modal-footer">
                <button
                  type="button"
                  onClick={() => setRenameTarget(null)}
                  className="ghost"
                >
                  取消
                </button>
                <button type="submit" className="primary">
                  保存名称
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  )
}
