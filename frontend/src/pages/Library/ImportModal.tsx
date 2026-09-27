import React, { useState } from 'react'
import { X, Upload, Folder, Music } from 'lucide-react'
import { api } from '../../api/client'
import type { Creator } from '../../types'

interface ImportModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
  creators: Creator[]
}

export function ImportModal({ isOpen, onClose, onSuccess, creators }: ImportModalProps) {
  const [title, setTitle] = useState('')
  const [originalTitle, setOriginalTitle] = useState('')
  const [rjCode, setRjCode] = useState('')
  const [tags, setTags] = useState('')
  const [selectedCreatorIds, setSelectedCreatorIds] = useState<string[]>([])
  const [selectionId, setSelectionId] = useState('')
  const [selectedFileName, setSelectedFileName] = useState('')
  const [coverSelectionId, setCoverSelectionId] = useState('')
  const [coverFileName, setCoverFileName] = useState('')
  const [autoProcess, setAutoProcess] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  if (!isOpen) return null

  const handlePickAudio = async () => {
    try {
      const res = await api.post<{ selection_id: string; filename: string }>('/picker/audio')
      setSelectionId(res.selection_id)
      setSelectedFileName(res.filename)
      if (!title) {
        setTitle(res.filename.replace(/\.[^/.]+$/, ''))
      }
    } catch (err: any) {
      setError(err.message || '选择音频失败')
    }
  }

  const handlePickCover = async () => {
    try {
      const res = await api.post<{ selection_id: string; filename: string }>('/picker/image')
      setCoverSelectionId(res.selection_id)
      setCoverFileName(res.filename)
    } catch (err: any) {
      setError(err.message || '选择封面失败')
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectionId) {
      setError('请先选择要导入的音频文件')
      return
    }
    setLoading(true)
    setError('')
    try {
      await api.post('/items/import', {
        selection_id: selectionId,
        title: title.trim() || selectedFileName,
        original_title: originalTitle.trim(),
        rj_code: rjCode.trim(),
        creator_ids: selectedCreatorIds,
        tags: tags
          .split(/[,，\s]+/)
          .map((t) => t.trim())
          .filter(Boolean),
        cover_selection_id: coverSelectionId || undefined,
        auto_process: autoProcess ? 'on' : undefined,
      })
      onSuccess()
      onClose()
    } catch (err: any) {
      setError(err.message || '导入作品失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-dialog">
        <div className="modal-header">
          <h3 className="modal-title flex items-center gap-2">
            <Music size={18} className="text-accent" />
            导入音频作品
          </h3>
          <button type="button" onClick={onClose} className="modal-close-btn">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-body space-y-4">
          {error && <div className="p-3 bg-red-900/30 border border-red-800 rounded text-red-300 text-sm">{error}</div>}

          {/* Audio selection */}
          <div className="space-y-1">
            <label className="text-sm font-medium">音频文件 *</label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handlePickAudio}
                className="btn btn-secondary flex items-center gap-1.5"
              >
                <Upload size={16} />
                选择本地音频
              </button>
              <span className="text-sm text-fg-dim self-center truncate">
                {selectedFileName || '未选择文件'}
              </span>
            </div>
          </div>

          {/* Title */}
          <div className="space-y-1">
            <label className="text-sm font-medium">作品标题</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="为空时默认使用音频文件名"
              className="input-text"
            />
          </div>

          {/* RJ Code & Original Title */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-sm font-medium">RJ 号</label>
              <input
                type="text"
                value={rjCode}
                onChange={(e) => setRjCode(e.target.value)}
                placeholder="例: RJ123456"
                className="input-text"
              />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">日文原名</label>
              <input
                type="text"
                value={originalTitle}
                onChange={(e) => setOriginalTitle(e.target.value)}
                placeholder="日文原版名称"
                className="input-text"
              />
            </div>
          </div>

          {/* Creators */}
          <div className="space-y-1">
            <label className="text-sm font-medium">创作者 / 声优</label>
            <select
              multiple
              value={selectedCreatorIds}
              onChange={(e) => {
                const options = Array.from(e.target.selectedOptions, (option) => option.value)
                setSelectedCreatorIds(options)
              }}
              className="input-text h-24"
            >
              {creators.map((c) => (
                <option key={c.creator_id} value={c.creator_id}>
                  {c.name} ({c.kind === 'voice_actor' ? '声优' : '社团'})
                </option>
              ))}
            </select>
            <small className="text-xs text-fg-dim">按住 Ctrl 可多选</small>
          </div>

          {/* Tags */}
          <div className="space-y-1">
            <label className="text-sm font-medium">标签</label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="逗号或空格分隔，例: ASMR, 耳搔, 治愈"
              className="input-text"
            />
          </div>

          {/* Cover */}
          <div className="space-y-1">
            <label className="text-sm font-medium">封面图片 (可选)</label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handlePickCover}
                className="btn btn-secondary flex items-center gap-1.5"
              >
                <Folder size={16} />
                选择封面
              </button>
              <span className="text-sm text-fg-dim self-center truncate">
                {coverFileName || '默认提取音频内置封面'}
              </span>
            </div>
          </div>

          {/* Auto process */}
          <label className="flex items-center gap-2 cursor-pointer pt-1">
            <input
              type="checkbox"
              checked={autoProcess}
              onChange={(e) => setAutoProcess(e.target.checked)}
              className="accent-accent"
            />
            <span className="text-sm">导入后自动加入字幕生成队列</span>
          </label>

          <div className="modal-footer">
            <button type="button" onClick={onClose} className="btn btn-secondary">
              取消
            </button>
            <button
              type="submit"
              disabled={loading || !selectionId}
              className="btn btn-primary"
            >
              {loading ? '正在导入...' : '确认导入'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
