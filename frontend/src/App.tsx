import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { FontProvider } from './context/FontContext'
import { CornerProvider } from './context/CornerContext'
import { PlayerProvider } from './context/PlayerContext'
import { TaskProvider } from './context/TaskContext'
import { Shell } from './components/layout/Shell'
import { LibraryPage } from './pages/Library'
import { ItemDetailPage } from './pages/ItemDetail'
import { PlayerPage } from './pages/Player'
import { TasksPage } from './pages/Tasks'
import { ProfilesPage } from './pages/Profiles'
import { CreatorsPage } from './pages/Creators'
import { TagsPage } from './pages/Tags'
import { SettingsPage } from './pages/Settings'
import { StatsPage } from './pages/Stats'
import { AboutPage } from './pages/About'

function App() {
  return (
    <BrowserRouter>
      <FontProvider>
      <CornerProvider>
      <TaskProvider>
        <PlayerProvider>
          <Routes>
            <Route path="/" element={<Shell />}>
              <Route index element={<LibraryPage />} />
              <Route path="items/:id" element={<ItemDetailPage />} />
              <Route path="tracks/:trackId/play" element={<PlayerPage />} />
              <Route path="tasks" element={<TasksPage />} />
              <Route path="downloads" element={<TasksPage />} />
              <Route path="profiles" element={<ProfilesPage />} />
              <Route path="creators" element={<CreatorsPage />} />
              <Route path="tags" element={<TagsPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="stats" element={<StatsPage />} />
              <Route path="about" element={<AboutPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </PlayerProvider>
      </TaskProvider>
      </CornerProvider>
      </FontProvider>
    </BrowserRouter>
  )
}

export default App
