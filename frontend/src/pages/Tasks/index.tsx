import { useState } from 'react'
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
    <>
      <div className="page-head task-center-head">
        <div>
          <h1>任务中心</h1>
          <p className="page-sub">
            监控后台 ASR 识别、LLM 翻译流水线以及在线音视频下载进度
          </p>
        </div>

        <button
          type="button"
          onClick={refreshTasks}
          className="ghost small"
        >
          刷新状态
        </button>
      </div>

      <nav className="tab-bar task-center-tabs" role="tablist">
        <button
          type="button"
          onClick={() => setCurrentTab('subtitles')}
          className={`tab ${currentTab === 'subtitles' ? 'active' : ''}`}
        >
          字幕 ({subtitleTasks.length})
        </button>
        <button
          type="button"
          onClick={() => setCurrentTab('downloads')}
          className={`tab ${currentTab === 'downloads' ? 'active' : ''}`}
        >
          下载 ({downloadTasks.length})
        </button>
      </nav>

      {currentTab === 'subtitles' && (
        <div className="task-center-list">
          {subtitleTasks.length === 0 ? (
            <p className="empty">当前没有字幕处理任务。</p>
          ) : (
            subtitleTasks.map((t) => {
              const isRunning = ['queued', 'running', 'processing'].includes(t.status)
              const isFailed = t.status === 'failed'
              const percent = Math.round(t.progress * 100)

              return (
                <article key={t.task_id} className="task-center-row">
                  <div className="task-center-header">
                    <div className="task-center-main">
                      <div className="task-title-group">
                        <strong className="task-title">{t.item_title || t.task_id}</strong>
                      </div>
                      <span className="task-media-name">{t.track_title || '音轨'}</span>
                    </div>

                    <div className="task-center-actions-wrap">
                      <div className="task-center-state">
                        <span className={`status-badge status-${t.status}`}>{t.status}</span>
                        {t.stage && (
                          <span className={`chip task-stage chip-stage-${t.stage}`}>{t.stage}</span>
                        )}
                      </div>
                      <div className="task-actions">
                        {isRunning && (
                          <button
                            type="button"
                            onClick={() => cancelTask(t.task_id)}
                            className="danger ghost small"
                          >
                            取消
                          </button>
                        )}
                        {isFailed && (
                          <button
                            type="button"
                            onClick={() => retryTask(t.task_id)}
                            className="small"
                          >
                            重试
                          </button>
                        )}
                        {!isRunning && (
                          <button
                            type="button"
                            onClick={() => deleteTask(t.task_id)}
                            className="danger ghost small"
                          >
                            删除
                          </button>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="task-progress-section">
                    <div className="task-progress-bar-wrap">
                      <div className="task-progress-track">
                        <div className="task-progress-fill" style={{ width: `${percent}%` }} />
                      </div>
                      <div className="task-center-progress">
                        <span className="task-progress">{percent}</span>%
                      </div>
                    </div>
                  </div>

                  {t.error && (
                    <p className="task-center-message" style={{ color: '#ff7b72' }}>
                      {t.error}
                    </p>
                  )}
                  {t.message && !t.error && (
                    <p className="task-center-message">{t.message}</p>
                  )}
                </article>
              )
            })
          )}
        </div>
      )}

      {currentTab === 'downloads' && (
        <div className="task-center-list">
          {downloadTasks.length === 0 ? (
            <p className="empty">当前没有媒体下载任务。</p>
          ) : (
            downloadTasks.map((t) => {
              const isRunning = t.status === 'running' || t.status === 'pending'
              const isFailed = t.status === 'failed' || t.status === 'error'
              const percent = Math.round((t.progress || 0) * 100)

              return (
                <article key={t.task_id} className="task-center-row">
                  <div className="task-center-header">
                    <div className="task-center-main">
                      <div className="task-title-group">
                        <strong className="task-title">{t.title || t.url}</strong>
                      </div>
                      <span className="task-media-name">{t.url}</span>
                    </div>

                    <div className="task-center-actions-wrap">
                      <div className="task-center-state">
                        <span className={`status-badge status-${t.status}`}>{t.status}</span>
                      </div>
                      <div className="task-actions">
                        {isRunning && (
                          <button
                            type="button"
                            onClick={() => cancelDownload(t.task_id)}
                            className="danger ghost small"
                          >
                            取消
                          </button>
                        )}
                        {isFailed && (
                          <button
                            type="button"
                            onClick={() => retryDownload(t.task_id)}
                            className="small"
                          >
                            重试
                          </button>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="task-progress-section">
                    <div className="task-progress-bar-wrap">
                      <div className="task-progress-track">
                        <div className="task-progress-fill" style={{ width: `${percent}%` }} />
                      </div>
                      <div className="task-center-progress">
                        <span className="task-progress">{percent}</span>%
                      </div>
                    </div>
                  </div>

                  {t.message && <p className="task-center-message">{t.message}</p>}
                </article>
              )
            })
          )}
        </div>
      )}
    </>
  )
}
