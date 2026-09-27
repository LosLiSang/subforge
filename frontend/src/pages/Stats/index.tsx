import React, { useEffect, useState } from 'react'
import { BarChart3, Clock, Disc, Users, CheckCircle } from 'lucide-react'
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
    <div className="page-container space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">媒体库统计</h1>
        <p className="text-sm text-fg-dim mt-0.5">
          查看音频总时长、字幕完成率及创作者分布情况
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-4 bg-panel rounded-xl border border-line flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-accent">
            <Disc size={20} />
          </div>
          <div>
            <div className="text-xs text-fg-dim">作品总数</div>
            <div className="text-2xl font-bold text-white">{stats.total_items}</div>
          </div>
        </div>

        <div className="p-4 bg-panel rounded-xl border border-line flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
            <Clock size={20} />
          </div>
          <div>
            <div className="text-xs text-fg-dim">音频总时长</div>
            <div className="text-2xl font-bold text-white">{stats.total_duration_label}</div>
          </div>
        </div>

        <div className="p-4 bg-panel rounded-xl border border-line flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-green-500/10 border border-green-500/20 flex items-center justify-center text-green-400">
            <CheckCircle size={20} />
          </div>
          <div>
            <div className="text-xs text-fg-dim">字幕完成率</div>
            <div className="text-2xl font-bold text-white">{stats.subtitled_percentage}%</div>
          </div>
        </div>

        <div className="p-4 bg-panel rounded-xl border border-line flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
            <Users size={20} />
          </div>
          <div>
            <div className="text-xs text-fg-dim">创作者数量</div>
            <div className="text-2xl font-bold text-white">{stats.total_creators}</div>
          </div>
        </div>
      </div>

      <div className="p-6 bg-panel rounded-xl border border-line space-y-4">
        <h2 className="text-base font-semibold">详细音轨汇总</h2>
        <div className="text-sm text-fg-dim space-y-2">
          <div className="flex justify-between py-1 border-b border-line">
            <span>音轨总数量</span>
            <span className="font-semibold text-white">{stats.total_tracks} 轨</span>
          </div>
          <div className="flex justify-between py-1 border-b border-line">
            <span>已生成中文字幕音轨</span>
            <span className="font-semibold text-green-400">{stats.subtitled_tracks} 轨</span>
          </div>
          <div className="flex justify-between py-1 border-b border-line">
            <span>未翻译音轨</span>
            <span className="font-semibold text-fg-faint">
              {stats.total_tracks - stats.subtitled_tracks} 轨
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
