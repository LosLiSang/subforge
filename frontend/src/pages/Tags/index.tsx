import React, { useState, useEffect, useMemo, useRef } from 'react'
import { Link } from 'react-router-dom'
import {
  Plus,
  Search,
  Tag as TagIcon,
  Edit2,
  Trash2,
  X,
  Settings,
  ArrowUpDown,
  Check,
} from 'lucide-react'
import { api } from '../../api/client'
import type { TagItem } from '../../types'

export function TagsPage() {
  const [tags, setTags] = useState<TagItem[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [sortBy, setSortBy] = useState<'count_desc' | 'name_asc'>('count_desc')
  const [editMode, setEditMode] = useState(false)

  // Inline quick-add tag state (User requirement 2)
  const [isInlineAdding, setIsInlineAdding] = useState(false)
  const [inlineTagName, setInlineTagName] = useState('')
  const [inlineSubmitting, setInlineSubmitting] = useState(false)
  const inlineInputRef = useRef<HTMLInputElement>(null)

  // Add tag modal
  const [modalOpen, setModalOpen] = useState(false)
  const [formName, setFormName] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Rename modal
  const [renameTarget, setRenameTarget] = useState<TagItem | null>(null)
  const [renameName, setRenameName] = useState('')
  const [submittingRename, setSubmittingRename] = useState(false)

  const loadTags = async () => {
    setLoading(true)
    try {
      const res = await api.get<any>('/api/tags/list')
      const list = Array.isArray(res) ? res : (res.tags || res.all_tags || [])
      // If server returned string[] of tags, map to TagItem
      const formatted: TagItem[] = list.map((item: any) => {
        if (typeof item === 'string') {
          return { name: item, item_count: 0 }
        }
        return item
      })
      setTags(formatted)
    } catch (err) {
      console.error('Failed to load tags:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTags()
  }, [])

  useEffect(() => {
    if (isInlineAdding && inlineInputRef.current) {
      inlineInputRef.current.focus()
    }
  }, [isInlineAdding])

  const filtered = useMemo(() => {
    let list = tags.filter((t) => {
      if (searchQuery.trim() && !t.name.toLowerCase().includes(searchQuery.toLowerCase())) {
        return false
      }
      return true
    })

    return list.sort((a, b) => {
      if (sortBy === 'count_desc') {
        const countA = a.item_count || 0
        const countB = b.item_count || 0
        if (countB !== countA) return countB - countA
        return a.name.localeCompare(b.name, 'zh-CN')
      } else {
        return a.name.localeCompare(b.name, 'zh-CN')
      }
    })
  }, [tags, searchQuery, sortBy])

  // Submit inline quick add
  const handleInlineSubmit = async () => {
    const clean = inlineTagName.trim().replace(/^#/, '')
    if (!clean) {
      setIsInlineAdding(false)
      setInlineTagName('')
      return
    }
    setInlineSubmitting(true)
    try {
      const formData = new FormData()
      formData.append('action', 'create')
      formData.append('name', clean)
      await api.postForm('/api/tags', formData)
      setInlineTagName('')
      setIsInlineAdding(false)
      await loadTags()
    } catch (err: any) {
      alert('添加标签失败: ' + (err.message || '未知错误'))
    } finally {
      setInlineSubmitting(false)
    }
  }

  // Submit modal add
  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const clean = formName.trim().replace(/^#/, '')
    if (!clean) return
    setSubmitting(true)
    try {
      const formData = new FormData()
      formData.append('action', 'create')
      formData.append('name', clean)
      await api.postForm('/api/tags', formData)
      setModalOpen(false)
      setFormName('')
      await loadTags()
    } catch (err: any) {
      alert('添加标签失败: ' + (err.message || '未知错误'))
    } finally {
      setSubmitting(false)
    }
  }

  // Submit rename
  const handleRenameSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!renameTarget || !renameName.trim()) return
    setSubmittingRename(true)
    try {
      const formData = new FormData()
      formData.append('action', 'rename')
      formData.append('old_name', renameTarget.name)
      formData.append('new_name', renameName.trim().replace(/^#/, ''))
      await api.postForm('/api/tags', formData)
      setRenameTarget(null)
      await loadTags()
    } catch (err: any) {
      alert('重命名失败: ' + (err.message || '未知错误'))
    } finally {
      setSubmittingRename(false)
    }
  }

  // Delete tag
  const handleDeleteTag = async (e: React.MouseEvent, t: TagItem) => {
    e.preventDefault()
    e.stopPropagation()
    const msg = t.item_count
      ? `确定要删除标签「${t.name}」吗？\n该标签已关联 ${t.item_count} 部作品，删除后将自动从这些作品中移除此标签。`
      : `确定要删除标签「${t.name}」吗？`
    if (!window.confirm(msg)) return
    try {
      const formData = new FormData()
      formData.append('action', 'delete')
      formData.append('name', t.name)
      await api.postForm('/api/tags', formData)
      await loadTags()
    } catch (err: any) {
      alert('删除标签失败: ' + (err.message || '未知错误'))
    }
  }

  return (
    <div className="vas-page-container">
      {/* Top Header & Title */}
      <div className="vas-header-row">
        <div className="vas-title-group">
          <h1 className="vas-main-title">All tags</h1>
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
            onClick={() => setModalOpen(true)}
          >
            <Plus size={15} />
            新建标签
          </button>
        </div>
      </div>

      {/* Wide Search Bar matching Creators style */}
      <div className="vas-search-bar-wrap">
        <input
          type="text"
          className="vas-search-input"
          placeholder="搜索标签 (Search tags)..."
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
          共匹配到 <strong>{filtered.length}</strong> 个标签 (全部 {tags.length})
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

      {/* Grid Container */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-dim)' }}>
          <p>正在载入标签列表…</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="vas-empty-state">
          <p>未找到匹配的标签</p>
          <small style={{ color: 'var(--fg-faint)', marginTop: 6 }}>
            可以尝试更换搜索关键词，或点击上方「+」新建标签
          </small>
        </div>
      ) : (
        <div className="vas-grid-container">
          {filtered.map((t) => (
            <div key={t.name} className="vas-cell-item">
              <Link
                to={`/?tag=${encodeURIComponent(t.name)}`}
                className="vas-item-link"
                title={`查看带有标签 #${t.name} 的所有作品 (${t.item_count || 0})`}
              >
                <span className="vas-name" style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                  <TagIcon size={13} style={{ opacity: 0.65, flexShrink: 0 }} />
                  <span>{t.name}</span>
                </span>
                <span className="vas-badge-count">{t.item_count || 0}</span>
              </Link>

              {editMode && (
                <div className="vas-cell-actions">
                  <button
                    type="button"
                    className="vas-cell-btn"
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      setRenameTarget(t)
                      setRenameName(t.name)
                    }}
                    title="重命名"
                  >
                    <Edit2 size={12} />
                  </button>
                  <button
                    type="button"
                    className="vas-cell-btn vas-cell-btn-delete"
                    onClick={(e) => handleDeleteTag(e, t)}
                    title="删除"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              )}
            </div>
          ))}

          {/* Inline Add Tag Card at the end of the tags grid - 100% unified with normal tag cards */}
          {!isInlineAdding ? (
            <div
              className="vas-cell-item"
              onClick={() => setIsInlineAdding(true)}
              style={{ cursor: 'pointer' }}
              title="点击添加新标签"
            >
              <div className="vas-item-link">
                <span className="vas-name" style={{ display: 'inline-flex', alignItems: 'center', gap: 7, color: 'var(--accent-base)' }}>
                  <TagIcon size={14} style={{ flexShrink: 0, opacity: 0.9 }} />
                  <span style={{ fontWeight: 600 }}>新建标签…</span>
                </span>
                <span
                  className="vas-badge-count"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: 24,
                    height: 20,
                    padding: 0,
                    background: 'var(--accent-base)',
                    color: '#ffffff',
                  }}
                >
                  <Plus size={13} strokeWidth={2.5} />
                </span>
              </div>
            </div>
          ) : (
            <div
              className="vas-cell-item"
              style={{
                background: 'rgba(255, 255, 255, 0.03)',
                boxShadow: 'inset 0 0 0 1.5px var(--accent-base)',
              }}
            >
              <div className="vas-item-link" style={{ gap: 6 }}>
                <TagIcon size={14} style={{ color: 'var(--accent-base)', flexShrink: 0 }} />
                <input
                  ref={inlineInputRef}
                  type="text"
                  value={inlineTagName}
                  onChange={(e) => setInlineTagName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.nativeEvent.isComposing) return
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      handleInlineSubmit()
                    } else if (e.key === 'Escape') {
                      e.preventDefault()
                      setIsInlineAdding(false)
                      setInlineTagName('')
                    }
                  }}
                  onBlur={() => {
                    if (inlineTagName.trim()) {
                      handleInlineSubmit()
                    } else {
                      setIsInlineAdding(false)
                    }
                  }}
                  placeholder="输入新标签名…"
                  style={{
                    flex: 1,
                    background: 'transparent',
                    border: 'none',
                    outline: 'none',
                    color: 'var(--fg-main)',
                    fontSize: '13.5px',
                    fontWeight: 500,
                    padding: 0,
                    minWidth: 0,
                  }}
                  autoFocus
                  disabled={inlineSubmitting}
                />
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-circle"
                    style={{ width: 22, height: 22, padding: 0 }}
                    onClick={handleInlineSubmit}
                    disabled={inlineSubmitting}
                    title="确认创建 (Enter)"
                  >
                    <Check size={13} style={{ color: 'var(--accent-base)' }} />
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-circle"
                    style={{ width: 22, height: 22, padding: 0 }}
                    onClick={() => {
                      setIsInlineAdding(false)
                      setInlineTagName('')
                    }}
                    title="取消 (Esc)"
                  >
                    <X size={13} />
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Add Modal */}
      {modalOpen && (
        <div className="modal-overlay" onClick={() => setModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">新建标签</h3>
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
                    标签名称 *
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="例如: 舔耳, 催眠, 少女, KU100"
                    required
                    autoFocus
                  />
                  <small style={{ color: 'var(--fg-faint)', marginTop: 4, display: 'block', fontSize: 11 }}>
                    无需输入开头的 # 号，系统会自动处理
                  </small>
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
              <h3 className="modal-title">重命名标签</h3>
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
                    原名称
                  </label>
                  <div style={{ fontSize: 13, color: 'var(--fg-muted)', marginBottom: 12 }}>
                    #{renameTarget.name} ({renameTarget.item_count || 0} 部作品)
                  </div>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                    新标签名 *
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={renameName}
                    onChange={(e) => setRenameName(e.target.value)}
                    required
                    autoFocus
                  />
                  <small style={{ color: 'var(--fg-faint)', marginTop: 4, display: 'block', fontSize: 11 }}>
                    重命名将同步更新所有包含该标签的作品元数据
                  </small>
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
                  disabled={submittingRename || !renameName.trim() || renameName.trim() === renameTarget.name}
                >
                  {submittingRename ? '正在更新…' : '确认重命名'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
