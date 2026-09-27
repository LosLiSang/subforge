import { useEffect, useState } from 'react'
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
    <>
      <div className="page-head">
        <div>
          <h1>模型配置</h1>
          <p className="page-sub">
            配置本地 Faster-Whisper、在线 Deepgram、Gemini 以及各类 OpenAI 兼容的大语言模型
          </p>
        </div>

        <button
          type="button"
          className="primary"
          onClick={() => {
            setModalType(currentTab)
            setAddModalOpen(true)
          }}
        >
          <svg className="btn-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
          {currentTab === 'asr' ? '添加语音模型' : '添加翻译模型'}
        </button>
      </div>

      <nav className="tab-bar" role="tablist">
        <button
          type="button"
          onClick={() => setCurrentTab('asr')}
          className={`tab ${currentTab === 'asr' ? 'active' : ''}`}
        >
          语音识别模型 (ASR)
        </button>
        <button
          type="button"
          onClick={() => setCurrentTab('llm')}
          className={`tab ${currentTab === 'llm' ? 'active' : ''}`}
        >
          翻译大模型 (LLM)
        </button>
      </nav>

      {currentTab === 'asr' && (
        <div className="model-status-row" style={{ padding: '12px 14px', marginBottom: 16 }}>
          <strong>本地 Faster-Whisper 缓存状态：</strong>
          <span>{cachedModels.length > 0 ? cachedModels.join(', ') : '未检测到本地缓存模型'}</span>
          <small style={{ color: 'var(--fg-faint)', marginLeft: 12 }}>首次运行未缓存模型时将自动下载</small>
        </div>
      )}

      {currentTab === 'asr' && (
        <div className="profile-list">
          {asrProfiles.map((p) => {
            const result = testResults[p.profile_id]
            return (
              <article key={p.profile_id} className="profile-row">
                <div className="profile-row-main">
                  <strong className="profile-row-name">{p.name}</strong>
                  <span className="profile-row-model">{p.model}</span>
                  <span className="profile-row-badges">
                    <span className="chip chip-cap chip-cap-transcribe">{p.provider || 'faster-whisper'}</span>
                    {p.device && <span className="chip">{p.device}</span>}
                    {p.has_key && <span className="chip chip-key">已配置密钥</span>}
                  </span>
                </div>

                <div className="profile-row-actions">
                  <div className="profile-controls">
                    <button
                      type="button"
                      className="profile-action profile-action-test"
                      onClick={() => handleTestAsr(p.profile_id)}
                      disabled={result?.loading}
                    >
                      <svg viewBox="0 0 16 16" aria-hidden="true" style={{ width: 14, height: 14 }}>
                        <path d="M8 2.25a5.75 5.75 0 1 0 5.75 5.75M8 5v3l2 1.25" />
                      </svg>
                      <span>{result?.loading ? '测试中…' : '测试'}</span>
                    </button>
                    <button
                      type="button"
                      className="profile-action profile-action-delete"
                      onClick={() => handleDeleteAsr(p.profile_id)}
                    >
                      <svg viewBox="0 0 16 16" aria-hidden="true" style={{ width: 14, height: 14 }}>
                        <path d="M3.5 4.25h9M6 2.75h4M5 6.25v6.5m3-6.5v6.5m3-6.5v6.5M4.25 4.25l.5 9h6.5l.5-9" />
                      </svg>
                      <span>删除</span>
                    </button>
                  </div>
                  {result && (
                    <output className="check-result" style={{ color: result.ok ? '#3fb950' : '#ff7b72' }}>
                      {result.msg}
                    </output>
                  )}
                </div>
              </article>
            )
          })}
        </div>
      )}

      {currentTab === 'llm' && (
        <div className="profile-list">
          {llmProfiles.map((p) => {
            const result = testResults[p.profile_id]
            return (
              <article key={p.profile_id} className="profile-row">
                <div className="profile-row-main">
                  <strong className="profile-row-name">{p.name}</strong>
                  <span className="profile-row-model">{p.model}</span>
                  <span className="profile-row-url">{p.api_base || p.base_url}</span>
                  <span className="profile-row-badges">
                    <span className="chip chip-cap chip-cap-translate">翻译</span>
                    <span className="chip chip-direct">直连</span>
                    <span className="chip chip-key">sk-***</span>
                  </span>
                </div>

                <div className="profile-row-actions">
                  <div className="profile-controls">
                    <button
                      type="button"
                      className="profile-action profile-action-test"
                      onClick={() => handleTestLlm(p.profile_id)}
                      disabled={result?.loading}
                    >
                      <svg viewBox="0 0 16 16" aria-hidden="true" style={{ width: 14, height: 14 }}>
                        <path d="M8 2.25a5.75 5.75 0 1 0 5.75 5.75M8 5v3l2 1.25" />
                      </svg>
                      <span>{result?.loading ? '测试中…' : '测试'}</span>
                    </button>
                    <button
                      type="button"
                      className="profile-action profile-action-delete"
                      onClick={() => handleDeleteLlm(p.profile_id)}
                    >
                      <svg viewBox="0 0 16 16" aria-hidden="true" style={{ width: 14, height: 14 }}>
                        <path d="M3.5 4.25h9M6 2.75h4M5 6.25v6.5m3-6.5v6.5m3-6.5v6.5M4.25 4.25l.5 9h6.5l.5-9" />
                      </svg>
                      <span>删除</span>
                    </button>
                  </div>
                  {result && (
                    <output className="check-result" style={{ color: result.ok ? '#3fb950' : '#ff7b72' }}>
                      {result.msg}
                    </output>
                  )}
                </div>
              </article>
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
            <form onSubmit={handleSaveProfile} className="modal-body">
              <label>
                配置名称
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="例: 本地 Medium / DeepSeek V3 翻译"
                  required
                />
              </label>

              {modalType === 'asr' && (
                <>
                  <label>
                    提供商
                    <select
                      value={provider}
                      onChange={(e) => setProvider(e.target.value)}
                    >
                      <option value="faster-whisper">本地 Faster-Whisper</option>
                      <option value="deepgram">Deepgram API</option>
                      <option value="gemini-audio">Gemini Audio API</option>
                    </select>
                  </label>

                  <label>
                    模型标识
                    <input
                      type="text"
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="medium"
                      required
                    />
                  </label>
                </>
              )}

              {modalType === 'llm' && (
                <>
                  <label>
                    API Base 地址
                    <input
                      type="text"
                      value={apiBase}
                      onChange={(e) => setApiBase(e.target.value)}
                      placeholder="https://api.openai.com/v1"
                    />
                  </label>

                  <label>
                    模型名称
                    <input
                      type="text"
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="gpt-4o-mini"
                      required
                    />
                  </label>
                </>
              )}

              <label>
                API Key (若需要)
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="sk-..."
                />
              </label>

              <div className="modal-footer">
                <button
                  type="button"
                  onClick={() => setAddModalOpen(false)}
                  className="ghost"
                >
                  取消
                </button>
                <button type="submit" className="primary">
                  保存配置
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  )
}
