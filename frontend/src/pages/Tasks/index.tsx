import React, { useState, useEffect } from 'react'
import {
  RefreshCw,
  RotateCcw,
  XCircle,
  CheckCircle2,
  AlertCircle,
  Clock,
  Download,
  Eye,
  Check,
  Sparkles,
  X,
  Search,
} from 'lucide-react'
import { api } from '../../api/client'
import type { SubtitleTask, DownloadTask } from '../../types'

export function TasksPage() {
  const [activeTab, setActiveTab] = useState<'subtitles' | 'downloads'>('subtitles')
  const [tasks, setTasks] = useState<SubtitleTask[]>([])
  const [downloads, setDownloads] = useState<DownloadTask[]>([])
  const [loading, setLoading] = useState(true)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [reprocessingId, setReprocessingId] = useState<string | null>(null)
  const [candidateModalData, setCandidateModalData] = useState<any | null>(null)
  const [candidateActionLoading, setCandidateActionLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'running' | 'awaiting_review' | 'completed' | 'failed'>('all')

  const loadTasks = async () => {
    try {
      const [resTasks, resDownloads] = await Promise.all([
        api.get<{ tasks?: SubtitleTask[]; subtitle_tasks?: SubtitleTask[] }>('/api/tasks').catch(() => ({ tasks: [], subtitle_tasks: [] })),
        api.get<{ downloads?: DownloadTask[]; download_tasks?: DownloadTask[] }>('/api/downloads/history').catch(() => ({ downloads: [], download_tasks: [] })),
      ])
      const taskList = resTasks.tasks || resTasks.subtitle_tasks || []
      const dlList = resDownloads.downloads || resDownloads.download_tasks || []
      setTasks(taskList)
      setDownloads(dlList)
    } catch (err) {
      console.error('Failed to load tasks:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTasks()
  }, [])

  useEffect(() => {
    if (!autoRefresh) return
    const timer = setInterval(() => {
      loadTasks()
    }, 3000)
    return () => clearInterval(timer)
  }, [autoRefresh])

  const handleCancel = async (taskId: string) => {
    try {
      await api.post(`/api/tasks/${taskId}/cancel`)
      loadTasks()
    } catch (err: any) {
      alert('取消任务失败: ' + err.message)
    }
  }

  const handleRetranscribe = async (task: SubtitleTask) => {
    if (!window.confirm(`确定要重新转写音轨《${task.track_title || task.item_title || '此音轨'}》吗？\n这将从头重新执行 ASR 语音识别与双语翻译。`)) {
      return
    }
    setReprocessingId(task.task_id)
    try {
      await api.post(`/api/tasks/${task.task_id}/reprocess`)
      await loadTasks()
    } catch (err: any) {
      alert('发起重新转写失败: ' + err.message)
    } finally {
      setReprocessingId(null)
    }
  }

  const handleRetry = async (taskId: string) => {
    try {
      await api.post(`/api/tasks/${taskId}/retry`)
      loadTasks()
    } catch (err: any) {
      alert('重试任务失败: ' + err.message)
    }
  }

  const handleOpenCandidate = async (taskId: string) => {
    try {
      const data = await api.get(`/api/tasks/${taskId}/candidate`)
      setCandidateModalData(data)
    } catch (err: any) {
      alert('获取候选字幕失败: ' + err.message)
    }
  }

  const handleConfirmCandidate = async (taskId: string) => {
    setCandidateActionLoading(true)
    try {
      await api.post(`/api/tasks/${taskId}/candidate/confirm`)
      setCandidateModalData(null)
      loadTasks()
      alert('已成功采纳并替换台本！')
    } catch (err: any) {
      alert('采纳候选失败: ' + err.message)
    } finally {
      setCandidateActionLoading(false)
    }
  }

  const handleDiscardCandidate = async (taskId: string) => {
    if (!window.confirm('确定放弃该重跑候选吗？正式字幕不会发生改变。')) return
    setCandidateActionLoading(true)
    try {
      await api.post(`/api/tasks/${taskId}/candidate/discard`)
      setCandidateModalData(null)
      loadTasks()
    } catch (err: any) {
      alert('放弃候选失败: ' + err.message)
    } finally {
      setCandidateActionLoading(false)
    }
  }

  const runningCount = tasks.filter((t) => t.status === 'running').length
  const awaitingCount = tasks.filter((t) => t.status === 'awaiting_review').length
  const completedCount = tasks.filter((t) => t.status === 'completed').length
  const failedCount = tasks.filter((t) => t.status === 'failed').length

  const filteredTasks = tasks.filter((t) => {
    if (statusFilter !== 'all' && t.status !== statusFilter) return false
    if (!searchQuery.trim()) return true
    const q = searchQuery.trim().toLowerCase()
    const title = (t.track_title || '').toLowerCase()
    const item = (t.item_title || '').toLowerCase()
    const asr = (t.asr || '').toLowerCase()
    const trans = (t.translation || '').toLowerCase()
    return title.includes(q) || item.includes(q) || asr.includes(q) || trans.includes(q)
  })

  return (
    <div className="tasks-page-container">
      {/* Header */}
      <div className="page-header">
        <div className="page-title-wrap">
          <h1 className="page-title">任务中心</h1>
          <span className="page-subtitle">
            实时监控 ASR 语音识别流水线、LLM 翻译模型任务与后台音视频下载进度
          </span>
        </div>

        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--fg-dim)', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            自动轮询刷新 (3s)
          </label>
          <button type="button" className="btn btn-ghost btn-sm" onClick={loadTasks}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            刷新
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 24, borderBottom: '1px solid var(--border-subtle)', paddingBottom: 12 }}>
        <button
          type="button"
          className={`btn btn-sm ${activeTab === 'subtitles' ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => setActiveTab('subtitles')}
        >
          字幕生成任务 ({tasks.length})
          {runningCount > 0 && (
            <span style={{ background: 'var(--accent-base)', color: '#fff', padding: '1px 6px', borderRadius: 99, fontSize: 10, marginLeft: 6 }}>
              {runningCount} 进行中
            </span>
          )}
        </button>

        <button
          type="button"
          className={`btn btn-sm ${activeTab === 'downloads' ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => setActiveTab('downloads')}
        >
          <Download size={14} />
          下载任务 ({downloads.length})
        </button>
      </div>

      {/* Subtitles Tab Content */}
      {activeTab === 'subtitles' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Filter and search toolbar */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {[
                { id: 'all', label: `全部 (${tasks.length})` },
                { id: 'running', label: `处理中 (${runningCount})` },
                { id: 'awaiting_review', label: `待确认 (${awaitingCount})` },
                { id: 'completed', label: `已完成 (${completedCount})` },
                { id: 'failed', label: `失败 (${failedCount})` },
              ].map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  className={`btn btn-sm ${statusFilter === tab.id ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => setStatusFilter(tab.id as any)}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <div style={{ position: 'relative', width: 240 }}>
              <Search size={14} style={{ position: 'absolute', left: 10, top: 9, color: 'var(--fg-faint)' }} />
              <input
                type="text"
                className="input-field"
                style={{ paddingLeft: 30, paddingRight: 26, fontSize: 12 }}
                placeholder="搜索音轨、作品名、RJ号…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              {searchQuery && (
                <button
                  type="button"
                  style={{ position: 'absolute', right: 8, top: 8, background: 'none', border: 'none', color: 'var(--fg-dim)', cursor: 'pointer', padding: 0 }}
                  onClick={() => setSearchQuery('')}
                >
                  <X size={13} />
                </button>
              )}
            </div>
          </div>

          <div className="tasks-table-container">
            <table className="tasks-table">
              <thead>
                <tr>
                  <th style={{ width: 110 }}>状态</th>
                  <th style={{ minWidth: 260 }}>音轨与作品</th>
                  <th style={{ width: 220 }}>模型配置</th>
                  <th style={{ minWidth: 220, width: 260 }}>处理进度与阶段</th>
                  <th style={{ width: 150, textAlign: 'right' }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredTasks.length === 0 ? (
                  <tr>
                    <td colSpan={5} style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-dim)' }}>
                      {searchQuery || statusFilter !== 'all' ? '未找到符合条件的字幕任务' : '暂无字幕任务记录'}
                    </td>
                  </tr>
                ) : (
                  filteredTasks.map((task) => {
                    const rawProgress = (task.progress !== undefined && task.progress !== null) ? task.progress : 0
                    const isSegment = task.kind === 'segment_reprocess'
                    const isRunning = task.status === 'running'
                    const isAwaitingReview = task.status === 'awaiting_review'
                    const isDone = task.status === 'completed'
                    const isFailed = task.status === 'failed'
                    const isQueued = task.status === 'queued'
                    const isDiscarded = task.status === 'discarded'
                    const pct = (isDone || isAwaitingReview) ? 100 : Math.min(100, Math.max(0, Math.round(rawProgress <= 1 ? rawProgress * 100 : rawProgress)))

                    return (
                      <tr key={task.task_id} className={`task-row task-row-${task.status}`}>
                        <td style={{ verticalAlign: 'top', paddingTop: 14 }}>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
                            <span
                              className={`task-status-badge task-status-${task.status}`}
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 4,
                                fontSize: 11,
                                fontWeight: 700,
                                padding: '3px 8px',
                                borderRadius: 'var(--radius-sm)',
                                background: isRunning
                                  ? 'var(--accent-soft)'
                                  : isAwaitingReview
                                  ? 'rgba(168, 85, 247, 0.15)'
                                  : isDone
                                  ? 'rgba(63, 185, 80, 0.15)'
                                  : isFailed
                                  ? 'rgba(239, 68, 68, 0.15)'
                                  : isDiscarded
                                  ? 'rgba(148, 163, 184, 0.15)'
                                  : 'rgba(245, 158, 11, 0.15)',
                                color: isRunning
                                  ? 'var(--accent-base)'
                                  : isAwaitingReview
                                  ? '#a855f7'
                                  : isDone
                                  ? 'var(--color-green)'
                                  : isFailed
                                  ? 'var(--color-red)'
                                  : isDiscarded
                                  ? 'var(--fg-dim)'
                                  : 'var(--color-amber)',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {isRunning && <Clock size={12} className="animate-spin" />}
                              {isAwaitingReview && <Sparkles size={12} />}
                              {isDone && <CheckCircle2 size={12} />}
                              {isFailed && <AlertCircle size={12} />}
                              {isDiscarded && <XCircle size={12} />}
                              {isQueued && <Clock size={12} />}
                              {isRunning
                                ? '处理中'
                                : isAwaitingReview
                                ? '待确认'
                                : isDone
                                ? '已完成'
                                : isFailed
                                ? '失败'
                                : isDiscarded
                                ? '已放弃'
                                : '排队中'}
                            </span>
                            {isSegment && (
                              <span
                                style={{
                                  fontSize: 10,
                                  fontWeight: 600,
                                  padding: '1px 5px',
                                  borderRadius: 'var(--radius-sm)',
                                  background: 'rgba(56, 189, 248, 0.15)',
                                  color: '#38bdf8',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                局部疑难句
                              </span>
                            )}
                          </div>
                        </td>

                        <td style={{ verticalAlign: 'top', paddingTop: 14 }}>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                            <div style={{ fontWeight: 600, fontSize: 13.5, color: 'var(--fg-main)', wordBreak: 'break-all' }} title={task.track_title || task.item_title || '未命名音轨'}>
                              {task.track_title || task.item_title || '未命名音轨'}
                            </div>
                            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 11.5, color: 'var(--fg-dim)' }}>
                              {task.item_title && task.track_title && (
                                <span title={task.item_title}>
                                  作品: {task.item_title}
                                </span>
                              )}
                              {task.range && (
                                <span style={{ background: 'rgba(255, 255, 255, 0.05)', padding: '1px 5px', borderRadius: 'var(--radius-sm)' }}>
                                  片段: {task.range}
                                </span>
                              )}
                            </div>
                          </div>
                        </td>

                        <td style={{ verticalAlign: 'top', paddingTop: 14 }}>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11 }}>
                            {task.asr ? (
                              <div
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 5,
                                  background: 'rgba(255, 255, 255, 0.04)',
                                  padding: '2px 6px',
                                  borderRadius: 'var(--radius-sm)',
                                  color: 'var(--fg-dim)',
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap',
                                }}
                                title={`ASR: ${task.asr}`}
                              >
                                <span style={{ color: 'var(--accent-base)', fontWeight: 600, fontSize: 10 }}>ASR</span>
                                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{task.asr}</span>
                              </div>
                            ) : null}
                            {task.translation ? (
                              <div
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 5,
                                  background: 'rgba(255, 255, 255, 0.04)',
                                  padding: '2px 6px',
                                  borderRadius: 'var(--radius-sm)',
                                  color: 'var(--fg-dim)',
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap',
                                }}
                                title={`翻译: ${task.translation}`}
                              >
                                <span style={{ color: '#a855f7', fontWeight: 600, fontSize: 10 }}>翻译</span>
                                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{task.translation}</span>
                              </div>
                            ) : null}
                            {!task.asr && !task.translation && <span style={{ color: 'var(--fg-faint)' }}>-</span>}
                          </div>
                        </td>

                        <td style={{ verticalAlign: 'top', paddingTop: 14 }}>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: 'var(--fg-dim)', gap: 8 }}>
                              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={task.message || task.stage || ''}>
                                {task.message || task.stage || (isDone ? '处理完成' : isAwaitingReview ? '候选已就绪' : '等待处理…')}
                              </span>
                              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, flexShrink: 0 }}>
                                {pct}%
                              </span>
                            </div>
                            <div style={{ width: '100%', height: 5, background: 'rgba(255, 255, 255, 0.08)', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
                              <div
                                style={{
                                  width: `${pct}%`,
                                  height: '100%',
                                  background: isFailed ? 'var(--color-red)' : isAwaitingReview ? '#a855f7' : isDone ? 'var(--color-green)' : 'var(--accent-base)',
                                  transition: 'width 0.2s',
                                }}
                              />
                            </div>
                            {task.error && (
                              <div
                                style={{
                                  fontSize: 11,
                                  color: 'var(--color-red)',
                                  background: 'rgba(239, 68, 68, 0.08)',
                                  padding: '3px 6px',
                                  borderRadius: 'var(--radius-sm)',
                                  wordBreak: 'break-all',
                                  lineHeight: 1.3,
                                }}
                                title={task.error}
                              >
                                {task.error}
                              </div>
                            )}
                          </div>
                        </td>

                        <td style={{ verticalAlign: 'top', paddingTop: 14, textAlign: 'right' }}>
                          <div style={{ display: 'inline-flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center', flexWrap: 'wrap' }}>
                            {isRunning && (
                              <button
                                type="button"
                                className="btn btn-sm btn-ghost"
                                onClick={() => handleCancel(task.task_id)}
                                title="取消任务"
                              >
                                <XCircle size={13} />
                                取消
                              </button>
                            )}
                            {isAwaitingReview && (
                              <>
                                <button
                                  type="button"
                                  className="btn btn-sm btn-primary"
                                  onClick={() => handleOpenCandidate(task.task_id)}
                                  title="查看候选台本与当前台本对比"
                                >
                                  <Eye size={12} />
                                  候选
                                </button>
                                <button
                                  type="button"
                                  className="btn btn-sm btn-ghost"
                                  onClick={() => handleConfirmCandidate(task.task_id)}
                                  title="直接采纳并替换正式台本"
                                >
                                  <Check size={13} />
                                </button>
                                <button
                                  type="button"
                                  className="btn btn-sm btn-ghost"
                                  onClick={() => handleDiscardCandidate(task.task_id)}
                                  title="放弃该候选"
                                >
                                  <X size={13} />
                                </button>
                              </>
                            )}
                            {isFailed && (
                              <>
                                <button
                                  type="button"
                                  className="btn btn-sm btn-ghost"
                                  onClick={() => handleRetry(task.task_id)}
                                  title="重试任务"
                                >
                                  <RotateCcw size={13} />
                                  重试
                                </button>
                                {!isSegment && (
                                  <button
                                    type="button"
                                    className="btn btn-sm btn-ghost"
                                    onClick={() => handleRetranscribe(task)}
                                    disabled={reprocessingId === task.task_id}
                                    title="重新发起该音轨的语音识别与翻译任务"
                                  >
                                    <RefreshCw size={13} className={reprocessingId === task.task_id ? 'animate-spin' : ''} />
                                    转写
                                  </button>
                                )}
                              </>
                            )}
                            {isDone && !isSegment && (
                              <button
                                type="button"
                                className="btn btn-sm btn-ghost"
                                onClick={() => handleRetranscribe(task)}
                                disabled={reprocessingId === task.task_id}
                                title="重新发起该音轨的语音识别与翻译任务"
                              >
                                <RotateCcw size={13} className={reprocessingId === task.task_id ? 'animate-spin' : ''} />
                                重新转写
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Downloads Tab Content */}
      {activeTab === 'downloads' && (
        <div className="tasks-table-container">
          <table className="tasks-table">
            <thead>
              <tr>
                <th style={{ width: 110 }}>状态</th>
                <th>下载标题 / 来源 URL</th>
                <th style={{ width: 220 }}>进度与状态</th>
                <th style={{ width: 100, textAlign: 'right' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {downloads.length === 0 ? (
                <tr>
                  <td colSpan={4} style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-dim)' }}>
                    暂无下载任务记录
                  </td>
                </tr>
              ) : (
                downloads.map((dl) => (
                  <tr key={dl.task_id}>
                    <td>
                      <span
                        className={`task-status-badge task-status-${dl.status}`}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 4,
                          fontSize: 11,
                          fontWeight: 700,
                          padding: '3px 8px',
                          borderRadius: 'var(--radius-sm)',
                          background: dl.status === 'completed' ? 'rgba(63, 185, 80, 0.15)' : 'var(--accent-soft)',
                          color: dl.status === 'completed' ? 'var(--color-green)' : 'var(--accent-base)',
                        }}
                      >
                        {dl.status === 'completed' ? <CheckCircle2 size={12} /> : <Download size={12} />}
                        {dl.status === 'completed' ? '已完成' : dl.status === 'downloading' ? '下载中' : dl.status}
                      </span>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600, fontSize: 13.5, color: 'var(--fg-main)' }}>{dl.title || dl.url}</div>
                      <div style={{ fontSize: 11.5, color: 'var(--fg-dim)', marginTop: 2, wordBreak: 'break-all' }}>{dl.url}</div>
                    </td>
                    <td>
                      <div style={{ fontSize: 12, color: 'var(--fg-dim)' }}>
                        {dl.message || (dl.status === 'completed' ? '下载完成' : '下载中…')}
                      </div>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <span style={{ color: 'var(--fg-faint)', fontSize: 12 }}>-</span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Candidate Review Modal */}
      {candidateModalData && (
        <div className="modal-overlay" onClick={() => setCandidateModalData(null)}>
          <div
            className="modal-content"
            style={{ maxWidth: 880, width: '95vw' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <h3 className="modal-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Sparkles size={18} style={{ color: '#a855f7' }} />
                  局部疑难句重跑 · 候选对比
                </h3>
                <span style={{ fontSize: 12, color: 'var(--fg-dim)' }}>
                  时间范围: {candidateModalData.target_start}s - {candidateModalData.target_end}s
                </span>
              </div>
              <button
                type="button"
                className="btn btn-ghost btn-circle"
                onClick={() => setCandidateModalData(null)}
              >
                <X size={18} />
              </button>
            </div>

            <div className="modal-body" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              {/* Current */}
            <div style={{ background: 'var(--bg-card-inset)', padding: 14, borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <h4 style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, color: 'var(--fg-dim)' }}>
                  当前台本 (正式)
                </h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--fg-faint)', marginBottom: 4 }}>原文 (JA)</div>
                  <div style={{ fontSize: 13, background: 'var(--bg-input)', border: '1px solid var(--border-subtle)', padding: 8, borderRadius: 4, maxHeight: 180, overflowY: 'auto', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                      {candidateModalData.current?.source?.map((s: any) => s.text).join('\n') || '（该范围无字幕）'}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--fg-faint)', marginBottom: 4 }}>译文 (ZH)</div>
                  <div style={{ fontSize: 13, background: 'var(--bg-input)', border: '1px solid var(--border-subtle)', padding: 8, borderRadius: 4, maxHeight: 180, overflowY: 'auto', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                      {candidateModalData.current?.target?.map((t: any) => t.text).join('\n') || '（该范围无字幕）'}
                    </div>
                  </div>
                </div>
              </div>

              {/* Candidate */}
              <div style={{ background: 'rgba(168, 85, 247, 0.06)', padding: 14, borderRadius: 'var(--radius-md)', border: '1px solid rgba(168, 85, 247, 0.3)' }}>
                <h4 style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, color: '#c084fc' }}>
                  候选新台本 (重跑生成)
                </h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div>
                    <div style={{ fontSize: 11, color: '#c084fc', marginBottom: 4 }}>原文 (JA)</div>
                  <div style={{ fontSize: 13, background: 'var(--bg-input)', border: '1px solid rgba(168, 85, 247, 0.25)', padding: 8, borderRadius: 4, maxHeight: 180, overflowY: 'auto', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                      {candidateModalData.candidate?.source?.map((s: any) => s.text).join('\n') || '（未生成内容）'}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: '#c084fc', marginBottom: 4 }}>译文 (ZH)</div>
                  <div style={{ fontSize: 13, background: 'var(--bg-input)', border: '1px solid rgba(168, 85, 247, 0.25)', padding: 8, borderRadius: 4, maxHeight: 180, overflowY: 'auto', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                      {candidateModalData.candidate?.target?.map((t: any) => t.text).join('\n') || '（未生成内容）'}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {candidateModalData.warnings?.length > 0 && (
              <div style={{ padding: '0 20px', fontSize: 12, color: 'var(--color-amber)' }}>
                提示：{candidateModalData.warnings.join('；')}
              </div>
            )}

            <div className="modal-footer" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={candidateActionLoading}
                onClick={() => handleDiscardCandidate(candidateModalData.task_id)}
              >
                放弃候选
              </button>
              <div style={{ display: 'flex', gap: 10 }}>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setCandidateModalData(null)}
                >
                  稍后再说
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={candidateActionLoading}
                  onClick={() => handleConfirmCandidate(candidateModalData.task_id)}
                >
                  <Check size={14} />
                  {candidateActionLoading ? '正在替换…' : '接受并替换正式台本'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
