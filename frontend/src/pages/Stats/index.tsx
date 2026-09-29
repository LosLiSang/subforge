import React, { useState, useEffect } from 'react'
import {
  Disc,
  Music,
  Clock,
  CheckCircle2,
  Users,
  BarChart3,
} from 'lucide-react'
import { api } from '../../api/client'
import type { StatsData } from '../../types'

export function StatsPage() {
  const [stats, setStats] = useState<StatsData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<StatsData>('/api/stats')
      .then((data) => setStats(data))
      .catch((err) => console.error('Failed to load stats:', err))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-dim)' }}>
        <p>正在载入统计数据…</p>
      </div>
    )
  }

  if (!stats) {
    return (
      <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-dim)' }}>
        <p>未获取到统计数据</p>
      </div>
    )
  }

  const pendingTracks = Math.max(0, stats.total_tracks - stats.subtitled_tracks)

  return (
    <div className="stats-page-container">
      {/* Header */}
      <div className="page-header">
        <div className="page-title-wrap">
          <h1 className="page-title">数据统计</h1>
          <span className="page-subtitle">
            本地作品库收纳总量、音轨时长看板与双语字幕转写覆盖率
          </span>
        </div>
      </div>

      {/* Metric Cards Grid */}
      <div className="card-grid" style={{ marginBottom: 32 }}>
        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--fg-dim)' }}>
            <Disc size={16} />
            <span className="stat-label">作品总数</span>
          </div>
          <span className="stat-value">{stats.total_items}</span>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--fg-dim)' }}>
            <Music size={16} />
            <span className="stat-label">音轨总数</span>
          </div>
          <span className="stat-value">{stats.total_tracks}</span>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--fg-dim)' }}>
            <Clock size={16} />
            <span className="stat-label">媒体总时长</span>
          </div>
          <span className="stat-value" style={{ fontSize: 24 }}>
            {stats.total_duration_label || '00:00:00'}
          </span>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-green)' }}>
            <CheckCircle2 size={16} />
            <span className="stat-label" style={{ color: 'var(--color-green)' }}>已生成字幕音轨</span>
          </div>
          <span className="stat-value" style={{ color: 'var(--color-green)' }}>
            {stats.subtitled_tracks}
          </span>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--fg-dim)' }}>
            <Users size={16} />
            <span className="stat-label">声优与社团总数</span>
          </div>
          <span className="stat-value">{stats.total_creators}</span>
        </div>
      </div>

      {/* Progress & Completion Card */}
      <div className="card-panel" style={{ maxWidth: 700 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <BarChart3 size={18} style={{ color: 'var(--accent-base)' }} />
          <h3 style={{ fontSize: 16, fontWeight: 700 }}>双语字幕就绪完成度</h3>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
          <span style={{ fontSize: 32, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent-base)' }}>
            {stats.subtitled_percentage}%
          </span>
          <span style={{ fontSize: 13, color: 'var(--fg-dim)' }}>
            待处理音轨: <strong style={{ color: 'var(--fg-main)' }}>{pendingTracks}</strong> 轨
          </span>
        </div>

        <div style={{ width: '100%', height: 10, background: 'rgba(255, 255, 255, 0.08)', borderRadius: 99, overflow: 'hidden' }}>
          <div
            style={{
              width: `${stats.subtitled_percentage}%`,
              height: '100%',
              background: 'linear-gradient(90deg, var(--accent-base) 0%, var(--color-green) 100%)',
              borderRadius: 99,
              transition: 'width 0.4s ease',
            }}
          />
        </div>
      </div>
    </div>
  )
}
