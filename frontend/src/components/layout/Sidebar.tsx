import { useState, useEffect } from 'react'
import { NavLink, Link } from 'react-router-dom'
import { useTasks } from '../../context/TaskContext'

export function Sidebar() {
  const { activeTaskCount } = useTasks()
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (localStorage.getItem('sf.theme') as any) || 'dark'
  })
  const [accent, setAccent] = useState<string>(() => {
    return localStorage.getItem('sf.accent') || 'blue'
  })

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('sf.theme', theme)
  }, [theme])

  useEffect(() => {
    document.documentElement.dataset.accent = accent
    localStorage.setItem('sf.accent', accent)
  }, [accent])

  const toggleTheme = () => {
    setTheme((t) => (t === 'light' ? 'dark' : 'light'))
  }

  const navItems = [
    {
      to: '/',
      label: '作品库',
      exact: true,
      icon: (
        <svg className="nav-ic" viewBox="0 0 24 24" aria-hidden="true">
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
        </svg>
      ),
    },
    {
      to: '/profiles',
      label: '翻译配置',
      icon: (
        <svg className="nav-ic" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
          <path d="M2 12h20" />
        </svg>
      ),
    },
    {
      to: '/creators',
      label: '创作者',
      icon: (
        <svg className="nav-ic" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
          <path d="M16 3.13a4 4 0 0 1 0 7.75" />
        </svg>
      ),
    },
    {
      to: '/settings',
      label: '设置',
      icon: (
        <svg className="nav-ic" viewBox="0 0 24 24" aria-hidden="true">
          <line x1="21" x2="14" y1="4" y2="4" />
          <line x1="10" x2="3" y1="4" y2="4" />
          <line x1="21" x2="12" y1="12" y2="12" />
          <line x1="8" x2="3" y1="12" y2="12" />
          <line x1="21" x2="16" y1="20" y2="20" />
          <line x1="12" x2="3" y1="20" y2="20" />
          <line x1="14" x2="14" y1="2" y2="6" />
          <line x1="8" x2="8" y1="10" y2="14" />
          <line x1="16" x2="16" y1="18" y2="22" />
        </svg>
      ),
    },
    {
      to: '/stats',
      label: '统计',
      icon: (
        <svg className="nav-ic" viewBox="0 0 24 24" aria-hidden="true">
          <line x1="12" x2="12" y1="20" y2="10" />
          <line x1="18" x2="18" y1="20" y2="4" />
          <line x1="6" x2="6" y1="20" y2="16" />
        </svg>
      ),
    },
    {
      to: '/tasks',
      label: '任务中心',
      badge: activeTaskCount > 0 ? activeTaskCount : null,
      icon: (
        <svg className="nav-ic" viewBox="0 0 24 24" aria-hidden="true">
          <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
          <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
        </svg>
      ),
    },
    {
      to: '/about',
      label: '关于',
      icon: (
        <svg className="nav-ic" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 16v-4" />
          <path d="M12 8h.01" />
        </svg>
      ),
    },
  ]

  return (
    <aside className="sidebar">
      <Link className="brand" to="/">
        <img className="brand-icon" src="/subforge-icon.svg" alt="" />
        <span className="brand-text">SubForge</span>
      </Link>

      <nav className="side-nav">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.exact}
            className={({ isActive }) => (isActive ? 'active' : '')}
          >
            {item.icon}
            {item.label}
            {item.badge !== null && item.badge !== undefined && (
              <span className="nav-badge">{item.badge}</span>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="appearance-controls">
        <div className="accent-picker" aria-label="强调色">
          {['blue', 'cyan', 'green', 'violet', 'amber', 'rose'].map((acc) => (
            <button
              key={acc}
              type="button"
              data-accent={acc}
              className={accent === acc ? 'active' : ''}
              onClick={() => setAccent(acc)}
              title={acc}
            />
          ))}
        </div>
        <button
          className={`theme-toggle ${theme === 'light' ? 'is-light' : ''}`}
          type="button"
          onClick={toggleTheme}
          aria-label="切换主题"
        >
          <svg className="theme-icon theme-icon-sun" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
          </svg>
          <svg className="theme-icon theme-icon-moon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20.2 15.4A8.5 8.5 0 0 1 8.6 3.8 8.5 8.5 0 1 0 20.2 15.4Z" />
          </svg>
          <span>{theme === 'light' ? '黑色主题' : '白色主题'}</span>
        </button>
      </div>
    </aside>
  )
}
