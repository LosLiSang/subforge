import React, { createContext, useContext, useEffect, useState } from 'react'
import type { SubtitleTask, DownloadTask } from '../types'
import { api } from '../api/client'

interface TaskContextType {
  subtitleTasks: SubtitleTask[]
  downloadTasks: DownloadTask[]
  activeTaskCount: number
  refreshTasks: () => Promise<void>
  cancelTask: (taskId: string) => Promise<void>
  retryTask: (taskId: string) => Promise<void>
  deleteTask: (taskId: string) => Promise<void>
  cancelDownload: (taskId: string) => Promise<void>
  retryDownload: (taskId: string) => Promise<void>
}

const TaskContext = createContext<TaskContextType | null>(null)

export function TaskProvider({ children }: { children: React.ReactNode }) {
  const [subtitleTasks, setSubtitleTasks] = useState<SubtitleTask[]>([])
  const [downloadTasks, setDownloadTasks] = useState<DownloadTask[]>([])

  const refreshTasks = async () => {
    try {
      const data = await api.get<{
        subtitle_tasks: SubtitleTask[]
        download_tasks: DownloadTask[]
      }>('/api/downloads/history')
      setSubtitleTasks(data.subtitle_tasks || [])
      setDownloadTasks(data.download_tasks || [])
    } catch (e) {
      // ignore if unauthenticated or error
    }
  }

  useEffect(() => {
    refreshTasks()
    const interval = setInterval(() => {
      refreshTasks()
    }, 3000)
    return () => clearInterval(interval)
  }, [])

  const activeTaskCount =
    subtitleTasks.filter((t) => ['queued', 'running', 'processing'].includes(t.status)).length +
    downloadTasks.filter((t) => ['pending', 'running'].includes(t.status)).length

  const cancelTask = async (taskId: string) => {
    await api.post(`/tasks/${taskId}/cancel`)
    await refreshTasks()
  }

  const retryTask = async (taskId: string) => {
    await api.post(`/tasks/${taskId}/retry`)
    await refreshTasks()
  }

  const deleteTask = async (taskId: string) => {
    await api.post(`/tasks/${taskId}/delete`)
    await refreshTasks()
  }

  const cancelDownload = async (taskId: string) => {
    await api.post(`/api/imports/${taskId}/cancel`)
    await refreshTasks()
  }

  const retryDownload = async (taskId: string) => {
    await api.post(`/api/imports/${taskId}/retry`)
    await refreshTasks()
  }

  return (
    <TaskContext.Provider
      value={{
        subtitleTasks,
        downloadTasks,
        activeTaskCount,
        refreshTasks,
        cancelTask,
        retryTask,
        deleteTask,
        cancelDownload,
        retryDownload,
      }}
    >
      {children}
    </TaskContext.Provider>
  )
}

export function useTasks() {
  const ctx = useContext(TaskContext)
  if (!ctx) throw new Error('useTasks must be used within TaskProvider')
  return ctx
}
