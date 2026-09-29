import React, { useState } from 'react'
import { X, Download } from 'lucide-react'
import { api } from '../../api/client'

interface ImportUrlModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: (taskId?: string) => void
}

export function ImportUrlModal({ isOpen, onClose, onSuccess }: ImportUrlModalProps) {
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [autoProcess, setAutoProcess] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!isOpen) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) {
      setError('请输入有效的网络音视频链接')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const formData = new FormData()
      formData.append('url', url.trim())
      if (title.trim()) formData.append('title', title.trim())
      if (autoProcess) formData.append('auto_process', 'on')

      const data = await api.postForm<{ task_id?: string }>('/items/import-url', formData)
      onSuccess(data.task_id)
      onClose()
    } catch (err: any) {
      setError('提交下载失败: ' + (err.message || '未知错误'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">从网络链接导入</h3>
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
              输入音频或视频链接（支持 Bilibili、YouTube 等常见流媒体平台），后端将自动通过 yt-dlp 抓取音频并加入作品库。
            </p>

            <div>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                网页链接 (URL) *
              </label>
              <div style={{ display: 'flex', alignItems: 'center', position: 'relative' }}>
                <input
                  type="url"
                  className="input-field"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://www.bilibili.com/video/BV... 或 https://youtu.be/..."
                  required
                  autoFocus
                />
              </div>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                自定义作品标题（可选，留空将自动提取网页标题）
              </label>
              <input
                type="text"
                className="input-field"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="作品标题"
              />
            </div>

            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, marginTop: 4 }}>
              <input
                type="checkbox"
                checked={autoProcess}
                onChange={(e) => setAutoProcess(e.target.checked)}
              />
              下载完成后自动加入转写与双语翻译任务
            </label>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={submitting}>
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={submitting || !url.trim()}>
              <Download size={14} />
              {submitting ? '正在提交…' : '开始下载'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
