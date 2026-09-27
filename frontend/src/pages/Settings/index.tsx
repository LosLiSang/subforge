import { useEffect, useState } from 'react'
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
    <>
      <div className="page-head">
        <div>
          <h1>系统设置</h1>
          <p className="page-sub">
          配置本地媒体库路径、网络代理、并发性能限制与系统访问权限
        </p>
      </div>
      </div>

      <form onSubmit={handleSave} className="settings-dashboard">
        {savedSuccess && (
          <div className="model-status-row" style={{ color: '#3fb950', borderColor: '#2ea04340', marginBottom: 16 }}>
            设置已成功保存！
          </div>
        )}

        <section className="dash-section tab-panel active">
          <div className="field-list">
            <div className="field">
              <div className="field-label">媒体库存储路径</div>
              <div className="path-picker">
                <input readOnly value={settings?.library_root || '未配置媒体库路径'} />
                <button type="button" className="pick-check-btn" onClick={handleSelectLibrary}>
                  重新选择目录
                </button>
              </div>
              <small>当前正在使用的同人音声与 ASMR 媒体库根路径。</small>
            </div>

            <div className="field">
              <div className="field-label">网络代理 (HTTP/SOCKS5)</div>
              <input
                type="text"
                value={proxyUrl}
                onChange={(e) => setProxyUrl(e.target.value)}
                placeholder="例: http://127.0.0.1:7890 或 socks5://127.0.0.1:1080"
              />
              <small>用于 YouTube 下载、境外 API 连接；访问 B站 时系统会自动优先尝试直连。</small>
            </div>

            <div className="field-inline">
              <div>
                <div className="field-label">本地 ASR 并发上限 (线程数)</div>
                <small>本地 Faster-Whisper 转录并发数</small>
              </div>
              <input
                type="number"
                min={1}
                max={8}
                className="narrow"
                value={asrConcurrency}
                onChange={(e) => setAsrConcurrency(parseInt(e.target.value) || 1)}
              />
            </div>

            <div className="field-inline">
              <div>
                <div className="field-label">翻译 Workers 并发数量</div>
                <small>LLM 翻译并发协程数</small>
              </div>
              <input
                type="number"
                min={1}
                max={32}
                className="narrow"
                value={translateWorkers}
                onChange={(e) => setTranslateWorkers(parseInt(e.target.value) || 8)}
              />
            </div>

            <div className="field">
              <div className="field-label">自定义翻译系统提示词 (Prompt)</div>
              <textarea
                value={translationPrompt}
                onChange={(e) => setTranslationPrompt(e.target.value)}
                placeholder="可选，留空则使用默认的高质量同人音声二次元翻译预设"
              />
            </div>

            <div className="field">
              <label className="check-field">
                <span>
                  <input
                    type="checkbox"
                    checked={noAuth}
                    onChange={(e) => setNoAuth(e.target.checked)}
                  />
                  本地免 Token 登录模式
                </span>
              </label>
            </div>

            <div className="field">
              <div className="field-label">固定访问密码 / Token (可选)</div>
              <input
                type="password"
                value={fixedToken}
                onChange={(e) => setFixedToken(e.target.value)}
                placeholder="设置后下次启动可通过固定密码访问，留空保持原样"
              />
            </div>
          </div>

          <div className="dash-actions" style={{ marginTop: 24 }}>
            <button type="submit" disabled={saving} className="primary">
              {saving ? '正在保存…' : '保存系统设置'}
            </button>
          </div>
        </section>
      </form>
    </>
  )
}
