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

export function Shell() {
  const { currentTrack } = usePlayer()

  return (
    <>
      <div className={`shell ${currentTrack ? 'has-player' : ''}`}>
      <Sidebar />
        <main id="main-content" className="frame-main">
        <Outlet />
      </main>
      </div>
      <GlobalPlayerBar />
      <FloatLyricsErrorBoundary>
        <FloatLyrics />
      </FloatLyricsErrorBoundary>
    </>
  )
}
