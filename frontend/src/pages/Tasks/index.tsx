import React, { useState } from 'react'
import {
  DownloadCloud,
  Sparkles,
  RotateCcw,
  XCircle,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Clock,
} from 'lucide-react'
import { useTasks } from '../../context/TaskContext'

export function TasksPage() {
  const {
    subtitleTasks,
    downloadTasks,
    refreshTasks,
    cancelTask,
    retryTask,
    deleteTask,
    cancelDownload,
    retryDownload,
  } = useTasks()

  const [currentTab, setCurrentTab] = useState<'subtitles' | 'downloads'>('subtitles')

  return (
    <div className="page-container space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">任务与下载中心</h1>
          <p className="text-sm text-fg-dim mt-0.5">
            监控后台 ASR 识别、LLM 翻译流水线以及在线音视频下载进度
          </p>
        </div>

        <button
          type="button"
          onClick={refreshTasks}
          className="btn btn-secondary text-xs flex items-center gap-1.5"
        >
          <RotateCcw size={14} /> 刷新状态
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-line gap-2">
        <button
          type="button"
          onClick={() => setCurrentTab('subtitles')}
          className={`tab-btn ${currentTab === 'subtitles' ? 'active' : ''}`}
        >
          <Sparkles size={16} />
          字幕生成流水线 ({subtitleTasks.length})
        </button>
        <button
          type="button"
          onClick={() => setCurrentTab('downloads')}
          className={`tab-btn ${currentTab === 'downloads' ? 'active' : ''}`}
        >
          <DownloadCloud size={16} />
          媒体下载任务 ({downloadTasks.length})
        </button>
      </div>

      {/* Tab Panels */}
      {currentTab === 'subtitles' && (
        <div className="space-y-3">
          {subtitleTasks.length === 0 ? (
            <div className="empty-state py-16">
              <p className="text-fg-dim text-sm">暂无字幕生成任务</p>
            </div>
          ) : (
            subtitleTasks.map((t) => {
              const isRunning = ['queued', 'running', 'processing'].includes(t.status)
              const isFailed = t.status === 'failed'
              const isCompleted = t.status === 'completed' || t.status === 'complete'

              return (
                <div key={t.task_id} className="task-card">
                  <div className="flex items-center justify-between gap-4">
                    <div className="space-y-1 min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        {isRunning && <Clock size={16} className="text-yellow-400 animate-spin" />}
                        {isFailed && <AlertCircle size={16} className="text-red-400" />}
                        {isCompleted && <CheckCircle2 size={16} className="text-green-400" />}
                        <span className="font-semibold text-sm text-white truncate">
                          {t.track_title || t.task_id}
                        </span>
                        {t.stage && (
                          <span className="badge badge-accent uppercase text-xs">{t.stage}</span>
                        )}
                      </div>
                      <div className="text-xs text-fg-dim">
                        作品: {t.item_title || '未知'} · 模型: {t.profile_label || '默认'}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 flex-none">
                      {isRunning && (
                        <button
                          type="button"
                          onClick={() => cancelTask(t.task_id)}
                          className="btn btn-secondary btn-sm text-red-400 flex items-center gap-1"
                        >
                          <XCircle size={14} /> 取消
                        </button>
                      )}
                      {isFailed && (
                        <button
                          type="button"
                          onClick={() => retryTask(t.task_id)}
                          className="btn btn-secondary btn-sm flex items-center gap-1"
                        >
                          <RotateCcw size={14} /> 重试
                        </button>
                      )}
                      {!isRunning && (
                        <button
                          type="button"
                          onClick={() => deleteTask(t.task_id)}
                          className="btn btn-danger btn-sm p-1.5"
                          title="删除任务记录"
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Progress bar */}
                  <div className="space-y-1 pt-2">
                    <div className="progress-track">
                      <div
                        className={`progress-fill ${isFailed ? 'bg-red-500' : isCompleted ? 'bg-green-500' : 'bg-accent'}`}
                        style={{ width: `${Math.round(t.progress * 100)}%` }}
                      />
                    </div>
                    <div className="flex justify-between text-xs text-fg-faint">
                      <span>{t.message || (isCompleted ? '已完成' : '处理中...')}</span>
                      <span>{Math.round(t.progress * 100)}%</span>
                    </div>
                  </div>

                  {t.error && (
                    <div className="mt-2 p-2 bg-red-950/40 border border-red-800 rounded text-xs text-red-300 font-mono overflow-x-auto">
                      {t.error}
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      )}

      {currentTab === 'downloads' && (
        <div className="space-y-3">
          {downloadTasks.length === 0 ? (
            <div className="empty-state py-16">
              <p className="text-fg-dim text-sm">暂无在线下载任务</p>
            </div>
          ) : (
            downloadTasks.map((t) => {
              const isRunning = t.status === 'running' || t.status === 'pending'
              const isFailed = t.status === 'failed' || t.status === 'error'
              const isCompleted = t.status === 'complete' || t.status === 'completed'

              return (
                <div key={t.task_id} className="task-card">
                  <div className="flex items-center justify-between gap-4">
                    <div className="space-y-1 min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        {isRunning && <Clock size={16} className="text-yellow-400 animate-spin" />}
                        {isFailed && <AlertCircle size={16} className="text-red-400" />}
                        {isCompleted && <CheckCircle2 size={16} className="text-green-400" />}
                        <span className="font-semibold text-sm text-white truncate">
                          {t.title || t.url}
                        </span>
                      </div>
                      <div className="text-xs text-fg-dim truncate">
                        来源 URL: {t.url}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 flex-none">
                      {isRunning && (
                        <button
                          type="button"
                          onClick={() => cancelDownload(t.task_id)}
                          className="btn btn-secondary btn-sm text-red-400 flex items-center gap-1"
                        >
                          <XCircle size={14} /> 取消
                        </button>
                      )}
                      {isFailed && (
                        <button
                          type="button"
                          onClick={() => retryDownload(t.task_id)}
                          className="btn btn-secondary btn-sm flex items-center gap-1"
                        >
                          <RotateCcw size={14} /> 重试
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="space-y-1 pt-2">
                    <div className="progress-track">
                      <div
                        className={`progress-fill ${isFailed ? 'bg-red-500' : isCompleted ? 'bg-green-500' : 'bg-accent'}`}
                        style={{ width: `${Math.round((t.progress || 0) * 100)}%` }}
                      />
                    </div>
                    <div className="flex justify-between text-xs text-fg-faint">
                      <span>{t.message || (isCompleted ? '下载完成' : '下载中...')}</span>
                      <span>{Math.round((t.progress || 0) * 100)}%</span>
                    </div>
                  </div>
                </div>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
