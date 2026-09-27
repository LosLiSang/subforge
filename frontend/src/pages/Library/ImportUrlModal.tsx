import React, { useState } from 'react'
import { X, Globe, Download, Sparkles } from 'lucide-react'
import { api } from '../../api/client'
import type { Creator } from '../../types'

interface ImportUrlModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
  creators: Creator[]
}

export function ImportUrlModal({ isOpen, onClose, onSuccess, creators }: ImportUrlModalProps) {
  const [url, setUrl] = useState('')
  const [fetching, setFetching] = useState(false)
  const [info, setInfo] = useState<any>(null)
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [selectedCreatorId, setSelectedCreatorId] = useState('')
  const [autoProcess, setAutoProcess] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  if (!isOpen) return null

  const handleFetchInfo = async () => {
    if (!url.trim()) return
    setFetching(true)
    setError('')
    try {
      const data = await api.get(`/api/video-info?url=${encodeURIComponent(url.trim())}`)
      if (data.ok) {
        setInfo(data)
        setTitle(data.title || '')
        setAuthor(data.author || '')
        const match = creators.find((c) => c.name === data.author)
        if (match) setSelectedCreatorId(match.creator_id)
      } else {
        setError(data.error || '获取元数据失败')
      }
    } catch (err: any) {
      setError(err.message || '获取视频信息失败')
    } finally {
      setFetching(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) return
    setLoading(true)
    setError('')
    try {
      await api.post('/items/import-url', {
        url: url.trim(),
        title: title.trim(),
        author: author.trim(),
        creator_ids: selectedCreatorId ? [selectedCreatorId] : [],
        cover_url: info?.cover_url || undefined,
        auto_process: autoProcess ? 'on' : undefined,
      })
      onSuccess()
      onClose()
    } catch (err: any) {
      setError(err.message || '创建下载任务失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-dialog">
        <div className="modal-header">
          <h3 className="modal-title flex items-center gap-2">
            <Globe size={18} className="text-accent" />
            从链接导入媒体
          </h3>
          <button type="button" onClick={onClose} className="modal-close-btn">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-body space-y-4">
          {error && <div className="p-3 bg-red-900/30 border border-red-800 rounded text-red-300 text-sm">{error}</div>}

          <div className="space-y-1">
            <label className="text-sm font-medium">媒体 URL (Bilibili / YouTube / 音频源)</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://www.bilibili.com/video/BV... 或 b23.tv"
                className="input-text flex-1"
              />
              <button
                type="button"
                onClick={handleFetchInfo}
                disabled={fetching || !url.trim()}
                className="btn btn-secondary flex items-center gap-1.5"
              >
                <Sparkles size={16} />
                {fetching ? '抓取中...' : '解析'}
              </button>
            </div>
          </div>

          {info && (
            <div className="p-3 bg-panel-2 rounded border border-line flex gap-3">
              {info.cover_url && (
                <img
                  src={info.cover_url}
                  alt="cover"
                  className="w-24 h-16 object-cover rounded flex-none"
                />
              )}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{info.title}</div>
                <div className="text-xs text-fg-dim mt-1">UP主 / 作者: {info.author || '未知'}</div>
                {info.duration > 0 && (
                  <div className="text-xs text-fg-faint mt-0.5">
                    时长: {Math.floor(info.duration / 60)} 分钟
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="space-y-1">
            <label className="text-sm font-medium">作品标题</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="留空则使用解析出的视频标题"
              className="input-text"
            />
          </div>

          <div className="space-y-1">
            <label className="text-sm font-medium">关联创作者</label>
            <select
              value={selectedCreatorId}
              onChange={(e) => setSelectedCreatorId(e.target.value)}
              className="input-text"
            >
              <option value="">-- 自动或不指定 --</option>
              {creators.map((c) => (
                <option key={c.creator_id} value={c.creator_id}>
                  {c.name} ({c.kind === 'voice_actor' ? '声优' : '社团'})
                </option>
              ))}
            </select>
          </div>

          <label className="flex items-center gap-2 cursor-pointer pt-1">
            <input
              type="checkbox"
              checked={autoProcess}
              onChange={(e) => setAutoProcess(e.target.checked)}
              className="accent-accent"
            />
            <span className="text-sm">下载完成后自动提交字幕生成</span>
          </label>

          <div className="modal-footer">
            <button type="button" onClick={onClose} className="btn btn-secondary">
              取消
            </button>
            <button
              type="submit"
              disabled={loading || !url.trim()}
              className="btn btn-primary flex items-center gap-1.5"
            >
              <Download size={16} />
              {loading ? '提交中...' : '提交后台下载'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
