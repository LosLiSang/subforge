import React, { useState, useEffect } from 'react'
import {
  Save,
  Folder,
  Check,
  Type,
  RotateCcw,
  FolderKanban,
  Cpu,
  Globe,
  FileEdit,
  ShieldCheck,
  Trash2,
  Square,
  Image as ImageIcon,
  UploadCloud,
  Sparkles,
} from 'lucide-react'
import { api } from '../../api/client'
import type { UiSettings, ModelProfile } from '../../types'
import { useFont } from '../../context/FontContext'
import { useCornerStyle } from '../../context/CornerContext'

type SettingsTab = 'general' | 'models' | 'cover' | 'appearance' | 'pipeline' | 'proxy' | 'prompt' | 'security'

export function SettingsPage() {
  const { fontSettings, updateFontSettings, resetFontSettings } = useFont()
  const { cornerSettings, updateCornerSettings, setAllCorners, resetCornerSettings } = useCornerStyle()
  const [activeTab, setActiveTab] = useState<SettingsTab>('general')
  const [settings, setSettings] = useState<UiSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  // Form fields
  const [libraryRoot, setLibraryRoot] = useState('')
  const [proxyUrl, setProxyUrl] = useState('')
  const [asrConcurrency, setAsrConcurrency] = useState(1)
  const [remoteAsrConcurrency, setRemoteAsrConcurrency] = useState(20)
  const [remoteAsrTaskConcurrency, setRemoteAsrTaskConcurrency] = useState(20)
  const [translateWorkers, setTranslateWorkers] = useState(20)
  const [downloadHistoryMaxCount, setDownloadHistoryMaxCount] = useState(200)
  const [downloadHistoryMaxAgeDays, setDownloadHistoryMaxAgeDays] = useState(30)
  const [translationPrompt, setTranslationPrompt] = useState('')
  const [noAuth, setNoAuth] = useState(false)
  const [fixedToken, setFixedToken] = useState('')
  const [deepgramKey, setDeepgramKey] = useState('')

  // Default Cover fields
  const [coverMode, setCoverMode] = useState<'preset' | 'url' | 'upload'>('preset')
  const [coverPreset, setCoverPreset] = useState<'default' | 'headphones' | 'wave' | 'studio'>('default')
  const [coverUrl, setCoverUrl] = useState('')
  const [coverFile, setCoverFile] = useState<File | null>(null)
  const [coverFilePreview, setCoverFilePreview] = useState<string | null>(null)
  const [coverNonce, setCoverNonce] = useState(Date.now())
  const [savingCover, setSavingCover] = useState(false)

  // Default Models fields
  const [availableAsrProfiles, setAvailableAsrProfiles] = useState<ModelProfile[]>([])
  const [availableLlmProfiles, setAvailableLlmProfiles] = useState<ModelProfile[]>([])
  const [defaultAsrProvider, setDefaultAsrProvider] = useState<'local' | 'model' | 'deepgram'>('local')
  const [defaultAsrProfileId, setDefaultAsrProfileId] = useState('')
  const [defaultWhisperModel, setDefaultWhisperModel] = useState('large-v3')
  const [defaultLlmProfileId, setDefaultLlmProfileId] = useState('')
  const [defaultMergeProfileId, setDefaultMergeProfileId] = useState('')
  const [defaultScene, setDefaultScene] = useState<'asmr' | 'normal'>('asmr')
  const [defaultChunkSeconds, setDefaultChunkSeconds] = useState(60)
  const [savingModels, setSavingModels] = useState(false)

  const loadSettings = async () => {
    setLoading(true)
    try {
      const [data, profs] = await Promise.all([
        api.get<UiSettings>('/api/settings'),
        api.get<{ asr_profiles: ModelProfile[]; llm_profiles: ModelProfile[] }>('/api/profiles').catch(() => ({ asr_profiles: [], llm_profiles: [] })),
      ])
      setSettings(data)
      setAvailableAsrProfiles(profs.asr_profiles || [])
      setAvailableLlmProfiles(profs.llm_profiles || [])
      setLibraryRoot(data.library_root || '')
      setProxyUrl(data.proxy_url || '')
      setAsrConcurrency(data.asr_concurrency || 1)
      setRemoteAsrConcurrency(data.remote_asr_concurrency || 20)
      setRemoteAsrTaskConcurrency(data.remote_asr_task_concurrency || 20)
      setTranslateWorkers(data.translate_workers || 20)
      setDownloadHistoryMaxCount(data.download_history_max_count || 200)
      setDownloadHistoryMaxAgeDays(data.download_history_max_age_days || 30)
      setTranslationPrompt(data.translation_prompt || '')
      setNoAuth(!!data.no_auth)
      if (data.default_cover) {
        setCoverMode(data.default_cover.mode || 'preset')
        setCoverPreset(data.default_cover.preset || 'default')
        setCoverUrl(data.default_cover.url || '')
      }
      if (data.default_processing) {
        setDefaultAsrProvider((data.default_processing.asr_provider as any) || 'local')
        setDefaultAsrProfileId(data.default_processing.asr_profile_id || '')
        setDefaultWhisperModel(data.default_processing.whisper_model || 'large-v3')
        setDefaultLlmProfileId(data.default_processing.llm_profile_id || '')
        setDefaultMergeProfileId(data.default_processing.merge_profile_id || '')
        setDefaultScene((data.default_processing.scene as any) || 'asmr')
        setDefaultChunkSeconds(data.default_processing.asr_chunk_seconds || 60)
      } else {
        if (profs.asr_profiles && profs.asr_profiles.length > 0) {
          setDefaultAsrProfileId(profs.asr_profiles[0].profile_id)
        }
        if (profs.llm_profiles && profs.llm_profiles.length > 0) {
          setDefaultLlmProfileId(profs.llm_profiles[0].profile_id)
        }
      }
    } catch (err: any) {
      setErrorMsg('加载设置失败: ' + err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadSettings()
  }, [])

  const handleSelectFolder = async () => {
    try {
      const res = await api.post<{ selection_id?: string; cancelled?: boolean }>('/picker/directory')
      if (res.selection_id) {
        const formData = new FormData()
        formData.append('selection_id', res.selection_id)
        await api.postForm('/library/select', formData)
        setSuccessMsg('已更新媒体库根目录')
        loadSettings()
      }
    } catch (err: any) {
      alert('选择文件夹失败: ' + err.message)
    }
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setSuccessMsg(null)
    setErrorMsg(null)
    try {
      const formData = new FormData()
      if (libraryRoot) formData.append('library_root', libraryRoot)
      if (proxyUrl) formData.append('proxy_url', proxyUrl)
      formData.append('asr_concurrency', String(asrConcurrency))
      formData.append('remote_asr_concurrency', String(remoteAsrConcurrency))
      formData.append('remote_asr_task_concurrency', String(remoteAsrTaskConcurrency))
      formData.append('translate_workers', String(translateWorkers))
      formData.append('download_history_max_count', String(downloadHistoryMaxCount))
      formData.append('download_history_max_age_days', String(downloadHistoryMaxAgeDays))
      if (translationPrompt) formData.append('translation_prompt', translationPrompt)
      if (noAuth) formData.append('no_auth', 'on')
      if (fixedToken) formData.append('fixed_token', fixedToken)
      if (deepgramKey) formData.append('deepgram_api_key', deepgramKey)
      formData.append('default_asr_provider', defaultAsrProvider)
      formData.append('default_asr_profile_id', defaultAsrProfileId)
      formData.append('default_whisper_model', defaultWhisperModel)
      formData.append('default_llm_profile_id', defaultLlmProfileId)
      formData.append('default_merge_profile_id', defaultMergeProfileId)
      formData.append('default_scene', defaultScene)
      formData.append('default_asr_chunk_seconds', String(defaultChunkSeconds))

      await api.postForm('/settings', formData)
      setSuccessMsg('设置已成功保存！')
      loadSettings()
    } catch (err: any) {
      setErrorMsg(err.message || '保存设置时发生异常')
    } finally {
      setSaving(false)
    }
  }

  const handleSaveCover = async () => {
    setSavingCover(true)
    setErrorMsg(null)
    setSuccessMsg(null)
    try {
      if (coverMode === 'upload' && coverFile) {
        const formData = new FormData()
        formData.append('file', coverFile)
        formData.append('mode', 'upload')
        await api.postForm('/api/settings/default-cover', formData)
      } else {
        await api.post('/api/settings/default-cover', {
          mode: coverMode,
          preset: coverPreset,
          url: coverUrl.trim(),
        })
      }
      setCoverNonce(Date.now())
      setCoverFile(null)
      setCoverFilePreview(null)
      setSuccessMsg('默认封面设置已成功更新！')
      loadSettings()
    } catch (err: any) {
      setErrorMsg(err.message || '保存封面配置失败')
    } finally {
      setSavingCover(false)
    }
  }

  const handleSaveDefaultModels = async () => {
    setSavingModels(true)
    setErrorMsg(null)
    setSuccessMsg(null)
    try {
      const formData = new FormData()
      formData.append('default_asr_provider', defaultAsrProvider)
      formData.append('default_asr_profile_id', defaultAsrProfileId)
      formData.append('default_whisper_model', defaultWhisperModel)
      formData.append('default_llm_profile_id', defaultLlmProfileId)
      formData.append('default_merge_profile_id', defaultMergeProfileId)
      formData.append('default_scene', defaultScene)
      formData.append('default_asr_chunk_seconds', String(defaultChunkSeconds))
      await api.postForm('/settings', formData)
      setSuccessMsg('默认模型配置已成功保存！')
      loadSettings()
    } catch (err: any) {
      setErrorMsg(err.message || '保存默认模型配置失败')
    } finally {
      setSavingModels(false)
    }
  }

  const handleResetDefaultModels = () => {
    setDefaultAsrProvider('local')
    setDefaultWhisperModel('large-v3')
    setDefaultScene('asmr')
    setDefaultChunkSeconds(60)
    if (availableAsrProfiles.length > 0) setDefaultAsrProfileId(availableAsrProfiles[0].profile_id)
    if (availableLlmProfiles.length > 0) setDefaultLlmProfileId(availableLlmProfiles[0].profile_id)
  }

  const handleResetCover = async () => {
    if (!window.confirm('确定要恢复系统默认预设封面吗？')) return
    setSavingCover(true)
    setErrorMsg(null)
    setSuccessMsg(null)
    try {
      await api.post('/api/settings/default-cover/reset')
      setCoverMode('preset')
      setCoverPreset('default')
      setCoverUrl('')
      setCoverFile(null)
      setCoverFilePreview(null)
      setCoverNonce(Date.now())
      setSuccessMsg('已恢复系统默认封面')
      loadSettings()
    } catch (err: any) {
      setErrorMsg(err.message || '恢复默认封面失败')
    } finally {
      setSavingCover(false)
    }
  }

  const handleDeleteDeepgramKey = async () => {
    if (!window.confirm('确定要清除已保存的 Deepgram API Key 吗？')) return
    try {
      await api.post('/settings/deepgram/delete-key')
      setDeepgramKey('')
      setSuccessMsg('Deepgram API Key 已成功清除')
      loadSettings()
    } catch (err: any) {
      alert('清除失败: ' + err.message)
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-dim)' }}>
        <p>正在载入系统设置…</p>
      </div>
    )
  }

  return (
    <div className="settings-page-container">
      <div className="page-header">
        <div className="page-title-wrap">
          <h1 className="page-title">系统设置</h1>
          <span className="page-subtitle">
            配置本地媒体库路径、网络代理、ASR 并发性能与全局翻译 Prompt 规则
          </span>
        </div>
      </div>

      {successMsg && (
        <div style={{ padding: '10px 16px', background: 'rgba(63, 185, 80, 0.15)', color: 'var(--color-green)', borderRadius: 'var(--radius-sm)', marginBottom: 20, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Check size={16} />
          {successMsg}
        </div>
      )}

      {errorMsg && (
        <div style={{ padding: '10px 16px', background: 'rgba(239, 68, 68, 0.15)', color: 'var(--color-red)', borderRadius: 'var(--radius-sm)', marginBottom: 20 }}>
          {errorMsg}
        </div>
      )}

      {/* Settings Sub-Tabs Header */}
      <div className="settings-tabs">
        <button
          type="button"
          className={`settings-tab-btn ${activeTab === 'general' ? 'active' : ''}`}
          onClick={() => setActiveTab('general')}
        >
          <FolderKanban size={15} />
          媒体库与目录
        </button>
        <button
          type="button"
          className={`settings-tab-btn ${activeTab === 'models' ? 'active' : ''}`}
          onClick={() => setActiveTab('models')}
        >
          <Sparkles size={15} />
          默认模型
        </button>
        <button
          type="button"
          className={`settings-tab-btn ${activeTab === 'cover' ? 'active' : ''}`}
          onClick={() => setActiveTab('cover')}
        >
          <ImageIcon size={15} />
          默认封面
        </button>
        <button
          type="button"
          className={`settings-tab-btn ${activeTab === 'appearance' ? 'active' : ''}`}
          onClick={() => setActiveTab('appearance')}
        >
          <Type size={15} />
          界面与字体排版
        </button>
        <button
          type="button"
          className={`settings-tab-btn ${activeTab === 'pipeline' ? 'active' : ''}`}
          onClick={() => setActiveTab('pipeline')}
        >
          <Cpu size={15} />
          并发与性能
        </button>
        <button
          type="button"
          className={`settings-tab-btn ${activeTab === 'proxy' ? 'active' : ''}`}
          onClick={() => setActiveTab('proxy')}
        >
          <Globe size={15} />
          网络代理
        </button>
        <button
          type="button"
          className={`settings-tab-btn ${activeTab === 'prompt' ? 'active' : ''}`}
          onClick={() => setActiveTab('prompt')}
        >
          <FileEdit size={15} />
          翻译 Prompt
        </button>
        <button
          type="button"
          className={`settings-tab-btn ${activeTab === 'security' ? 'active' : ''}`}
          onClick={() => setActiveTab('security')}
        >
          <ShieldCheck size={15} />
          密钥与安全
        </button>
      </div>

      <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        {/* 1. Library Root */}
        {activeTab === 'general' && (
        <div className="card-panel">
          <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>本地媒体库目录</h3>
          <p style={{ fontSize: 13, color: 'var(--fg-dim)', marginBottom: 12 }}>
            SubForge 存储音频、作品封面以及生成的中日双语字幕的基础文件夹。
          </p>
          <div style={{ display: 'flex', gap: 10 }}>
            <input
              type="text"
              className="input-field"
              value={libraryRoot}
              onChange={(e) => setLibraryRoot(e.target.value)}
              placeholder="选择本地音声库绝对路径"
              style={{ flex: 1 }}
            />
            <button type="button" className="btn" onClick={handleSelectFolder}>
              <Folder size={15} />
              选择文件夹
            </button>
          </div>
        </div>
        )}

        {/* Default Models & Processing Pipeline */}
        {activeTab === 'models' && (
          <div className="card-panel" style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Sparkles size={18} style={{ color: 'var(--accent-base)' }} />
                  <h3 style={{ fontSize: 16, fontWeight: 700 }}>默认模型配置 (Default Processing Models)</h3>
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  onClick={handleResetDefaultModels}
                  title="恢复默认配置"
                >
                  <RotateCcw size={13} />
                  重置
                </button>
              </div>
              <p style={{ fontSize: 13, color: 'var(--fg-dim)' }}>
                配置全局默认使用的 ASR 语音识别与 LLM 双语翻译模型。发起单轨转写或批量处理时将自动预选此处的默认值，你仍可在每次处理时手动自由切换。
              </p>
            </div>

            {/* 1. Default ASR Engine */}
            <div className="card-inset" style={{ padding: '16px 18px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                <Cpu size={16} style={{ color: 'var(--accent-base)' }} />
                <h4 style={{ fontSize: 14, fontWeight: 600 }}>默认 ASR 语音转写引擎</h4>
              </div>

              {/* Provider Selection */}
              <div style={{ marginBottom: 16 }}>
                <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 8 }}>
                  引擎架构类型
                </label>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  {[
                    { key: 'local', label: '本地 Faster-Whisper', desc: '离线 GPU / CPU 推理' },
                    { key: 'model', label: '自定义 / API 音频模型', desc: '如 raspb (Gemini 3.8 Flash) / OpenAI Compatible' },
                    { key: 'deepgram', label: 'Deepgram Nova-3', desc: '极速云端语音转写' },
                  ].map((p) => (
                    <button
                      key={p.key}
                      type="button"
                      className={`option-card-btn ${defaultAsrProvider === p.key ? 'active' : ''}`}
                      onClick={() => setDefaultAsrProvider(p.key as any)}
                    >
                      <span style={{ fontWeight: 600 }}>{p.label}</span>
                      <span style={{ fontSize: 10.5, opacity: defaultAsrProvider === p.key ? 0.9 : 0.75 }}>{p.desc}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Local Whisper Model Options */}
              {defaultAsrProvider === 'local' && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 12 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                      Whisper 模型规格
                    </label>
                    <select
                      className="select-field"
                      style={{ width: '100%' }}
                      value={defaultWhisperModel}
                      onChange={(e) => setDefaultWhisperModel(e.target.value)}
                    >
                      <option value="large-v3">large-v3 (最高准确率，推荐 GPU 运行)</option>
                      <option value="medium">medium (均衡型，适合显存较小设备)</option>
                      <option value="base">base (轻量快速，仅基础转写)</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                      场景识别优化
                    </label>
                    <select
                      className="select-field"
                      style={{ width: '100%' }}
                      value={defaultScene}
                      onChange={(e) => setDefaultScene(e.target.value as any)}
                    >
                      <option value="asmr">ASMR 悄悄话强化（降低静音截断，保留呼吸声）</option>
                      <option value="normal">标准人声对话（普通播客/影视人声）</option>
                    </select>
                  </div>
                </div>
              )}

              {/* Model Profile Options */}
              {defaultAsrProvider === 'model' && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 12 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                      默认 API 语音识别模型
                    </label>
                    <select
                      className="select-field"
                      style={{ width: '100%' }}
                      value={defaultAsrProfileId}
                      onChange={(e) => setDefaultAsrProfileId(e.target.value)}
                    >
                      {availableAsrProfiles.length === 0 && <option value="">暂无支持语音转写的配置</option>}
                      {availableAsrProfiles.map((p) => (
                        <option key={p.profile_id} value={p.profile_id}>
                          {p.name} ({p.model})
                        </option>
                      ))}
                    </select>
                    <span style={{ fontSize: 11, color: 'var(--fg-faint)', marginTop: 4, display: 'block' }}>
                      可在「翻译配置」页面添加更多具备语音转写能力 (transcribe) 的模型。
                    </span>
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                      音频分片上限 (秒)
                    </label>
                    <input
                      type="number"
                      min={10}
                      max={600}
                      className="input-field"
                      value={defaultChunkSeconds}
                      onChange={(e) => setDefaultChunkSeconds(parseInt(e.target.value) || 60)}
                    />
                  </div>
                </div>
              )}

              {defaultAsrProvider === 'deepgram' && (
                <div style={{ marginTop: 12 }}>
                  <p style={{ fontSize: 12, color: 'var(--fg-dim)' }}>
                    使用 Deepgram Nova-3 云端 API 进行极速语音识别。请确保已在「密钥与安全」选项卡中配置了 Deepgram API Key。
                  </p>
                </div>
              )}
            </div>

            {/* 2. Default LLM Translation Engine */}
            <div className="card-inset" style={{ padding: '16px 18px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                <Globe size={16} style={{ color: 'var(--accent-base)' }} />
                <h4 style={{ fontSize: 14, fontWeight: 600 }}>默认 LLM 双语翻译模型</h4>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                  默认翻译模型配置
                </label>
                <select
                  className="select-field"
                  style={{ width: '100%', maxWidth: 480 }}
                  value={defaultLlmProfileId}
                  onChange={(e) => setDefaultLlmProfileId(e.target.value)}
                >
                  {availableLlmProfiles.length === 0 && <option value="">暂无支持翻译的模型配置</option>}
                  {availableLlmProfiles.map((p) => (
                    <option key={p.profile_id} value={p.profile_id}>
                      {p.name} ({p.model})
                    </option>
                  ))}
                </select>
                <span style={{ fontSize: 11, color: 'var(--fg-faint)', marginTop: 4, display: 'block' }}>
                  生成双语台本时默认选用此模型。如需新增或修改模型参数（如 Base URL、思考等级等），请前往「翻译配置」页面。
                </span>
              </div>
            </div>

            {/* Save Button */}
            <div>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleSaveDefaultModels}
                disabled={savingModels}
              >
                <Check size={15} />
                {savingModels ? '正在保存…' : '保存默认模型配置'}
              </button>
            </div>
          </div>
        )}

        {/* 2. Default Cover Configuration */}
        {activeTab === 'cover' && (
        <div className="card-panel" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <ImageIcon size={18} style={{ color: 'var(--accent-base)' }} />
                <h3 style={{ fontSize: 16, fontWeight: 700 }}>默认封面配置 (Default Cover)</h3>
              </div>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={handleResetCover}
                disabled={savingCover}
                title="恢复系统初始预设封面"
              >
                <RotateCcw size={13} />
                恢复默认
              </button>
            </div>
            <p style={{ fontSize: 13, color: 'var(--fg-dim)' }}>
              当音声作品无内嵌封面图片或加载失败时，作品卡片、播放器底栏及详情页将统一使用此默认封面。
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', gap: 24, alignItems: 'start' }}>
            {/* Left Preview */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center' }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--fg-dim)' }}>当前生效效果预览</span>
              <div
                style={{
                  width: 200,
                  height: 200,
                  borderRadius: 'var(--radius-lg)',
                  overflow: 'hidden',
                  border: '2px solid var(--border-strong)',
                  background: '#090d14',
                  boxShadow: 'var(--shadow-md)',
                  position: 'relative',
                }}
              >
                <img
                  src={coverFilePreview || (coverMode === 'url' && coverUrl ? coverUrl : `/covers/default?v=${coverNonce}`)}
                  alt="默认封面预览"
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  onError={(e) => {
                    (e.target as HTMLImageElement).src = '/covers/default'
                  }}
                />
                <div
                  style={{
                    position: 'absolute',
                    bottom: 8,
                    right: 8,
                    background: 'rgba(0,0,0,0.7)',
                    padding: '2px 8px',
                    borderRadius: 4,
                    fontSize: 10,
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--accent-base)',
                    border: '1px solid var(--border-subtle)',
                  }}
                >
                  1:1 ASMR
                </div>
              </div>
              <span style={{ fontSize: 11, color: 'var(--fg-faint)', textAlign: 'center' }}>
                {settings?.default_cover?.has_custom_file
                  ? '当前生效: 本地自定义图片'
                  : settings?.default_cover?.mode === 'url'
                  ? '当前生效: 网络图片 URL'
                  : `当前生效: 预设风格 (${settings?.default_cover?.preset || 'default'})`}
              </span>
            </div>

            {/* Right Controls */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div>
                <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 8 }}>
                  封面提供方式
                </label>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  {[
                    { key: 'preset', label: '内置艺术预设', icon: <Sparkles size={14} /> },
                    { key: 'upload', label: '上传本地图片', icon: <UploadCloud size={14} /> },
                    { key: 'url', label: '网络图片地址', icon: <Globe size={14} /> },
                  ].map((modeOpt) => (
                    <button
                      key={modeOpt.key}
                      type="button"
                      className={`btn btn-sm ${coverMode === modeOpt.key ? 'btn-primary' : 'btn-ghost'}`}
                      onClick={() => {
                        setCoverMode(modeOpt.key as any)
                        if (modeOpt.key !== 'upload') {
                          setCoverFile(null)
                          setCoverFilePreview(null)
                        }
                      }}
                    >
                      {modeOpt.icon}
                      {modeOpt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Preset View */}
              {coverMode === 'preset' && (
                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 8 }}>
                    预设艺术风格
                  </label>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
                    {[
                      { id: 'default', name: 'SubForge 原生', desc: '科技蓝 · 极简耳机与音频波纹', color: '#38bdf8' },
                      { id: 'headphones', name: '深邃耳机', desc: '魅影紫 · 专业监听与人声音频', color: '#a855f7' },
                      { id: 'wave', name: '声学波形', desc: '极光青 · 纯净双耳立体声频段', color: '#06b6d4' },
                      { id: 'studio', name: '录音工作室', desc: '琥珀金 · 经典专业电容麦克风', color: '#f59e0b' },
                    ].map((presetItem) => (
                      <div
                        key={presetItem.id}
                        onClick={() => setCoverPreset(presetItem.id as any)}
                        style={{
                          padding: '12px 14px',
                          borderRadius: 'var(--radius-md)',
                          border: coverPreset === presetItem.id ? `2px solid ${presetItem.color}` : '1px solid var(--border-subtle)',
                          background: coverPreset === presetItem.id ? 'rgba(255, 255, 255, 0.06)' : 'rgba(255, 255, 255, 0.02)',
                          cursor: 'pointer',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: 4,
                          transition: 'all 0.15s ease',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg-main)' }}>{presetItem.name}</span>
                          <span
                            style={{
                              width: 10,
                              height: 10,
                              borderRadius: '50%',
                              background: presetItem.color,
                              display: 'inline-block',
                            }}
                          />
                        </div>
                        <span style={{ fontSize: 11, color: 'var(--fg-dim)' }}>{presetItem.desc}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Upload Local File View */}
              {coverMode === 'upload' && (
                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 8 }}>
                    上传本地封面图片 (支持 JPG / PNG / WebP)
                  </label>
                  <div
                    style={{
                      border: '2px dashed var(--border-strong)',
                      borderRadius: 'var(--radius-md)',
                      padding: '24px 20px',
                      textAlign: 'center',
                      cursor: 'pointer',
                      background: 'rgba(255, 255, 255, 0.02)',
                      transition: 'border-color 0.15s',
                    }}
                    onClick={() => document.getElementById('default-cover-file-input')?.click()}
                  >
                    <UploadCloud size={32} style={{ color: 'var(--accent-base)', marginBottom: 8, margin: '0 auto' }} />
                    <p style={{ fontSize: 13, color: 'var(--fg-main)', fontWeight: 500 }}>
                      {coverFile ? coverFile.name : '点击或拖拽本地图片文件到此处'}
                    </p>
                    <span style={{ fontSize: 11, color: 'var(--fg-faint)', marginTop: 4, display: 'block' }}>
                      建议尺寸 500x500 或 1:1 正方形图片，最高支持 20MB
                    </span>
                    <input
                      id="default-cover-file-input"
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      style={{ display: 'none' }}
                      onChange={(e) => {
                        const file = e.target.files?.[0]
                        if (file) {
                          setCoverFile(file)
                          const url = URL.createObjectURL(file)
                          setCoverFilePreview(url)
                        }
                      }}
                    />
                  </div>
                </div>
              )}

              {/* URL View */}
              {coverMode === 'url' && (
                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 8 }}>
                    网络图片 URL 地址
                  </label>
                  <input
                    type="url"
                    className="input-field"
                    value={coverUrl}
                    onChange={(e) => setCoverUrl(e.target.value)}
                    placeholder="https://example.com/cover.jpg"
                  />
                  <small style={{ color: 'var(--fg-faint)', marginTop: 4, display: 'block' }}>
                    请填入直接返回图片资源的 HTTPS 链接（如图床或 CDN 链接）
                  </small>
                </div>
              )}

              <div style={{ marginTop: 8 }}>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleSaveCover}
                  disabled={savingCover || (coverMode === 'upload' && !coverFile && !settings?.default_cover?.has_custom_file) || (coverMode === 'url' && !coverUrl.trim())}
                >
                  <Check size={15} />
                  {savingCover ? '正在应用…' : '应用并保存封面设置'}
                </button>
              </div>
            </div>
          </div>
        </div>
        )}
        {/* 2. Network Proxy */}
        {activeTab === 'proxy' && (
        <div className="card-panel">
          <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>网络代理设置</h3>
          <p style={{ fontSize: 13, color: 'var(--fg-dim)', marginBottom: 12 }}>
            若使用云端 API（Deepgram, Gemini, OpenAI）或从 Bilibili/YouTube 抓取音频，可在此配置本地 HTTP 代理。
          </p>
          <input
            type="text"
            className="input-field"
            value={proxyUrl}
            onChange={(e) => setProxyUrl(e.target.value)}
            placeholder="例如: http://127.0.0.1:7890"
          />
        </div>
        )}

        {/* 3. Concurrency Limits */}
        {activeTab === 'pipeline' && (
        <div className="card-panel">
          <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>并发控制</h3>
          <p style={{ fontSize: 12, color: 'var(--fg-dim)', marginBottom: 16 }}>
            「作品数」决定同时有几个作品在转写，其余按入队顺序排队；「请求数」是所有作品共享的 API 调用上限。保存后立即生效。
          </p>
          {([
            {
              group: '本地转写（Whisper）',
              fields: [{
                label: '同时加载模型数',
                hint: '每个模型占一份显存/内存，也就是同时做本地转写的作品数。显存不足时保持 1。',
                value: asrConcurrency, set: setAsrConcurrency, max: 8,
              }],
            },
            {
              group: '网络转写（Deepgram / 音频模型）',
              fields: [
                {
                  label: '同时转写作品数',
                  hint: '同时进入网络转写的作品（含片段重处理）。设为 1 时一个作品独占全部请求，先到先完成。',
                  value: remoteAsrTaskConcurrency, set: setRemoteAsrTaskConcurrency, max: 64,
                },
                {
                  label: '同时请求数',
                  hint: '所有作品共享，同时发往转写服务的请求上限。频繁遇到 429 限流时调低。',
                  value: remoteAsrConcurrency, set: setRemoteAsrConcurrency, max: 64,
                },
              ],
            },
            {
              group: '翻译（LLM）',
              fields: [{
                label: '同时请求数',
                hint: '所有作品共享，同时发往翻译模型的请求上限。频繁遇到 429 限流时调低。',
                value: translateWorkers, set: setTranslateWorkers, max: 64,
              }],
            },
          ] as const).map((section) => (
            <div key={section.group} style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>{section.group}</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
                {section.fields.map((field) => (
                  <div key={field.label}>
                    <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                      {field.label}
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={field.max}
                      className="input-field"
                      value={field.value}
                      onChange={(e) => field.set(Math.max(1, parseInt(e.target.value) || 1))}
                    />
                    <div style={{ fontSize: 11, color: 'var(--fg-dim)', marginTop: 6, lineHeight: 1.5 }}>
                      {field.hint}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        )}

        {/* 4. Download History Retention */}
        {activeTab === 'pipeline' && (
        <div className="card-panel">
          <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>下载任务历史</h3>
          <p style={{ fontSize: 12, color: 'var(--fg-dim)', marginBottom: 16 }}>
            下载/导入任务记录保存在媒体库数据库中，超出以下任一限制的记录会自动清理（进行中的任务不受影响）。保存后立即生效。
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
            {[
              { label: '最多保留条数', hint: '只保留最近的 N 条记录。', value: downloadHistoryMaxCount, set: setDownloadHistoryMaxCount, max: 10000 },
              { label: '最长保留天数', hint: '超过 N 天的记录会被清理。', value: downloadHistoryMaxAgeDays, set: setDownloadHistoryMaxAgeDays, max: 3650 },
            ].map((field) => (
              <div key={field.label}>
                <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                  {field.label}
                </label>
                <input
                  type="number"
                  min={1}
                  max={field.max}
                  className="input-field"
                  value={field.value}
                  onChange={(e) => field.set(Math.max(1, parseInt(e.target.value) || 1))}
                />
                <div style={{ fontSize: 11, color: 'var(--fg-dim)', marginTop: 6, lineHeight: 1.5 }}>
                  {field.hint}
                </div>
              </div>
            ))}
          </div>
        </div>
        )}

        {/* 界面边角风格设置 (Corner Style Settings: Rounded vs Sharp) */}
        {activeTab === 'appearance' && (
        <div className="card-panel" style={{ marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Square size={18} style={{ color: 'var(--accent-base)' }} />
              <h3 style={{ fontSize: 15, fontWeight: 700 }}>界面边角风格设置（圆角 / 直角）</h3>
            </div>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={resetCornerSettings}
              title="恢复默认圆角"
            >
              <RotateCcw size={13} />
              恢复默认圆角
            </button>
          </div>

          <p style={{ fontSize: 13, color: 'var(--fg-dim)', marginBottom: 16 }}>
            自定义全局或各个界面的边角风格。支持快速在现代柔和圆角与硬朗极简直角之间切换，并可针对卡片、按钮、作品库、设置与侧边栏进行细粒度控制。
          </p>

          {/* Master Switch */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '14px 18px',
              background: 'rgba(255, 255, 255, 0.03)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              marginBottom: 16,
              flexWrap: 'wrap',
              gap: 12,
            }}
          >
            <div>
              <div style={{ fontWeight: 600, fontSize: 14 }}>全局风格快速切换</div>
              <div style={{ fontSize: 12, color: 'var(--fg-dim)', marginTop: 2 }}>
                一键应用至所有卡片、按钮、作品库、设置及侧边栏组件
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                type="button"
                className={`btn btn-sm ${cornerSettings.global === 'rounded' ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setAllCorners('rounded')}
              >
                ● 柔和圆角 (默认)
              </button>
              <button
                type="button"
                className={`btn btn-sm ${cornerSettings.global === 'sharp' ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setAllCorners('sharp')}
              >
                ■ 硬朗直角
              </button>
            </div>
          </div>

          {/* Granular Module Switches Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginBottom: 20 }}>
            {/* 1. 卡片与面板 */}
            <div
              style={{
                padding: '12px 14px',
                background: 'var(--bg-card-inset)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>卡片与面板</span>
                <span style={{ fontSize: 11, color: 'var(--fg-faint)' }}>Cards</span>
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--fg-dim)', minHeight: 32 }}>
                控制任务中心表格容器、统计卡片、弹窗与内容面板边角
              </div>
              <div style={{ display: 'flex', gap: 4, marginTop: 'auto' }}>
                <button
                  type="button"
                  style={{ flex: 1 }}
                  className={`btn btn-sm ${cornerSettings.cards === 'rounded' ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => updateCornerSettings({ cards: 'rounded' })}
                >
                  圆角
                </button>
                <button
                  type="button"
                  style={{ flex: 1 }}
                  className={`btn btn-sm ${cornerSettings.cards === 'sharp' ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => updateCornerSettings({ cards: 'sharp' })}
                >
                  直角
                </button>
              </div>
            </div>

            {/* 2. 按钮控件 */}
            <div
              style={{
                padding: '12px 14px',
                background: 'var(--bg-card-inset)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>按钮组件</span>
                <span style={{ fontSize: 11, color: 'var(--fg-faint)' }}>Buttons</span>
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--fg-dim)', minHeight: 32 }}>
                控制主按钮、操作小按钮、图标操作钮与各种交互按钮边角
              </div>
              <div style={{ display: 'flex', gap: 4, marginTop: 'auto' }}>
                <button
                  type="button"
                  style={{ flex: 1 }}
                  className={`btn btn-sm ${cornerSettings.buttons === 'rounded' ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => updateCornerSettings({ buttons: 'rounded' })}
                >
                  圆角
                </button>
                <button
                  type="button"
                  style={{ flex: 1 }}
                  className={`btn btn-sm ${cornerSettings.buttons === 'sharp' ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => updateCornerSettings({ buttons: 'sharp' })}
                >
                  直角
                </button>
              </div>
            </div>

            {/* 3. 作品库 */}
            <div
              style={{
                padding: '12px 14px',
                background: 'var(--bg-card-inset)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>作品库</span>
                <span style={{ fontSize: 11, color: 'var(--fg-faint)' }}>Library</span>
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--fg-dim)', minHeight: 32 }}>
                控制作品卡片、作品封面、标签徽章、RJ 号标识与列表表格
              </div>
              <div style={{ display: 'flex', gap: 4, marginTop: 'auto' }}>
                <button
                  type="button"
                  style={{ flex: 1 }}
                  className={`btn btn-sm ${cornerSettings.library === 'rounded' ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => updateCornerSettings({ library: 'rounded' })}
                >
                  圆角
                </button>
                <button
                  type="button"
                  style={{ flex: 1 }}
                  className={`btn btn-sm ${cornerSettings.library === 'sharp' ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => updateCornerSettings({ library: 'sharp' })}
                >
                  直角
                </button>
              </div>
            </div>

            {/* 4. 设置页面 */}
            <div
              style={{
                padding: '12px 14px',
                background: 'var(--bg-card-inset)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>系统设置</span>
                <span style={{ fontSize: 11, color: 'var(--fg-faint)' }}>Settings</span>
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--fg-dim)', minHeight: 32 }}>
                控制设置选项卡标签、配置卡片、输入框、下拉选择器与按钮
              </div>
              <div style={{ display: 'flex', gap: 4, marginTop: 'auto' }}>
                <button
                  type="button"
                  style={{ flex: 1 }}
                  className={`btn btn-sm ${cornerSettings.settings === 'rounded' ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => updateCornerSettings({ settings: 'rounded' })}
                >
                  圆角
                </button>
                <button
                  type="button"
                  style={{ flex: 1 }}
                  className={`btn btn-sm ${cornerSettings.settings === 'sharp' ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => updateCornerSettings({ settings: 'sharp' })}
                >
                  直角
                </button>
              </div>
            </div>

            {/* 5. 侧边栏 */}
            <div
              style={{
                padding: '12px 14px',
                background: 'var(--bg-card-inset)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>侧边栏</span>
                <span style={{ fontSize: 11, color: 'var(--fg-faint)' }}>Sidebar</span>
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--fg-dim)', minHeight: 32 }}>
                控制侧边栏导航项背景、激活指示器、计数角标与主题开关
              </div>
              <div style={{ display: 'flex', gap: 4, marginTop: 'auto' }}>
                <button
                  type="button"
                  style={{ flex: 1 }}
                  className={`btn btn-sm ${cornerSettings.sidebar === 'rounded' ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => updateCornerSettings({ sidebar: 'rounded' })}
                >
                  圆角
                </button>
                <button
                  type="button"
                  style={{ flex: 1 }}
                  className={`btn btn-sm ${cornerSettings.sidebar === 'sharp' ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => updateCornerSettings({ sidebar: 'sharp' })}
                >
                  直角
                </button>
              </div>
            </div>
          </div>

          {/* Live Interactive Preview */}
          <div
            style={{
              padding: '14px 16px',
              background: 'var(--bg-card-inset)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            <div style={{ fontSize: 12, color: 'var(--fg-dim)', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>实时效果即时反馈预览</span>
              <span style={{ fontSize: 11, color: 'var(--fg-faint)' }}>（修改上方设置立即全局生效，无需刷新页面）</span>
            </div>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              <div
                className="card-panel"
                style={{
                  padding: '8px 14px',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  fontSize: 12,
                  background: 'rgba(255, 255, 255, 0.05)',
                }}
              >
                <span>卡片与面板示例</span>
                <span className="task-status-badge task-status-completed" style={{ fontSize: 10, padding: '1px 5px', borderRadius: 'var(--radius-sm)' }}>
                  已完成
                </span>
              </div>
              <button type="button" className="btn btn-primary btn-sm">
                主按钮示例
              </button>
              <button type="button" className="btn btn-ghost btn-sm">
                次要按钮
              </button>
              <input
                type="text"
                className="input-field"
                style={{ width: 140, padding: '4px 8px', fontSize: 12 }}
                readOnly
                value="输入框示例"
              />
            </div>
          </div>
        </div>
        )}

        {/* 字体与排版设置 (Typography & Subtitle Display) */}
        {activeTab === 'appearance' && (
        <div className="card-panel">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Type size={18} style={{ color: 'var(--accent-base)' }} />
              <h3 style={{ fontSize: 15, fontWeight: 700 }}>界面与台本字体排版设置</h3>
            </div>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={resetFontSettings}
              title="恢复默认字体与字号"
            >
              <RotateCcw size={13} />
              恢复默认
            </button>
          </div>

          <p style={{ fontSize: 13, color: 'var(--fg-dim)', marginBottom: 16 }}>
            自定义 SubForge 全局界面基础字号、界面字体族、日文音声原句与中文双语台本的字体及排版行距。
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16, marginBottom: 16 }}>
            <div>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                全局界面字体
              </label>
              <select
                className="select-field"
                style={{ width: '100%' }}
                value={fontSettings.fontFamily}
                onChange={(e) => updateFontSettings({ fontFamily: e.target.value })}
              >
                <option value="system">系统默认 (System Default)</option>
                <option value="source_han">思源黑体 (Source Han Sans / Noto Sans)</option>
                <option value="yahei">微软雅黑 (Microsoft YaHei)</option>
                <option value="pingfang">苹方 (PingFang SC)</option>
                <option value="lxgw">霞鹜文楷 (LXGW WenKai)</option>
                <option value="yu_gothic">游黑体 (Yu Gothic · 日文推荐)</option>
                <option value="meiryo">Meiryo (メイリオ)</option>
                <option value="mincho">明朝体 / 宋体 (MS Mincho / SimSun)</option>
                <option value="serif">衬线体 (Source Han Serif / 宋体 / Georgia)</option>
                <option value="mono">等宽体 (JetBrains Mono / Consolas / 代码等宽)</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                自定义字体名 (留空使用上方选项)
              </label>
              <input
                type="text"
                className="input-field"
                value={fontSettings.customFont}
                onChange={(e) => updateFontSettings({ customFont: e.target.value })}
                placeholder="例如: HarmonyOS Sans, 鸿蒙黑体"
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                日文原声台本字体族
              </label>
              <select
                className="select-field"
                style={{ width: '100%' }}
                value={fontSettings.jaFont}
                onChange={(e) => updateFontSettings({ jaFont: e.target.value })}
              >
                <option value="system">跟随界面字体</option>
                <option value="yu_gothic">游黑体 (Yu Gothic)</option>
                <option value="meiryo">Meiryo (メイリオ)</option>
                <option value="source_han">思源黑体 (Noto Sans JP)</option>
                <option value="mincho">明朝体 (MS Mincho)</option>
                <option value="serif">衬线体 (Yu Mincho / 游明朝体)</option>
                <option value="mono">等宽体 (Monospace / 代码等宽)</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                中文译文字体族
              </label>
              <select
                className="select-field"
                style={{ width: '100%' }}
                value={fontSettings.zhFont}
                onChange={(e) => updateFontSettings({ zhFont: e.target.value })}
              >
                <option value="system">跟随界面字体</option>
                <option value="source_han">思源黑体 (Source Han Sans)</option>
                <option value="yahei">微软雅黑 (Microsoft YaHei)</option>
                <option value="pingfang">苹方 (PingFang SC)</option>
                <option value="lxgw">霞鹜文楷 (LXGW WenKai)</option>
                <option value="serif">衬线体 (思源宋体 / SimSun / 宋体)</option>
                <option value="mono">等宽体 (JetBrains Mono / 等宽字体)</option>
              </select>
            </div>
          </div>

          {/* Sliders */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, marginBottom: 16 }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                <span>全局界面字号</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{fontSettings.uiFontSize || 14}px</span>
              </div>
              <input
                type="range"
                min={12}
                max={18}
                step={0.5}
                className="input-field"
                style={{ padding: 0 }}
                value={fontSettings.uiFontSize || 14}
                onChange={(e) => updateFontSettings({ uiFontSize: parseFloat(e.target.value) })}
              />
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                <span>中文字幕字号</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{fontSettings.subtitleFontSize}px</span>
              </div>
              <input
                type="range"
                min={13}
                max={24}
                step={0.5}
                className="input-field"
                style={{ padding: 0 }}
                value={fontSettings.subtitleFontSize}
                onChange={(e) => updateFontSettings({ subtitleFontSize: parseFloat(e.target.value) })}
              />
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                <span>日文字幕字号</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{fontSettings.subtitleJaFontSize}px</span>
              </div>
              <input
                type="range"
                min={11}
                max={20}
                step={0.5}
                className="input-field"
                style={{ padding: 0 }}
                value={fontSettings.subtitleJaFontSize}
                onChange={(e) => updateFontSettings({ subtitleJaFontSize: parseFloat(e.target.value) })}
              />
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                <span>台本行间距</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{fontSettings.subtitleLineHeight}</span>
              </div>
              <input
                type="range"
                min={1.3}
                max={2.0}
                step={0.05}
                className="input-field"
                style={{ padding: 0 }}
                value={fontSettings.subtitleLineHeight}
                onChange={(e) => updateFontSettings({ subtitleLineHeight: parseFloat(e.target.value) })}
              />
            </div>
          </div>

          {/* Live Preview Box */}
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
              实时渲染效果预览
            </label>
            <div
              style={{
                padding: '16px 20px',
                background: 'var(--bg-card-inset)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                display: 'flex',
                flexDirection: 'column',
                gap: 4,
              }}
            >
              <div className="script-source-text">
                「……ふふ、今日もお疲れ様。ゆっくり休んでね」
              </div>
              <div className="script-target-text">
                “……呵呵，今天也辛苦啦。好好休息一下吧”
              </div>
            </div>
          </div>
        </div>
        )}

        {/* 4. Global Translation Prompt */}
        {activeTab === 'prompt' && (
        <div className="card-panel">
          <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>全局翻译 Prompt 提示词</h3>
          <p style={{ fontSize: 13, color: 'var(--fg-dim)', marginBottom: 12 }}>
            定义针对同人音声、ASMR 助眠剧情的翻译风格与专有名词约定。
          </p>
          <textarea
            className="input-field"
            rows={8}
            value={translationPrompt}
            onChange={(e) => setTranslationPrompt(e.target.value)}
            placeholder="例如: 你是一位专业的同人音声翻译家。请将输入的日语音频台本翻译成流畅地道的中文，保留拟声词韵味与角色称谓习惯…"
            style={{ resize: 'vertical' }}
          />
        </div>
        )}

        {/* 5. Security & Tokens */}
        {activeTab === 'security' && (
        <div className="card-panel">
          <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>访问安全与密钥</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                固定访问 Token（局域网共享保护）
              </label>
              <input
                type="password"
                className="input-field"
                value={fixedToken}
                onChange={(e) => setFixedToken(e.target.value)}
                placeholder="留空保留当前 Token"
              />
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <label style={{ fontSize: 12, color: 'var(--fg-dim)' }}>
                  Deepgram API Key (外部云端转写)
                </label>
                {settings?.has_deepgram_key && (
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost btn-danger"
                    onClick={handleDeleteDeepgramKey}
                    style={{ padding: '2px 8px' }}
                  >
                    <Trash2 size={12} />
                    清除已存密钥
                  </button>
                )}
              </div>
              <input
                type="password"
                className="input-field"
                value={deepgramKey}
                onChange={(e) => setDeepgramKey(e.target.value)}
                placeholder={settings?.has_deepgram_key ? '已配置 (输入新 Key 覆盖)' : 'sk-...'}
              />
            </div>

            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, marginTop: 4 }}>
              <input
                type="checkbox"
                checked={noAuth}
                onChange={(e) => setNoAuth(e.target.checked)}
              />
              局域网无鉴权访问模式 (开启后同局域网设备无需输入密码即可在线听)
            </label>
          </div>
        </div>
        )}

        {/* Save Button */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 10 }}>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            <Save size={16} />
            {saving ? '正在保存…' : '保存系统设置'}
          </button>
        </div>
      </form>
    </div>
  )
}
