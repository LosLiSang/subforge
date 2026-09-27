import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { GlobalPlayerBar } from './GlobalPlayerBar'
import { FloatLyrics } from './FloatLyrics'
import { usePlayer } from '../../context/PlayerContext'

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
      <FloatLyrics />
    </>
  )
}
