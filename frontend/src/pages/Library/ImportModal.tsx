import React, { useState, useEffect } from 'react'
import { X, Upload, Folder, Check } from 'lucide-react'
import { api } from '../../api/client'
import type { Creator } from '../../types'

interface ImportModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: (itemId?: string) => void
}

export function ImportModal({ isOpen, onClose, onSuccess }: ImportModalProps) {
  const [selectionId, setSelectionId] = useState('')
  const [filename, setFilename] = useState('')
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState<'rj_work' | 'stream'>('rj_work')
  const [rjCode, setRjCode] = useState('')
  const [author] = useState('')
  const [autoProcess, setAutoProcess] = useState(true)
  const [creators, setCreators] = useState<Creator[]>([])
  const [selectedCreatorIds, setSelectedCreatorIds] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [picking, setPicking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen) {
      api.get<any>('/api/creators/list')
        .then((res) => {
          const list = Array.isArray(res) ? res : (res.creators || res.all_creators || [])
          setCreators(list)
        })
        .catch(() => {})
    }
  }, [isOpen])

  if (!isOpen) return null

  const handlePickFile = async () => {
    setPicking(true)
    setError(null)
    try {
      const res = await api.post<{ selection_id?: string; filename?: string; cancelled?: boolean }>('/picker/audio')
      if (res.selection_id) {
        setSelectionId(res.selection_id)
        const fname = res.filename || '已选择音频'
        setFilename(fname)
        if (!title) {
          const baseName = fname.replace(/\.[^/.]+$/, '')
          setTitle(baseName)
          const m = baseName.match(/(RJ\d{6,8})/i)
          if (m) setRjCode(m[1].toUpperCase())
        }
      }
    } catch (err: any) {
      setError('选择文件失败: ' + (err.message || '未知错误'))
    } finally {
      setPicking(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectionId) {
      setError('请先选择要导入的音频文件')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const formData = new FormData()
      formData.append('selection_id', selectionId)
      formData.append('title', title)
      formData.append('kind', kind)
      if (rjCode) formData.append('rj_code', rjCode)
      if (author) formData.append('author', author)
      if (autoProcess) formData.append('auto_process', 'on')
      selectedCreatorIds.forEach((id) => formData.append('creator_ids', id))

      await api.postForm('/items/import', formData)
      onSuccess()
      onClose()
    } catch (err: any) {
      setError('导入失败: ' + (err.message || '未知错误'))
    } finally {
      setSubmitting(false)
    }
  }

  const toggleCreator = (id: string) => {
    setSelectedCreatorIds((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    )
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">导入单个音频</h3>
          <button type="button" className="btn btn-ghost btn-circle" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {error && (
              <div style={{ color: 'var(--color-red)', background: 'rgba(239, 68, 68, 0.1)', padding: '8px 12px', borderRadius: 'var(--radius-sm)' }}>
                {error}
              </div>
            )}

            <div>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                音频文件 *
              </label>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <button
                  type="button"
                  className="btn"
                  onClick={handlePickFile}
                  disabled={picking}
                >
                  <Folder size={15} />
                  {picking ? '正在选择…' : '浏览文件'}
                </button>
                <span style={{ fontSize: 13, color: filename ? 'var(--fg-main)' : 'var(--fg-faint)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {filename || '未选择音频文件'}
                </span>
              </div>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                作品类型
              </label>
              <div style={{ display: 'flex', gap: 16 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="kind"
                    checked={kind === 'rj_work'}
                    onChange={() => setKind('rj_work')}
                  />
                  RJ 同人音声
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="kind"
                    checked={kind === 'stream'}
                    onChange={() => setKind('stream')}
                  />
                  直播/其他音频
                </label>
              </div>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                标题 *
              </label>
              <input
                type="text"
                className="input-field"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="作品标题"
                required
              />
            </div>

            {kind === 'rj_work' && (
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
                      if (!rjCode.trim()) return
                      try {
                        const res = await api.get<{ ok: boolean; data: any }>(`/api/dlsite/${rjCode.trim()}`)
                        if (res.ok && res.data && res.data.title) {
                          setTitle(res.data.title)
                        }
                      } catch {}
                    }}
                  >
                    从 DLsite 填充
                  </button>
                </div>
                <input
                  type="text"
                  className="input-field"
                  value={rjCode}
                  onChange={(e) => setRjCode(e.target.value.toUpperCase())}
                  placeholder="例如: RJ123456"
                />
              </div>
            )}

            <div>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                关联创作者
              </label>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', maxHeight: 100, overflowY: 'auto' }}>
                {creators.map((c) => {
                  const active = selectedCreatorIds.includes(c.creator_id)
                  return (
                    <button
                      key={c.creator_id}
                      type="button"
                      className={`chip ${active ? (c.kind === 'voice_actor' ? 'chip-creator' : 'chip-circle') : 'chip-tag'}`}
                      onClick={() => toggleCreator(c.creator_id)}
                      style={{ cursor: 'pointer' }}
                    >
                      {active && <Check size={12} />}
                      {c.name}
                    </button>
                  )
                })}
              </div>
            </div>

            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
              <input
                type="checkbox"
                checked={autoProcess}
                onChange={(e) => setAutoProcess(e.target.checked)}
              />
              导入后自动加入后台 ASR 识别与翻译队列
            </label>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={submitting}>
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={submitting || !selectionId}>
              <Upload size={14} />
              {submitting ? '正在导入…' : '立即导入'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
