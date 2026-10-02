import React, { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import {
  Plus,
  Search,
  User,
  Users,
  Edit2,
  Trash2,
  X,
  Settings,
  ArrowUpDown,
  GitMerge,
} from 'lucide-react'
import { api } from '../../api/client'
import type { Creator } from '../../types'

export function CreatorsPage() {
  const [creators, setCreators] = useState<Creator[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [kindFilter, setKindFilter] = useState<'voice_actor' | 'circle' | 'all'>('voice_actor')
  const [sortBy, setSortBy] = useState<'count_desc' | 'name_asc'>('count_desc')
  const [editMode, setEditMode] = useState(false)

  // Add creator modal
  const [modalOpen, setModalOpen] = useState(false)
  const [formName, setFormName] = useState('')
  const [formKind, setFormKind] = useState<'voice_actor' | 'circle'>('voice_actor')
  const [submitting, setSubmitting] = useState(false)

  // Rename modal
  const [renameTarget, setRenameTarget] = useState<Creator | null>(null)
  const [renameName, setRenameName] = useState('')
  const [submittingRename, setSubmittingRename] = useState(false)

  // Merge modal
  const [mergeSource, setMergeSource] = useState<Creator | null>(null)
  const [mergeTargetId, setMergeTargetId] = useState('')
  const [mergeFilterQuery, setMergeFilterQuery] = useState('')
  const [submittingMerge, setSubmittingMerge] = useState(false)

  const loadCreators = async () => {
    setLoading(true)
    try {
      const res = await api.get<any>('/api/creators/list')
      const list = Array.isArray(res) ? res : (res.creators || res.all_creators || [])
      setCreators(list)
    } catch (err) {
      console.error('Failed to load creators:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadCreators()
  }, [])

  const filtered = useMemo(() => {
    let list = creators.filter((c) => {
      if (kindFilter !== 'all' && c.kind !== kindFilter) return false
      if (searchQuery.trim() && !c.name.toLowerCase().includes(searchQuery.toLowerCase())) return false
      return true
    })

    return list.sort((a, b) => {
      if (sortBy === 'count_desc') {
        const countA = a.item_count || 0
        const countB = b.item_count || 0
        if (countB !== countA) return countB - countA
        return a.name.localeCompare(b.name, 'ja')
      } else {
        return a.name.localeCompare(b.name, 'ja')
      }
    })
  }, [creators, kindFilter, searchQuery, sortBy])

  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formName.trim()) return
    setSubmitting(true)
    try {
      const formData = new FormData()
      formData.append('name', formName.trim())
      formData.append('kind', formKind)
      await api.postForm('/api/creators', formData)
      setModalOpen(false)
      setFormName('')
      loadCreators()
    } catch (err: any) {
      alert('添加创作者失败: ' + err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleRenameSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!renameTarget || !renameName.trim()) return
    setSubmittingRename(true)
    try {
      const formData = new FormData()
      formData.append('action', 'rename')
      formData.append('creator_id', renameTarget.creator_id)
      formData.append('name', renameName.trim())
      await api.postForm('/creators', formData)
      setRenameTarget(null)
      loadCreators()
    } catch (err: any) {
      alert('重命名失败: ' + err.message)
    } finally {
      setSubmittingRename(false)
    }
  }

  const handleMergeSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!mergeSource || !mergeTargetId) return
    const target = creators.find((c) => c.creator_id === mergeTargetId)
    if (!target) return
    if (!window.confirm(`确定要将「${mergeSource.name}」合并到「${target.name}」吗？\n所有属于「${mergeSource.name}」的作品将自动转移至「${target.name}」，合并后「${mergeSource.name}」将被移除。`)) {
      return
    }
    setSubmittingMerge(true)
    try {
      const formData = new FormData()
      formData.append('action', 'merge')
      formData.append('source_id', mergeSource.creator_id)
      formData.append('target_id', mergeTargetId)
      await api.postForm('/creators', formData)
      setMergeSource(null)
      setMergeTargetId('')
      await loadCreators()
    } catch (err: any) {
      alert('合并创作者失败: ' + (err.message || '未知错误'))
    } finally {
      setSubmittingMerge(false)
    }
  }

  const handleDeleteCreator = async (e: React.MouseEvent, c: Creator) => {
    e.preventDefault()
    e.stopPropagation()
    if (!window.confirm(`确定要删除创作者「${c.name}」吗？`)) return
    try {
      const formData = new FormData()
      formData.append('action', 'delete')
      formData.append('creator_id', c.creator_id)
      await api.postForm('/creators', formData)
      loadCreators()
    } catch (err: any) {
      alert('删除创作者失败: ' + (err.message || '该创作者可能仍有关联作品'))
    }
  }

  const pageTitle =
    kindFilter === 'voice_actor'
      ? 'All vas'
      : kindFilter === 'circle'
      ? 'All circles'
      : 'All creators'

  const searchPlaceholder =
    kindFilter === 'voice_actor'
      ? 'Search for a vas...'
      : kindFilter === 'circle'
      ? 'Search for a circle...'
      : 'Search creators...'

  return (
    <div className="vas-page-container">
      {/* Top Header & Title matching asmr.one / Kikoeru */}
      <div className="vas-header-row">
        <div className="vas-title-group">
          <h1 className="vas-main-title">{pageTitle}</h1>
        </div>

        <div className="vas-type-tabs">
          <button
            type="button"
            className={`vas-tab ${kindFilter === 'voice_actor' ? 'active' : ''}`}
            onClick={() => setKindFilter('voice_actor')}
          >
            <User size={14} style={{ marginRight: 4 }} />
            声优 (All vas)
          </button>
          <button
            type="button"
            className={`vas-tab ${kindFilter === 'circle' ? 'active' : ''}`}
            onClick={() => setKindFilter('circle')}
          >
            <Users size={14} style={{ marginRight: 4 }} />
            社团 (Circles)
          </button>
          <button
            type="button"
            className={`vas-tab ${kindFilter === 'all' ? 'active' : ''}`}
            onClick={() => setKindFilter('all')}
          >
            全部 ({creators.length})
          </button>
        </div>

        <div className="vas-header-actions">
          <button
            type="button"
            className={`btn btn-sm ${editMode ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setEditMode(!editMode)}
            title="切换管理模式（重命名/删除）"
          >
            <Settings size={14} />
            {editMode ? '完成编辑' : '管理'}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => {
              setFormKind(kindFilter === 'circle' ? 'circle' : 'voice_actor')
              setModalOpen(true)
            }}
          >
            <Plus size={15} />
            新建创作者
          </button>
        </div>
      </div>

      {/* Wide Search Bar matching asmr.one / Kikoeru Image #2 */}
      <div className="vas-search-bar-wrap">
        <input
          type="text"
          className="vas-search-input"
          placeholder={searchPlaceholder}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          autoComplete="off"
          spellCheck="false"
        />
        <div className="vas-search-icon-wrap">
          <Search size={18} />
        </div>
      </div>

      {/* Sub toolbar: count info and sorting */}
      <div className="vas-sub-toolbar">
        <span className="vas-count-label">
          共匹配到 <strong>{filtered.length}</strong> 位创作者
        </span>
        <div className="vas-sort-group">
          <ArrowUpDown size={13} style={{ color: 'var(--fg-faint)' }} />
          <button
            type="button"
            className={`vas-sort-btn ${sortBy === 'count_desc' ? 'active' : ''}`}
            onClick={() => setSortBy('count_desc')}
          >
            按作品数排序
          </button>
          <span style={{ color: 'var(--border-subtle)' }}>|</span>
          <button
            type="button"
            className={`vas-sort-btn ${sortBy === 'name_asc' ? 'active' : ''}`}
            onClick={() => setSortBy('name_asc')}
          >
            按名称排序
          </button>
        </div>
      </div>

      {/* 4-column Table/Grid matching Image #2 */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-dim)' }}>
          <p>正在载入创作者列表…</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="vas-empty-state">
          <p>未找到匹配的创作者</p>
          <small style={{ color: 'var(--fg-faint)', marginTop: 6 }}>
            可以尝试更换搜索关键词，或点击右上角新建创作者
          </small>
        </div>
      ) : (
        <div className="vas-grid-container">
          {filtered.map((c) => (
            <div key={c.creator_id} className="vas-cell-item">
              <Link
                to={`/?creator=${c.creator_id}`}
                className="vas-item-link"
                title={`查看 ${c.name} 的所有作品 (${c.item_count || 0})`}
              >
                <span className="vas-name">{c.name}</span>
                <span className="vas-badge-count">{c.item_count || 0}</span>
              </Link>

              {editMode && (
                <div className="vas-cell-actions">
                  <button
                    type="button"
                    className="vas-cell-btn"
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      setRenameTarget(c)
                      setRenameName(c.name)
                    }}
                    title="重命名"
                  >
                    <Edit2 size={12} />
                  </button>
                  <button
                    type="button"
                    className="vas-cell-btn"
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      setMergeSource(c)
                      setMergeTargetId('')
                      setMergeFilterQuery('')
                    }}
                    title="合并到其他创作者…"
                  >
                    <GitMerge size={12} />
                  </button>
                  <button
                    type="button"
                    className="vas-cell-btn vas-cell-btn-delete"
                    onClick={(e) => handleDeleteCreator(e, c)}
                    title="删除"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="vas-footer-id">
        <span>7fc0f47a</span>
      </div>

      {/* Add Modal */}
      {modalOpen && (
        <div className="modal-overlay" onClick={() => setModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">新建创作者</h3>
              <button
                type="button"
                className="btn btn-ghost btn-circle"
                onClick={() => setModalOpen(false)}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleAddSubmit}>
              <div className="modal-body">
                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                    创作者类型
                  </label>
                  <div style={{ display: 'flex', gap: 16 }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                      <input
                        type="radio"
                        name="formKind"
                        checked={formKind === 'voice_actor'}
                        onChange={() => setFormKind('voice_actor')}
                      />
                      声优 (Voice Actor)
                    </label>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                      <input
                        type="radio"
                        name="formKind"
                        checked={formKind === 'circle'}
                        onChange={() => setFormKind('circle')}
                      />
                      制作社团 (Circle)
                    </label>
                  </div>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                    创作者姓名 / 社团名 *
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="例如: 陽向葵ゅか, 柚木つばめ, 或 社团名"
                    required
                    autoFocus
                  />
                </div>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setModalOpen(false)}
                  disabled={submitting}
                >
                  取消
                </button>
                <button type="submit" className="btn btn-primary" disabled={submitting || !formName.trim()}>
                  {submitting ? '正在创建…' : '确认创建'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Rename Modal */}
      {renameTarget && (
        <div className="modal-overlay" onClick={() => setRenameTarget(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">重命名创作者</h3>
              <button
                type="button"
                className="btn btn-ghost btn-circle"
                onClick={() => setRenameTarget(null)}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleRenameSubmit}>
              <div className="modal-body">
                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                    新名称 *
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={renameName}
                    onChange={(e) => setRenameName(e.target.value)}
                    required
                    autoFocus
                  />
                  {creators.some((c) => c.creator_id !== renameTarget.creator_id && c.kind === renameTarget.kind && c.name.toLowerCase() === renameName.trim().toLowerCase()) && (
                    <div style={{ marginTop: 8, fontSize: 12, color: 'var(--color-amber)', background: 'rgba(245, 158, 11, 0.1)', padding: '6px 10px', borderRadius: 4 }}>
                      ⚠️ 提示：已存在同名创作者，保存将自动将两者合并，所有关联作品将汇集为同一人。
                    </div>
                  )}
                </div>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setRenameTarget(null)}
                  disabled={submittingRename}
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={submittingRename || !renameName.trim()}
                >
                  {submittingRename ? '正在保存…' : '保存'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Merge Modal */}
      {mergeSource && (
        <div className="modal-overlay" onClick={() => setMergeSource(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">合并创作者</h3>
              <button
                type="button"
                className="btn btn-ghost btn-circle"
                onClick={() => setMergeSource(null)}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleMergeSubmit}>
              <div className="modal-body">
                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 4 }}>
                    被合并的源创作者
                  </label>
                  <div style={{ padding: '8px 12px', background: 'rgba(255, 255, 255, 0.04)', borderRadius: 'var(--radius-sm)', fontSize: 13, fontWeight: 600 }}>
                    {mergeSource.name} ({mergeSource.item_count || 0} 部作品)
                  </div>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                    选择要合并到的目标创作者 *
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    style={{ height: 30, fontSize: 12, marginBottom: 8 }}
                    placeholder="快速搜索候选目标…"
                    value={mergeFilterQuery}
                    onChange={(e) => setMergeFilterQuery(e.target.value)}
                  />
                  <div style={{ maxHeight: 180, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4, padding: 4, background: 'rgba(0, 0, 0, 0.2)', borderRadius: 'var(--radius-sm)' }}>
                    {creators
                      .filter((c) => c.creator_id !== mergeSource.creator_id && c.kind === mergeSource.kind)
                      .filter((c) => !mergeFilterQuery.trim() || c.name.toLowerCase().includes(mergeFilterQuery.trim().toLowerCase()))
                      .map((c) => {
                        const selected = mergeTargetId === c.creator_id
                        return (
                          <div
                            key={c.creator_id}
                            onClick={() => setMergeTargetId(c.creator_id)}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              padding: '6px 10px',
                              borderRadius: 4,
                              cursor: 'pointer',
                              background: selected ? 'var(--accent-base)' : 'transparent',
                              color: selected ? '#fff' : 'var(--fg-main)',
                              fontSize: 13,
                              transition: 'all 0.15s ease',
                            }}
                          >
                            <span>{c.name}</span>
                            <span style={{ fontSize: 11, opacity: 0.8 }}>({c.item_count || 0} 部作品)</span>
                          </div>
                        )
                      })}
                  </div>
                  <small style={{ color: 'var(--fg-faint)', marginTop: 8, display: 'block', fontSize: 11 }}>
                    合并后，所有关联作品将自动迁移至目标创作者，原条目「{mergeSource.name}」将被移除。
                  </small>
                </div>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setMergeSource(null)}
                  disabled={submittingMerge}
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={submittingMerge || !mergeTargetId}
                >
                  {submittingMerge ? '正在合并…' : '确认合并'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
