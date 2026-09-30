import React, { useState, useEffect } from 'react'
import { X, Folder, Upload, Check } from 'lucide-react'
import { api } from '../../api/client'
import type { Creator } from '../../types'

interface ImportFolderModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
}

export function ImportFolderModal({ isOpen, onClose, onSuccess }: ImportFolderModalProps) {
  const [selectionId, setSelectionId] = useState('')
  const [folderName, setFolderName] = useState('')
  const [rjCode, setRjCode] = useState('')
  const [title, setTitle] = useState('')
  const [autoProcess, setAutoProcess] = useState(true)
  const [creators, setCreators] = useState<Creator[]>([])
  const [selectedCreatorIds, setSelectedCreatorIds] = useState<string[]>([])
  const [picking, setPicking] = useState(false)
  const [submitting, setSubmitting] = useState(false)
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

  const handlePickFolder = async () => {
    setPicking(true)
    setError(null)
    try {
      const res = await api.post<{ selection_id?: string; name?: string; cancelled?: boolean }>('/picker/folder')
      if (res.selection_id) {
        setSelectionId(res.selection_id)
        const name = res.name || '已选文件夹'
        setFolderName(name)
        const m = name.match(/RJ\d{6,8}/i)
        if (m && !rjCode) {
          setRjCode(m[0].toUpperCase())
        }
        if (!title) {
          setTitle(name)
        }
      }
    } catch (err: any) {
      setError('选择文件夹失败: ' + (err.message || '未知错误'))
    } finally {
      setPicking(false)
    }
  }

  const toggleCreator = (id: string) => {
    setSelectedCreatorIds((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectionId) {
      setError('请先选择要导入的作品文件夹')
      return
    }
    const finalRj = rjCode.trim() || (folderName.match(/RJ\d{6,8}/i)?.[0] ?? '')
    if (!finalRj) {
      setError('请输入或从目录中提取有效的 RJ 号（例如: RJ01499022）')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const formData = new FormData()
      formData.append('selection_id', selectionId)
      formData.append('rj_code', finalRj.toUpperCase())
      if (title.trim()) formData.append('title', title.trim())
      if (autoProcess) formData.append('auto_process', 'on')
      selectedCreatorIds.forEach((id) => formData.append('creator_ids', id))

      await api.postForm('/items/import-folder', formData)
      onSuccess()
      onClose()
    } catch (err: any) {
      setError('批量导入失败: ' + (err.message || '未知错误'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">扫描/导入作品目录</h3>
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

            <p style={{ fontSize: 13, color: 'var(--fg-dim)' }}>
              选择包含同人音声作品的目录。系统会自动扫描子目录中的音频文件、封面并尝试提取 RJ 号建立作品索引。
            </p>

            <div>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                本地文件夹 *
              </label>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <button
                  type="button"
                  className="btn"
                  onClick={handlePickFolder}
                  disabled={picking}
                >
                  <Folder size={15} />
                  {picking ? '正在选择…' : '选择文件夹'}
                </button>
                <span style={{ fontSize: 13, color: folderName ? 'var(--fg-main)' : 'var(--fg-faint)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {folderName || '未选择目录'}
                </span>
              </div>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                RJ 号 *
              </label>
              <input
                type="text"
                className="input-field"
                value={rjCode}
                onChange={(e) => setRjCode(e.target.value.toUpperCase())}
                placeholder="例如: RJ01499022"
                required
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                作品标题
              </label>
              <input
                type="text"
                className="input-field"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="留空使用 RJ 号或目录名"
              />
            </div>

            {creators.length > 0 && (
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
            )}

            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, marginTop: 4 }}>
              <input
                type="checkbox"
                checked={autoProcess}
                onChange={(e) => setAutoProcess(e.target.checked)}
              />
              导入完成后自动将所有音轨加入转写与翻译任务队列
            </label>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={submitting}>
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={submitting || !selectionId}>
              <Upload size={14} />
              {submitting ? '正在扫描导入…' : '开始导入'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
