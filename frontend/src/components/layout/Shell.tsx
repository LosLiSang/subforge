import React, { Component, useState, type ErrorInfo, type ReactNode } from 'react'
import { Link, Outlet } from 'react-router-dom'
import { Menu, Inbox } from 'lucide-react'
import { Sidebar } from './Sidebar'
import { GlobalPlayerBar } from './GlobalPlayerBar'
import { FloatLyrics } from './FloatLyrics'
import { usePlayer } from '../../context/PlayerContext'
import { useTasks } from '../../context/TaskContext'
import subforgeLogo from '../../assets/subforge-icon.svg'

class FloatLyricsErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false }
  static getDerivedStateFromError() {
    return { hasError: true }
  }
  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('FloatLyrics crashed safely:', error, errorInfo)
  }
  render() {
    if (this.state.hasError) return null
    return this.props.children
  }
}

class PageErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean; error: Error | null }> {
  state: { hasError: boolean; error: Error | null } = { hasError: false, error: null }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }
  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Page render error:', error, errorInfo)
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 48, textAlign: 'center' }}>
          <h2 style={{ fontSize: 18, marginBottom: 12, color: 'var(--color-red)' }}>页面加载发生错误</h2>
          <p style={{ fontSize: 14, color: 'var(--fg-dim)', marginBottom: 20 }}>
            {this.state.error?.message || '未知错误'}
          </p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                this.setState({ hasError: false, error: null })
                window.location.reload()
              }}
            >
              刷新页面
            </button>
            <a href="/" className="btn btn-primary">
              返回作品库
            </a>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

export function Shell() {
  const { currentTrack } = usePlayer()
  const { activeTaskCount } = useTasks()
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  return (
    <>
      <div className={`shell ${currentTrack ? 'has-player' : ''}`}>
        {mobileNavOpen && (
          <div
            className="sidebar-backdrop"
            onClick={() => setMobileNavOpen(false)}
            aria-hidden="true"
          />
        )}
        <Sidebar isOpen={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
        <div className="shell-content-wrap">
          <header className="mobile-topbar">
            <button
              type="button"
              className="mobile-menu-btn"
              onClick={() => setMobileNavOpen(true)}
              aria-label="打开导航菜单"
            >
              <Menu size={20} />
            </button>
            <Link className="mobile-brand" to="/" onClick={() => setMobileNavOpen(false)}>
              <img src={subforgeLogo} alt="SubForge" width={24} height={24} />
              <span>SubForge</span>
            </Link>
            <Link
              className="mobile-tasks-link"
              to="/tasks"
              aria-label={activeTaskCount > 0 ? `任务中心（${activeTaskCount} 个进行中）` : '任务中心'}
              title="任务中心"
            >
              <Inbox size={18} aria-hidden="true" />
              {activeTaskCount > 0 ? <span className="mobile-tasks-badge">{activeTaskCount}</span> : null}
            </Link>
          </header>
          <main id="main-content" className="frame-main">
            <PageErrorBoundary>
              <Outlet />
            </PageErrorBoundary>
          </main>
        </div>
      </div>
      <GlobalPlayerBar />
      <FloatLyricsErrorBoundary>
        <FloatLyrics />
      </FloatLyricsErrorBoundary>
    </>
  )
}
