import React, { useEffect, useState } from 'react'
import { Users, Plus, Edit2, Trash2, Search, Mic, Building2 } from 'lucide-react'
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
    <div className="page-container space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">创作者管理</h1>
          <p className="text-sm text-fg-dim mt-0.5">
            分类管理音声声优 (CV) 与社团组织，维护作品关联关系
          </p>
        </div>

        <button
          type="button"
          onClick={() => setAddOpen(true)}
          className="btn btn-primary flex items-center gap-1.5"
        >
          <Plus size={16} /> 添加创作者
        </button>
      </div>

      {/* Controls */}
      <div className="bg-panel p-4 rounded-xl border border-line flex flex-wrap gap-4 items-center justify-between">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setCurrentKind('all')}
            className={`tab-btn text-xs ${currentKind === 'all' ? 'active' : ''}`}
          >
            全部 ({creators.length})
          </button>
          <button
            type="button"
            onClick={() => setCurrentKind('voice_actor')}
            className={`tab-btn text-xs flex items-center gap-1 ${currentKind === 'voice_actor' ? 'active' : ''}`}
          >
            <Mic size={14} /> 声优 (
            {creators.filter((c) => c.kind === 'voice_actor').length})
          </button>
          <button
            type="button"
            onClick={() => setCurrentKind('circle')}
            className={`tab-btn text-xs flex items-center gap-1 ${currentKind === 'circle' ? 'active' : ''}`}
          >
            <Building2 size={14} /> 社团 (
            {creators.filter((c) => c.kind === 'circle').length})
          </button>
        </div>

        <div className="relative min-w-[200px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-dim" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索创作者名称..."
            className="input-text text-sm pl-8"
          />
        </div>
      </div>

      {/* Creators Grid */}
      {loading ? (
        <div className="text-center py-20 text-fg-dim text-sm">加载创作者列表中...</div>
      ) : filtered.length === 0 ? (
        <div className="empty-state py-16 text-sm text-fg-dim">暂无匹配的创作者</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {filtered.map((c) => (
            <div
              key={c.creator_id}
              className="p-3.5 bg-panel rounded-xl border border-line flex items-center justify-between gap-3"
            >
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <div className="w-8 h-8 rounded-full bg-panel-2 border border-line flex items-center justify-center text-fg-dim flex-none">
                  {c.kind === 'voice_actor' ? <Mic size={16} /> : <Building2 size={16} />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="font-semibold text-sm text-white truncate">{c.name}</div>
                  <div className="text-xs text-fg-dim">
                    关联 {c.item_count || 0} 部作品 · {c.kind === 'voice_actor' ? '声优' : '社团'}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => {
                    setRenameTarget(c)
                    setEditName(c.name)
                  }}
                  className="p-1.5 text-fg-dim hover:text-white"
                  title="重命名"
                >
                  <Edit2 size={15} />
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(c)}
                  className="p-1.5 text-fg-dim hover:text-red-400"
                  title="删除"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

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
                  className="btn btn-secondary"
                >
                  取消
                </button>
                <button type="submit" className="btn btn-primary">
                  保存名称
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
