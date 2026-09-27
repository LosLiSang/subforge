import React from 'react'
import { NavLink } from 'react-router-dom'
import {
  Library,
  BarChart2,
  Cpu,
  Users,
  Settings,
  DownloadCloud,
  Info,
  Headphones,
} from 'lucide-react'
import { useTasks } from '../../context/TaskContext'

export function Sidebar() {
  const { activeTaskCount } = useTasks()

  const navItems = [
    { to: '/', label: '作品库', icon: Library, exact: true },
    { to: '/stats', label: '统计', icon: BarChart2 },
    { to: '/profiles', label: '模型配置', icon: Cpu },
    { to: '/creators', label: '创作者', icon: Users },
    { to: '/settings', label: '系统设置', icon: Settings },
    {
      to: '/tasks',
      label: '任务与下载',
      icon: DownloadCloud,
      badge: activeTaskCount > 0 ? activeTaskCount : null,
    },
    { to: '/about', label: '关于', icon: Info },
  ]

  return (
    <aside className="sidebar">
      <div className="brand-header">
        <div className="brand-icon-wrapper">
          <Headphones className="brand-icon text-accent" size={24} />
        </div>
        <span className="brand-title">SubForge</span>
      </div>

      <nav className="nav-list">
        {navItems.map((item) => {
          const Icon = item.icon
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.exact}
              className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
            >
              <Icon size={18} className="nav-icon" />
              <span className="nav-label">{item.label}</span>
              {item.badge !== null && (
                <span className="nav-badge">{item.badge}</span>
              )}
            </NavLink>
          )
        })}
      </nav>
    </aside>
  )
}
