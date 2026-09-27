import React, { useEffect, useState } from 'react'
import { Settings, Shield, Network, Sliders, Folder, Save, Key, Trash2 } from 'lucide-react'
import { api } from '../../api/client'
import type { UiSettings } from '../../types'

export function SettingsPage() {
  const [settings, setSettings] = useState<UiSettings | null>(null)
  const [proxyUrl, setProxyUrl] = useState('')
  const [asrConcurrency, setAsrConcurrency] = useState(1)
  const [remoteAsrConcurrency, setRemoteAsrConcurrency] = useState(1)
  const [translateWorkers, setTranslateWorkers] = useState(8)
  const [translationPrompt, setTranslationPrompt] = useState('')
  const [fixedToken, setFixedToken] = useState('')
  const [noAuth, setNoAuth] = useState(false)
  const [deepgramKey, setDeepgramKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [savedSuccess, setSavedSuccess] = useState(false)

  const fetchSettings = async () => {
    try {
      const data = await api.get<UiSettings>('/api/settings')
      setSettings(data)
      setProxyUrl(data.proxy_url || '')
      setAsrConcurrency(data.asr_concurrency || 1)
      setRemoteAsrConcurrency(data.remote_asr_concurrency || 1)
      setTranslateWorkers(data.translate_workers || 8)
      setTranslationPrompt(data.translation_prompt || '')
      setNoAuth(data.no_auth || false)
    } catch (err) {
      console.error('Failed to fetch settings:', err)
    }
  }

  useEffect(() => {
    fetchSettings()
  }, [])

  const handleSelectLibrary = async () => {
    try {
      await api.post('/library/select')
      fetchSettings()
    } catch (err: any) {
      alert('选择媒体库路径失败: ' + err.message)
    }
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setSavedSuccess(false)
    try {
      await api.post('/settings', {
        proxy_url: proxyUrl.trim() || undefined,
        asr_concurrency: asrConcurrency,
        remote_asr_concurrency: remoteAsrConcurrency,
        translate_workers: translateWorkers,
        translation_prompt: translationPrompt.trim() || undefined,
        fixed_token: fixedToken.trim() || undefined,
        no_auth: noAuth ? 'on' : undefined,
        deepgram_api_key: deepgramKey.trim() || undefined,
      })
      setSavedSuccess(true)
      setFixedToken('')
      setDeepgramKey('')
      fetchSettings()
      setTimeout(() => setSavedSuccess(false), 3000)
    } catch (err: any) {
      alert('保存设置失败: ' + err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteDeepgramKey = async () => {
    if (!confirm('确认删除已保存的 Deepgram API Key 吗？')) return
    try {
      await api.post('/settings/deepgram/delete-key')
      fetchSettings()
    } catch (err: any) {
      alert('删除失败: ' + err.message)
    }
  }

  return (
    <div className="page-container space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">系统设置</h1>
        <p className="text-sm text-fg-dim mt-0.5">
          配置本地媒体库路径、网络代理、并发性能限制与系统访问权限
        </p>
      </div>

      <form onSubmit={handleSave} className="space-y-6">
        {savedSuccess && (
          <div className="p-3 bg-green-900/30 border border-green-800 rounded-lg text-green-300 text-sm">
            设置已成功保存！
          </div>
        )}

        {/* Library Path */}
        <div className="p-4 bg-panel rounded-xl border border-line space-y-3">
          <div className="flex items-center gap-2 font-semibold text-white text-sm">
            <Folder size={18} className="text-accent" />
            媒体库存储路径
          </div>
          <div className="flex gap-2 items-center">
            <input
              type="text"
              readOnly
              value={settings?.library_root || '未配置媒体库路径'}
              className="input-text flex-1 font-mono text-xs bg-panel-2"
            />
            <button
              type="button"
              onClick={handleSelectLibrary}
              className="btn btn-secondary flex items-center gap-1.5"
            >
              重新选择目录
            </button>
          </div>
        </div>

        {/* Network & Proxy */}
        <div className="p-4 bg-panel rounded-xl border border-line space-y-3">
          <div className="flex items-center gap-2 font-semibold text-white text-sm">
            <Network size={18} className="text-accent" />
            网络代理设置
          </div>
          <div className="space-y-1">
            <label className="text-xs text-fg-dim">HTTP / SOCKS5 代理地址</label>
            <input
              type="text"
              value={proxyUrl}
              onChange={(e) => setProxyUrl(e.target.value)}
              placeholder="例: http://127.0.0.1:7890 或 socks5://127.0.0.1:1080"
              className="input-text font-mono text-xs"
            />
            <small className="text-xs text-fg-faint block">
              用于 YouTube 下载、境外 API 连接；访问 B站 时系统会自动优先尝试直连。
            </small>
          </div>
        </div>

        {/* Performance & Concurrency */}
        <div className="p-4 bg-panel rounded-xl border border-line space-y-4">
          <div className="flex items-center gap-2 font-semibold text-white text-sm">
            <Sliders size={18} className="text-accent" />
            并发与性能
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-xs text-fg-dim">本地 ASR 并发上限 (线程数)</label>
              <input
                type="number"
                min={1}
                max={8}
                value={asrConcurrency}
                onChange={(e) => setAsrConcurrency(parseInt(e.target.value) || 1)}
                className="input-text text-sm"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-fg-dim">翻译并发 Workers</label>
              <input
                type="number"
                min={1}
                max={32}
                value={translateWorkers}
                onChange={(e) => setTranslateWorkers(parseInt(e.target.value) || 8)}
                className="input-text text-sm"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-xs text-fg-dim">自定义翻译系统提示词 (Prompt)</label>
            <textarea
              value={translationPrompt}
              onChange={(e) => setTranslationPrompt(e.target.value)}
              placeholder="可选，留空则使用默认的高质量同人音声二次元翻译预设"
              className="input-text text-xs h-24 font-mono"
            />
          </div>
        </div>

        {/* Security & Access */}
        <div className="p-4 bg-panel rounded-xl border border-line space-y-4">
          <div className="flex items-center gap-2 font-semibold text-white text-sm">
            <Shield size={18} className="text-accent" />
            访问与安全模式
          </div>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={noAuth}
              onChange={(e) => setNoAuth(e.target.checked)}
              className="accent-accent"
            />
            <span className="text-sm font-medium">本地免 Token 登录模式</span>
          </label>

          <div className="space-y-1 pt-1">
            <label className="text-xs text-fg-dim">固定访问密码 / Token (可选)</label>
            <input
              type="password"
              value={fixedToken}
              onChange={(e) => setFixedToken(e.target.value)}
              placeholder="设置后下次启动可通过固定密码访问，留空保持原样"
              className="input-text text-sm"
            />
          </div>
        </div>

        <div className="flex justify-end pt-2">
          <button
            type="submit"
            disabled={saving}
            className="btn btn-primary flex items-center gap-2 px-6"
          >
            <Save size={16} />
            {saving ? '正在保存...' : '保存系统设置'}
          </button>
        </div>
      </form>
    </div>
  )
}
