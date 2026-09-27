import React from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { GlobalPlayerBar } from './GlobalPlayerBar'
import { FloatLyrics } from './FloatLyrics'
import { usePlayer } from '../../context/PlayerContext'

export function Shell() {
  const { currentTrack } = usePlayer()

  return (
    <div className={`app-shell ${currentTrack ? 'has-player-bar' : ''}`}>
      <Sidebar />
      <main id="main-content" className="main-content">
        <Outlet />
      </main>
      <GlobalPlayerBar />
      <FloatLyrics />
    </div>
  )
}
