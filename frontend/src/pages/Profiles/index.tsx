import React, { useEffect, useState } from 'react'
import { Cpu, Plus, Sparkles, CheckCircle2, AlertCircle, Trash2, Key, HardDrive } from 'lucide-react'
import { api } from '../../api/client'

export function ProfilesPage() {
  const [currentTab, setCurrentTab] = useState<'asr' | 'llm'>('asr')
  const [asrProfiles, setAsrProfiles] = useState<any[]>([])
  const [llmProfiles, setLlmProfiles] = useState<any[]>([])
  const [cachedModels, setCachedModels] = useState<string[]>([])
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; msg: string; loading?: boolean }>>({})
  const [loading, setLoading] = useState(true)

  // Add Modal state
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [modalType, setModalType] = useState<'asr' | 'llm'>('asr')
  const [name, setName] = useState('')
  const [provider, setProvider] = useState('faster-whisper')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiBase, setApiBase] = useState('')
  const [device, setDevice] = useState('auto')
  const [computeType, setComputeType] = useState('auto')

  const fetchProfiles = async () => {
    setLoading(true)
    try {
      const data = await api.get<{
        asr_profiles: any[]
        llm_profiles: any[]
        cached_models: string[]
      }>('/api/profiles')
      setAsrProfiles(data.asr_profiles || [])
      setLlmProfiles(data.llm_profiles || [])
      setCachedModels(data.cached_models || [])
    } catch (err) {
      console.error('Failed to fetch profiles:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchProfiles()
  }, [])

  const handleTestAsr = async (profileId: string) => {
    setTestResults((prev) => ({ ...prev, [profileId]: { ok: false, msg: '测试中...', loading: true } }))
    try {
      const res = await api.post<{ ok: boolean; message: string }>(`/audio-models/${profileId}/test`)
      setTestResults((prev) => ({
        ...prev,
        [profileId]: { ok: res.ok, msg: res.message || (res.ok ? '连接成功' : '连接失败'), loading: false },
      }))
    } catch (err: any) {
      setTestResults((prev) => ({
        ...prev,
        [profileId]: { ok: false, msg: err.message || '测试失败', loading: false },
      }))
    }
  }

  const handleTestLlm = async (profileId: string) => {
    setTestResults((prev) => ({ ...prev, [profileId]: { ok: false, msg: '测试中...', loading: true } }))
    try {
      const res = await api.post<{ ok: boolean; message: string }>(`/profiles/${profileId}/test`)
      setTestResults((prev) => ({
        ...prev,
        [profileId]: { ok: res.ok, msg: res.message || (res.ok ? '连接成功' : '连接失败'), loading: false },
      }))
    } catch (err: any) {
      setTestResults((prev) => ({
        ...prev,
        [profileId]: { ok: false, msg: err.message || '测试失败', loading: false },
      }))
    }
  }

  const handleDeleteAsr = async (profileId: string) => {
    if (!confirm('确定要删除该语音识别配置吗？')) return
    try {
      await api.post(`/audio-models/${profileId}/delete`)
      fetchProfiles()
    } catch (err: any) {
      alert('删除失败: ' + err.message)
    }
  }

  const handleDeleteLlm = async (profileId: string) => {
    if (!confirm('确定要删除该翻译配置吗？')) return
    try {
      await api.post(`/profiles/${profileId}/delete`)
      fetchProfiles()
    } catch (err: any) {
      alert('删除失败: ' + err.message)
    }
  }

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      if (modalType === 'asr') {
        await api.post('/audio-models', {
          name: name.trim(),
          provider,
          model: model.trim(),
          api_key: apiKey.trim() || undefined,
          device,
          compute_type: computeType,
        })
      } else {
        await api.post('/profiles', {
          name: name.trim(),
          model: model.trim(),
          api_base: apiBase.trim() || undefined,
          api_key: apiKey.trim() || undefined,
        })
      }
      setAddModalOpen(false)
      setName('')
      setModel('')
      setApiKey('')
      setApiBase('')
      fetchProfiles()
    } catch (err: any) {
      alert('保存配置失败: ' + err.message)
    }
  }

  return (
    <div className="page-container space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">模型配置</h1>
          <p className="text-sm text-fg-dim mt-0.5">
            配置本地 Faster-Whisper、在线 Deepgram、Gemini 以及各类 OpenAI 兼容的大语言模型
          </p>
        </div>

        <button
          type="button"
          onClick={() => {
            setModalType(currentTab)
            setAddModalOpen(true)
          }}
          className="btn btn-primary flex items-center gap-1.5"
        >
          <Plus size={16} />
          {currentTab === 'asr' ? '添加语音模型' : '添加翻译模型'}
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-line gap-2">
        <button
          type="button"
          onClick={() => setCurrentTab('asr')}
          className={`tab-btn ${currentTab === 'asr' ? 'active' : ''}`}
        >
          <Cpu size={16} />
          语音识别模型 (ASR) ({asrProfiles.length})
        </button>
        <button
          type="button"
          onClick={() => setCurrentTab('llm')}
          className={`tab-btn ${currentTab === 'llm' ? 'active' : ''}`}
        >
          <Sparkles size={16} />
          翻译大模型 (LLM) ({llmProfiles.length})
        </button>
      </div>

      {/* Local Faster-Whisper Cache Status */}
      {currentTab === 'asr' && (
        <div className="p-3.5 bg-panel-2 rounded-xl border border-line flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <HardDrive size={16} className="text-accent" />
            <span className="font-semibold text-white">本地 Faster-Whisper 缓存状态:</span>
            <span className="text-fg-dim">
              {cachedModels.length > 0 ? cachedModels.join(', ') : '未检测到本地缓存模型'}
            </span>
          </div>
          <span className="text-fg-faint">首次运行未缓存模型时将自动下载</span>
        </div>
      )}

      {/* ASR List */}
      {currentTab === 'asr' && (
        <div className="grid gap-3">
          {asrProfiles.map((p) => {
            const result = testResults[p.profile_id]
            return (
              <div key={p.profile_id} className="p-4 bg-panel rounded-xl border border-line flex items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-white text-sm">{p.name}</span>
                    <span className="badge badge-accent uppercase text-xs">{p.provider || 'faster-whisper'}</span>
                    {p.model && <span className="text-xs text-fg-dim font-mono">{p.model}</span>}
                  </div>
                  <div className="text-xs text-fg-dim flex items-center gap-3">
                    {p.device && <span>设备: {p.device}</span>}
                    {p.compute_type && <span>计算类型: {p.compute_type}</span>}
                    {p.has_key && (
                      <span className="text-green-400 flex items-center gap-1">
                        <Key size={12} /> 已配置密钥
                      </span>
                    )}
                  </div>
                  {result && (
                    <div className={`text-xs mt-1 flex items-center gap-1 ${result.ok ? 'text-green-400' : 'text-red-400'}`}>
                      {result.ok ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
                      {result.msg}
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => handleTestAsr(p.profile_id)}
                    disabled={result?.loading}
                    className="btn btn-secondary btn-sm"
                  >
                    {result?.loading ? '测试中...' : '测试连通性'}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDeleteAsr(p.profile_id)}
                    className="btn btn-danger btn-sm p-1.5"
                    title="删除配置"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* LLM List */}
      {currentTab === 'llm' && (
        <div className="grid gap-3">
          {llmProfiles.map((p) => {
            const result = testResults[p.profile_id]
            return (
              <div key={p.profile_id} className="p-4 bg-panel rounded-xl border border-line flex items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-white text-sm">{p.name}</span>
                    <span className="badge badge-accent text-xs font-mono">{p.model}</span>
                  </div>
                  <div className="text-xs text-fg-dim font-mono truncate max-w-lg">
                    接口: {p.api_base || 'https://api.openai.com/v1'}
                  </div>
                  {result && (
                    <div className={`text-xs mt-1 flex items-center gap-1 ${result.ok ? 'text-green-400' : 'text-red-400'}`}>
                      {result.ok ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
                      {result.msg}
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => handleTestLlm(p.profile_id)}
                    disabled={result?.loading}
                    className="btn btn-secondary btn-sm"
                  >
                    {result?.loading ? '测试中...' : '测试连通性'}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDeleteLlm(p.profile_id)}
                    className="btn btn-danger btn-sm p-1.5"
                    title="删除配置"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Add Modal */}
      {addModalOpen && (
        <div className="modal-backdrop">
          <div className="modal-dialog">
            <div className="modal-header">
              <h3 className="modal-title">
                {modalType === 'asr' ? '添加语音识别模型配置' : '添加翻译模型配置'}
              </h3>
            </div>
            <form onSubmit={handleSaveProfile} className="modal-body space-y-4">
              <div className="space-y-1">
                <label className="text-sm font-medium">配置名称 *</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="例: 本地 Medium / DeepSeek V3 翻译"
                  className="input-text"
                  required
                />
              </div>

              {modalType === 'asr' && (
                <>
                  <div className="space-y-1">
                    <label className="text-sm font-medium">提供商</label>
                    <select
                      value={provider}
                      onChange={(e) => setProvider(e.target.value)}
                      className="input-text"
                    >
                      <option value="faster-whisper">本地 Faster-Whisper</option>
                      <option value="deepgram">Deepgram API</option>
                      <option value="gemini-audio">Gemini Audio API</option>
                    </select>
                  </div>

                  <div className="space-y-1">
                    <label className="text-sm font-medium">模型标识 (例如 medium, large-v3)</label>
                    <input
                      type="text"
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="medium"
                      className="input-text"
                      required
                    />
                  </div>
                </>
              )}

              {modalType === 'llm' && (
                <>
                  <div className="space-y-1">
                    <label className="text-sm font-medium">API Base 地址</label>
                    <input
                      type="text"
                      value={apiBase}
                      onChange={(e) => setApiBase(e.target.value)}
                      placeholder="https://api.openai.com/v1"
                      className="input-text"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="text-sm font-medium">模型名称 (例如 gpt-4o-mini, deepseek-chat)</label>
                    <input
                      type="text"
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="gpt-4o-mini"
                      className="input-text"
                      required
                    />
                  </div>
                </>
              )}

              <div className="space-y-1">
                <label className="text-sm font-medium">API Key (若需要)</label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="sk-..."
                  className="input-text"
                />
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  onClick={() => setAddModalOpen(false)}
                  className="btn btn-secondary"
                >
                  取消
                </button>
                <button type="submit" className="btn btn-primary">
                  保存配置
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
