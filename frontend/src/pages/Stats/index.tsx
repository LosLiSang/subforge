import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { StatsData } from '../../types'

export function StatsPage() {
  const [stats, setStats] = useState<StatsData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = async () => {
      try {
        const data = await api.get<StatsData>('/api/stats')
        setStats(data)
      } catch (err) {
        console.error('Failed to fetch stats:', err)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) {
    return <div className="page-container text-center py-20 text-fg-dim">正在加载统计数据...</div>
  }

  if (!stats) {
    return <div className="page-container text-center py-20 text-fg-dim">暂无可用统计</div>
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>统计</h1>
          <p className="page-sub">作品库概览与音轨指标</p>
        </div>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <span className="stat-num">{stats.total_items}</span>
          <span className="stat-label">作品</span>
        </div>
        <div className="stat-card">
          <span className="stat-num">{stats.total_tracks}</span>
          <span className="stat-label">音轨</span>
        </div>
        <div className="stat-card">
          <span className="stat-num">{stats.total_duration_label}</span>
          <span className="stat-label">总时长</span>
        </div>
        <div className="stat-card">
          <span className="stat-num">{stats.subtitled_tracks}</span>
          <span className="stat-label">已生成字幕</span>
        </div>
        <div className="stat-card">
          <span className="stat-num">{stats.total_creators}</span>
          <span className="stat-label">创作者</span>
        </div>
      </div>

      <h2 className="dash-h2" style={{ marginTop: 24 }}>音轨状态</h2>
      <div className="status-bars">
        <div className="status-bar-row">
          <span className="status-badge status-playable">可播放</span>
          <div className="status-bar-track">
            <div
              className="status-bar-fill status-playable"
              style={{ width: `${stats.subtitled_percentage}%` }}
            />
          </div>
          <span className="stat-num small">{stats.subtitled_tracks}</span>
        </div>
        <div className="status-bar-row">
          <span className="status-badge status-waiting">未翻译</span>
          <div className="status-bar-track">
            <div
              className="status-bar-fill status-waiting"
              style={{ width: `${Math.max(0, 100 - stats.subtitled_percentage)}%` }}
            />
          </div>
          <span className="stat-num small">{stats.total_tracks - stats.subtitled_tracks}</span>
        </div>
      </div>
    </>
  )
}
