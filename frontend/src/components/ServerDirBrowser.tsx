import React, { useEffect, useState } from 'react'
import { Folder, ArrowUp, Check, RefreshCw } from 'lucide-react'
import { api } from '../api/client'

interface FsDirEntry {
  name: string
  path: string
}

interface FsListResponse {
  current_path: string
  parent_path: string | null
  dirs: FsDirEntry[]
}

interface ServerDirBrowserProps {
  kind: 'folder' | 'directory'
  initialPath?: string
  onSelect: (res: { selection_id: string; name: string; path: string }) => void
  onCancel?: () => void
}

export function ServerDirBrowser({ kind, initialPath, onSelect, onCancel }: ServerDirBrowserProps) {
  const [currentPath, setCurrentPath] = useState(initialPath || '')
  const [pathInput, setPathInput] = useState(initialPath || '')
  const [parentPath, setParentPath] = useState<string | null>(null)
  const [dirs, setDirs] = useState<FsDirEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [selecting, setSelecting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadDir = async (targetPath?: string) => {
    setLoading(true)
    setError(null)
    try {
      const qs = targetPath ? `?path=${encodeURIComponent(targetPath)}` : ''
      const res = await api.get<FsListResponse>(`/api/fs/list${qs}`)
      setCurrentPath(res.current_path)
      setPathInput(res.current_path)
      setParentPath(res.parent_path)
      setDirs(res.dirs || [])
    } catch (err: any) {
      setError(err.message || '无法读取目录')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadDir(initialPath || undefined)
  }, [])

  const handleSelectCurrent = async () => {
    if (!currentPath) return
    setSelecting(true)
    setError(null)
    try {
      const res = await api.post<{ selection_id: string; name: string; path: string }>(
        '/api/picker/select-path',
        { path: currentPath, kind }
      )
      onSelect(res)
    } catch (err: any) {
      setError(err.message || '选择目录失败')
    } finally {
      setSelecting(false)
    }
  }

  return (
    <div
      style={{
        marginTop: 10,
        padding: 12,
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-strong)',
        background: 'rgba(255, 255, 255, 0.03)',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <input
          type="text"
          className="input-field"
          value={pathInput}
          onChange={(e) => setPathInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              loadDir(pathInput.trim())
            }
          }}
          placeholder="输入服务器目录路径"
          style={{ flex: 1, minWidth: 160, fontSize: 12.5, padding: '6px 10px' }}
        />
        <button
          type="button"
          className="btn btn-sm btn-ghost"
          onClick={() => loadDir(pathInput.trim())}
          disabled={loading}
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          跳转
        </button>
        <button
          type="button"
          className="btn btn-sm btn-ghost"
          onClick={() => parentPath && loadDir(parentPath)}
          disabled={loading || !parentPath}
          title="返回上级目录"
        >
          <ArrowUp size={13} />
          上级
        </button>
      </div>

      {error && (
        <div style={{ fontSize: 12, color: 'var(--color-red)', background: 'rgba(239, 68, 68, 0.1)', padding: '6px 10px', borderRadius: 'var(--radius-sm)' }}>
          {error}
        </div>
      )}

      <div
        style={{
          maxHeight: 210,
          overflowY: 'auto',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-sm)',
          background: 'var(--bg-app)',
        }}
      >
        {loading ? (
          <div style={{ padding: 16, textAlign: 'center', fontSize: 12.5, color: 'var(--fg-dim)' }}>
            正在加载目录…
          </div>
        ) : dirs.length === 0 ? (
          <div style={{ padding: 16, textAlign: 'center', fontSize: 12.5, color: 'var(--fg-faint)' }}>
            此目录下无子文件夹
          </div>
        ) : (
          dirs.map((d) => (
            <button
              key={d.path}
              type="button"
              onClick={() => loadDir(d.path)}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '8px 12px',
                background: 'transparent',
                border: 'none',
                borderBottom: '1px solid var(--border-subtle)',
                color: 'var(--fg-main)',
                fontSize: 13,
                textAlign: 'left',
                cursor: 'pointer',
              }}
            >
              <Folder size={14} style={{ color: 'var(--accent-base)', flexShrink: 0 }} />
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {d.name}
              </span>
            </button>
          ))
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11.5, color: 'var(--fg-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0 }}>
          当前: {currentPath || '-'}
        </span>
        <div style={{ display: 'flex', gap: 6 }}>
          {onCancel && (
            <button type="button" className="btn btn-sm btn-ghost" onClick={onCancel}>
              收起
            </button>
          )}
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={handleSelectCurrent}
            disabled={selecting || !currentPath}
          >
            <Check size={13} />
            {selecting ? '正在确认…' : '选择当前目录'}
          </button>
        </div>
      </div>
    </div>
  )
}
