import React, { Component, type ErrorInfo, type ReactNode } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { GlobalPlayerBar } from './GlobalPlayerBar'
import { FloatLyrics } from './FloatLyrics'
import { usePlayer } from '../../context/PlayerContext'

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

  return (
    <>
      <div className={`shell ${currentTrack ? 'has-player' : ''}`}>
      <Sidebar />
        <main id="main-content" className="frame-main">
        <PageErrorBoundary>
        <Outlet />
        </PageErrorBoundary>
      </main>
      </div>
      <GlobalPlayerBar />
      <FloatLyricsErrorBoundary>
        <FloatLyrics />
      </FloatLyricsErrorBoundary>
    </>
  )
}
