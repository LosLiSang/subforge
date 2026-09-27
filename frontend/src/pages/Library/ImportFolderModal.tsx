import React, { useState } from 'react'
import { X, FolderOpen, CheckCircle } from 'lucide-react'
import { api } from '../../api/client'
import type { ImportFolderPreviewResponse } from '../../types'

interface ImportFolderModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
}

export function ImportFolderModal({ isOpen, onClose, onSuccess }: ImportFolderModalProps) {
  const [selectionId, setSelectionId] = useState('')
  const [preview, setPreview] = useState<ImportFolderPreviewResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState('')

  if (!isOpen) return null

  const handlePickFolder = async () => {
    setError('')
    setLoading(true)
    try {
      const res = await api.post<{ selection_id: string }>('/picker/media-folder')
      setSelectionId(res.selection_id)
      // Preview
      const previewRes = await api.post<ImportFolderPreviewResponse>(
        '/api/import-folders/preview',
        { selection_id: res.selection_id }
      )
      setPreview(previewRes)
    } catch (err: any) {
      setError(err.message || '扫描文件夹失败')
    } finally {
      setLoading(false)
    }
  }

  const handleImport = async () => {
    if (!selectionId) return
    setImporting(true)
    setError('')
    try {
      await api.post('/items/import-folder', { selection_id: selectionId })
      onSuccess()
      onClose()
    } catch (err: any) {
      setError(err.message || '批量导入失败')
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-dialog max-w-2xl">
        <div className="modal-header">
          <h3 className="modal-title flex items-center gap-2">
            <FolderOpen size={18} className="text-accent" />
            导入作品文件夹
          </h3>
          <button type="button" onClick={onClose} className="modal-close-btn">
            <X size={18} />
          </button>
        </div>

        <div className="modal-body space-y-4">
          {error && <div className="p-3 bg-red-900/30 border border-red-800 rounded text-red-300 text-sm">{error}</div>}

          {!preview && (
            <div className="text-center py-8 space-y-4">
              <p className="text-fg-dim text-sm">
                选择包含音频文件的作品文件夹（例如带有 RJ 号的同人音声目录），系统将自动分组解析。
              </p>
              <button
                type="button"
                onClick={handlePickFolder}
                disabled={loading}
                className="btn btn-primary"
              >
                {loading ? '正在扫描...' : '选择本地目录'}
              </button>
            </div>
          )}

          {preview && (
            <div className="space-y-4">
              <div className="flex justify-between items-center bg-panel-2 p-3 rounded border border-line">
                <div>
                  <div className="font-semibold text-sm">{preview.folder_name}</div>
                  <div className="text-xs text-fg-dim">发现 {preview.groups.length} 个作品分组</div>
                </div>
                <button
                  type="button"
                  onClick={handlePickFolder}
                  className="btn btn-secondary text-xs"
                >
                  重新选择
                </button>
              </div>

              <div className="max-h-60 overflow-y-auto space-y-2 pr-1">
                {preview.groups.map((group, idx) => (
                  <div key={idx} className="p-3 bg-panel border border-line rounded">
                    <div className="flex items-center gap-2 font-medium text-sm">
                      <CheckCircle size={16} className="text-green-400" />
                      <span>{group.title}</span>
                      {group.rj_code && (
                        <span className="badge badge-accent">{group.rj_code}</span>
                      )}
                    </div>
                    <div className="text-xs text-fg-dim mt-1 pl-6">
                      包含 {group.tracks?.length || 0} 个音轨
                    </div>
                  </div>
                ))}
              </div>

              <div className="modal-footer">
                <button type="button" onClick={onClose} className="btn btn-secondary">
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleImport}
                  disabled={importing}
                  className="btn btn-primary"
                >
                  {importing ? '正在批量导入...' : `确认导入 (${preview.groups.length} 个作品)`}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
