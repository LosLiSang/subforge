import React, { useState, useEffect } from 'react'
import {
  Plus,
  Cpu,
  Bot,
  Trash2,
  Edit2,
  Activity,
  CheckCircle2,
  XCircle,
  X,
  Sparkles,
  LayoutGrid,
  List,
  Zap,
  ChevronDown,
  Info,
  TrendingUp,
  ArrowDownRight,
  ArrowUpRight,
  Clock,
  Target,
  Mic,
} from 'lucide-react'
import { api } from '../../api/client'
import type { ModelProfile } from '../../types'

function getProviderInfo(p: ModelProfile) {
  const modelLower = (p.model || '').toLowerCase()
  const nameLower = (p.name || '').toLowerCase()
  const baseLower = (p.base_url || p.api_base || '').toLowerCase()

  if (p.provider === 'faster-whisper') {
    return {
      brand: 'faster-whisper',
      type: 'Whisper 本地',
      color: '#3fb950',
      bg: 'rgba(63, 185, 80, 0.14)',
      icon: <Cpu size={14} />,
    }
  }
  if (p.provider === 'deepgram' || nameLower.includes('deepgram') || modelLower.includes('nova')) {
    return {
      brand: 'Deepgram',
      type: '云端转写',
      color: '#a855f7',
      bg: 'rgba(168, 85, 247, 0.14)',
      icon: <Sparkles size={14} />,
    }
  }
  if (modelLower.includes('gemini') || baseLower.includes('google') || baseLower.includes('generative')) {
    return {
      brand: 'Gemini',
      type: '多模态',
      color: '#38bdf8',
      bg: 'rgba(56, 189, 248, 0.14)',
      icon: <Sparkles size={14} />,
    }
  }
  if (nameLower.includes('ollama') || baseLower.includes('11434')) {
    return {
      brand: 'Ollama',
      type: '本地模型',
      color: '#f59e0b',
      bg: 'rgba(245, 158, 11, 0.14)',
      icon: <Bot size={14} />,
    }
  }
  return {
    brand: 'OpenAI',
    type: '兼容协议',
    color: '#38bdf8',
    bg: 'rgba(56, 189, 248, 0.14)',
    icon: <Bot size={14} />,
  }
}

function formatKey(masked?: string, hasKey?: boolean) {
  if (!masked && !hasKey) return '免密 / 本地'
  if (!masked) return '密钥: 已配置'
  const compact = masked.replace(/•{3,}/g, '••••')
  return `密钥: ${compact}`
}

function compactMaskedKey(masked?: string): string {
  if (!masked) return ''
  return masked.replace(/•{3,}/g, '••••')
}

function formatModelDisplay(model?: string) {
  if (!model) return '—'
  if (model.includes('/')) {
    const parts = model.split('/')
    return parts[parts.length - 1]
  }
  return model
}

function getNowFormatted() {
  const d = new Date()
  const yyyy = d.getFullYear()
  const m = d.getMonth() + 1
  const dd = d.getDate()
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${yyyy}/${m}/${dd} ${hh}:${mm}:${ss}`
}

function formatDateTime(isoOrStr?: string | null) {
  if (!isoOrStr) return '—'
  try {
    const d = new Date(isoOrStr)
    if (isNaN(d.getTime())) return isoOrStr
    const m = d.getMonth() + 1
    const dd = d.getDate()
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    return `${m}/${dd} ${hh}:${mm}`
  } catch {
    return isoOrStr
  }
}

function cleanBaseUrl(url?: string) {
  if (!url) return '—'
  return url.replace(/^https?:\/\//, '').replace(/\/+$/, '')
}

export function ProfilesPage() {
  const [activeTab, setActiveTab] = useState<'asr' | 'llm'>('llm')
  const [viewMode, setViewMode] = useState<'table' | 'grid'>('grid')
  const [asrProfiles, setAsrProfiles] = useState<ModelProfile[]>([])
  const [llmProfiles, setLlmProfiles] = useState<ModelProfile[]>([])
  const [loading, setLoading] = useState(true)

  // Test status state: profile_id -> { loading: boolean, success?: boolean, latency?: number, message?: string, timestamp?: string }
  const [testResults, setTestResults] = useState<Record<string, { loading?: boolean; success?: boolean; latency?: number; message?: string; timestamp?: string }>>({})

  // Pagination
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)
  const [jumpPage, setJumpPage] = useState('1')

  // Modal state (Add / Edit)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingProfile, setEditingProfile] = useState<ModelProfile | null>(null)
  const [formKind, setFormKind] = useState<'asr' | 'llm'>('llm')
  const [formName, setFormName] = useState('')
  const [formProvider, setFormProvider] = useState('openai_compatible')
  const [formModel, setFormModel] = useState('deepseek-chat')
  const [formBaseUrl, setFormBaseUrl] = useState('')
  const [formApiKey, setFormApiKey] = useState('')
  const [formDevice, setFormDevice] = useState('cuda')
  const [formTemperature, setFormTemperature] = useState(0.0)
  const [formMaxSeconds, setFormMaxSeconds] = useState(60)
  const [formReasoningEffort, setFormReasoningEffort] = useState('')
  const [formCaps, setFormCaps] = useState<string[]>(['translate'])
  const [submitting, setSubmitting] = useState(false)

  const loadProfiles = async () => {
    setLoading(true)
    try {
      const res = await api.get<{ asr_profiles: ModelProfile[]; llm_profiles: ModelProfile[] }>('/api/profiles')
      setAsrProfiles(res.asr_profiles || [])
      setLlmProfiles(res.llm_profiles || [])
    } catch (err) {
      console.error('Failed to load profiles:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadProfiles()
  }, [])

  const handleTestProfile = async (profileId: string) => {
    setTestResults((prev) => ({
      ...prev,
      [profileId]: { loading: true },
    }))
    const start = performance.now()
    try {
      const res = await api.post<{
        ok?: boolean
        error?: string
        message?: string
        latency_ms?: number
        status?: 'online' | 'failed'
        tested_at?: string
      }>(`/profiles/${profileId}/test`)
      const duration = res.latency_ms !== undefined ? res.latency_ms : Math.round(performance.now() - start)
      const nowStr = getNowFormatted()
      const isSuccess = res.ok !== false && res.status !== 'failed'
      const statusMsg = res.message || (isSuccess ? '连接成功' : res.error || '测试失败')

      setTestResults((prev) => ({
        ...prev,
        [profileId]: {
          loading: false,
          success: isSuccess,
          latency: duration,
          message: statusMsg,
          timestamp: nowStr,
        },
      }))

      const updateList = (list: ModelProfile[]) =>
        list.map((p) =>
          p.profile_id === profileId
            ? {
                ...p,
                health: {
                  status: isSuccess ? ('online' as const) : ('failed' as const),
                  latency_ms: duration,
                  tested_at: res.tested_at || new Date().toISOString(),
                  message: statusMsg,
                },
              }
            : p
        )
      setAsrProfiles(updateList)
      setLlmProfiles(updateList)
    } catch (err: any) {
      const duration = Math.round(performance.now() - start)
      const nowStr = getNowFormatted()
      const errMsg = err.message || '网络连接失败'
      setTestResults((prev) => ({
        ...prev,
        [profileId]: {
          loading: false,
          success: false,
          latency: duration,
          message: errMsg,
          timestamp: nowStr,
        },
      }))
      const updateList = (list: ModelProfile[]) =>
        list.map((p) =>
          p.profile_id === profileId
            ? {
                ...p,
                health: {
                  status: 'failed' as const,
                  latency_ms: duration,
                  tested_at: new Date().toISOString(),
                  message: errMsg,
                },
              }
            : p
        )
      setAsrProfiles(updateList)
      setLlmProfiles(updateList)
    }
  }

  const handleDeleteProfile = async (profileId: string, name: string) => {
    if (!window.confirm(`确定要删除配置「${name}」吗？`)) return
    try {
      await api.post(`/profiles/${profileId}/delete`)
      loadProfiles()
    } catch (err: any) {
      alert('删除失败: ' + err.message)
    }
  }

  const handleOpenAdd = (kind: 'asr' | 'llm') => {
    setEditingProfile(null)
    setFormKind(kind)
    setFormName('')
    if (kind === 'asr') {
      setFormProvider('faster-whisper')
      setFormModel('large-v3')
      setFormCaps(['transcribe'])
    } else {
      setFormProvider('openai_compatible')
      setFormModel('deepseek-chat')
      setFormCaps(['translate'])
    }
    setFormBaseUrl('')
    setFormApiKey('')
    setFormDevice('cuda')
    setFormTemperature(0.0)
    setFormMaxSeconds(60)
    setFormReasoningEffort('')
    setModalOpen(true)
  }

  const handleOpenEdit = (p: ModelProfile) => {
    setEditingProfile(p)
    setFormKind(activeTab)
    setFormName(p.name || '')
    setFormModel(p.model || '')
    setFormBaseUrl(p.base_url || p.api_base || '')
    setFormProvider(p.provider || p.protocol || 'openai_compatible')
    setFormApiKey('')
    setFormDevice(p.device || 'cuda')
    setFormTemperature(p.temperature ?? 0.0)
    setFormMaxSeconds(p.max_request_seconds ?? 60)
    setFormReasoningEffort(p.reasoning_effort || '')
    setFormCaps(p.capabilities || (activeTab === 'asr' ? ['transcribe'] : ['translate']))
    setModalOpen(true)
  }

  const handleSubmitModal = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formName.trim() || !formModel.trim()) {
      alert('请填写配置名称与模型标识')
      return
    }
    setSubmitting(true)
    try {
      const formData = new FormData()
      if (editingProfile) {
        formData.append('profile_id', editingProfile.profile_id)
      }
      formData.append('kind', formKind)
      formData.append('name', formName.trim())
      formData.append('model', formModel.trim())
      formData.append('base_url', formBaseUrl.trim())
      formData.append('protocol', formProvider)
      if (formApiKey.trim()) {
        formData.append('api_key', formApiKey.trim())
      }
      if (formDevice) {
        formData.append('device', formDevice)
      }
      formData.append('temperature', String(formTemperature))
      formData.append('max_request_seconds', String(formMaxSeconds))
      formData.append('reasoning_effort', formReasoningEffort)
      if (formCaps.includes('transcribe')) formData.append('cap_transcribe', 'on')
      if (formCaps.includes('translate')) formData.append('cap_translate', 'on')
      if (formCaps.includes('merge')) formData.append('cap_merge', 'on')

      await api.postForm('/profiles', formData)
      setModalOpen(false)
      setFormName('')
      setFormApiKey('')
      setEditingProfile(null)
      loadProfiles()
    } catch (err: any) {
      alert((editingProfile ? '编辑配置失败: ' : '添加配置失败: ') + err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const displayed = activeTab === 'asr' ? asrProfiles : llmProfiles
  const totalItems = displayed.length
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize))
  const startIndex = (currentPage - 1) * pageSize
  const pagedItems = displayed.slice(startIndex, startIndex + pageSize)

  // Keep page in valid bounds
  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages)
    }
  }, [totalPages, currentPage])

  return (
    <div className="profiles-page-container">
      {/* Header */}
      <div className="page-header">
        <div className="page-title-wrap">
          <h1 className="page-title">翻译配置</h1>
          <span className="page-subtitle">
            管理大语言模型翻译引擎（OpenAI / DeepSeek / Gemini / Ollama）与 ASR 语音转写服务
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ display: 'flex', background: 'rgba(255, 255, 255, 0.05)', borderRadius: 'var(--radius-sm)', padding: 2 }}>
            <button
              type="button"
              className={`btn btn-sm ${viewMode === 'table' ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setViewMode('table')}
              title="列表表格视图 (参考 Image #2 格式)"
            >
              <List size={15} />
              表格
            </button>
            <button
              type="button"
              className={`btn btn-sm ${viewMode === 'grid' ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setViewMode('grid')}
              title="卡片网格视图"
            >
              <LayoutGrid size={15} />
              卡片
            </button>
          </div>

          <button
            type="button"
            className="btn btn-primary"
            onClick={() => handleOpenAdd(activeTab)}
          >
            <Plus size={16} />
            新建配置
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 24, borderBottom: '1px solid var(--border-subtle)', paddingBottom: 12 }}>
        <button
          type="button"
          className={`btn btn-sm ${activeTab === 'llm' ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => setActiveTab('llm')}
        >
          <Bot size={14} />
          LLM 翻译模型配置 ({llmProfiles.length})
        </button>
        <button
          type="button"
          className={`btn btn-sm ${activeTab === 'asr' ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => setActiveTab('asr')}
        >
          <Cpu size={14} />
          ASR 语音转写配置 ({asrProfiles.length})
        </button>
      </div>

      {/* Profiles Grid */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-dim)' }}>
          <p>正在载入配置…</p>
        </div>
      ) : displayed.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-dim)' }}>
          <p>暂无相关配置</p>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            style={{ marginTop: 12 }}
            onClick={() => handleOpenAdd(activeTab)}
          >
            创建首个配置
          </button>
        </div>
      ) : viewMode === 'table' ? (
        /* ─── 参考 Image #2 格式制作的专业表格视图 ─── */
        <div className="profiles-table-wrap">
        <div className="works-table-container">
          <table className="works-table newapi-table">
            <colgroup>
              <col style={{ width: 130 }} />
              <col style={{ width: '25%' }} />
              <col style={{ width: '35%' }} />
              <col style={{ width: '22%' }} />
              <col style={{ width: 130 }} />
              <col style={{ width: 110 }} />
            </colgroup>
            <thead>
              <tr>
                <th>类型</th>
                <th>标识</th>
                <th>地址</th>
                <th>模型</th>
                <th>近期测试</th>
                <th style={{ textAlign: 'right' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {pagedItems.map((p) => {
                const test = testResults[p.profile_id]
                const isTesting = test?.loading
                const isOnline = isTesting ? false : test ? test.success === true : p.health?.status === 'online'
                const isFailed = isTesting ? false : test ? test.success === false : p.health?.status === 'failed'
                const latency = test?.latency !== undefined ? test.latency : p.health?.latency_ms
                const info = getProviderInfo(p)
                const endpoint = p.base_url || p.api_base || '—'

                return (
                  <tr key={p.profile_id}>
                    {/* 1. 类型 */}
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: 28,
                            height: 28,
                            borderRadius: '50%',
                            background: info.bg,
                            color: info.color,
                            flexShrink: 0,
                          }}
                        >
                          {info.icon}
                        </span>
                        <div style={{ display: 'flex', flexDirection: 'column' }}>
                          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg-main)' }}>{info.brand}</span>
                          <span style={{ fontSize: 10.5, color: 'var(--fg-faint)' }}>{info.type}</span>
                        </div>
                      </div>
                    </td>

                    {/* 2. 标识 */}
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                        <span
                          style={{
                            fontWeight: 600,
                            fontSize: 13.5,
                            color: 'var(--fg-main)',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                          title={p.name}
                        >
                          {p.name}
                        </span>
                        <span
                          style={{
                            fontSize: 11,
                            color: 'var(--fg-dim)',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                          title={p.api_key_masked}
                        >
                          {formatKey(p.api_key_masked, p.has_key)}
                        </span>
                      </div>
                    </td>

                    {/* 3. 地址 */}
                    <td>
                      <span
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: 12,
                          color: 'var(--fg-dim)',
                          maxWidth: '100%',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          display: 'block',
                        }}
                        title={endpoint}
                      >
                        {endpoint}
                      </span>
                    </td>

                    {/* 4. 模型 */}
                    <td>
                      <span
                        className="chip"
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: 11.5,
                          background: 'rgba(255, 255, 255, 0.07)',
                          color: 'var(--fg-main)',
                          border: '1px solid var(--border-subtle)',
                          maxWidth: '100%',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          display: 'inline-block',
                          verticalAlign: 'middle',
                        }}
                        title={p.model}
                      >
                        {formatModelDisplay(p.model)}
                      </span>
                    </td>

                    {/* 5. 近期测试状态 */}
                    <td>
                      {isTesting ? (
                        <span style={{ color: '#eab308', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                          <Zap size={11} className="spin-slow" /> 测试中...
                        </span>
                      ) : isOnline ? (
                        <span style={{ color: '#22c55e', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                          ✓ {latency !== undefined && latency !== null ? `${latency}ms` : '在线'}
                        </span>
                      ) : isFailed ? (
                        <span
                          style={{ color: '#ef4444', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12 }}
                          title={test?.message || p.health?.message || '握手失败'}
                        >
                          ✕ 异常 {latency !== undefined && latency !== null ? `(${latency}ms)` : ''}
                        </span>
                      ) : (
                        <span style={{ color: 'var(--fg-faint)', fontSize: 12 }}>— 未测试</span>
                      )}
                    </td>

                    {/* 6. 操作 (编辑 / 删除 / 测试) */}
                    <td style={{ textAlign: 'right' }}>
                      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center' }}>
                        <button
                          type="button"
                          className="action-btn action-btn-edit"
                          onClick={() => handleOpenEdit(p)}
                          title="编辑该配置"
                        >
                          <Edit2 size={13} />
                        </button>

                        <button
                          type="button"
                          className="action-btn action-btn-delete"
                          onClick={() => handleDeleteProfile(p.profile_id, p.name)}
                          title="删除配置"
                        >
                          <Trash2 size={13} />
                        </button>

                        <button
                          type="button"
                          className="action-btn action-btn-test"
                          onClick={() => handleTestProfile(p.profile_id)}
                          disabled={isTesting}
                          title="发起连通性与延迟测试"
                        >
                          <Zap size={13} className={isTesting ? 'spin-slow' : ''} />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        </div>
      ) : (
        /* ─── 现代化监控卡片视图（纯真实数据：真实端点、连通状态、延迟、历史任务选用） ─── */
        <>
        <div className="newapi-card-grid">
          {pagedItems.map((p) => {
            const test = testResults[p.profile_id]
            const isTesting = test?.loading
            const isOnline = isTesting ? false : test ? test.success === true : p.health?.status === 'online'
            const isFailed = isTesting ? false : test ? test.success === false : p.health?.status === 'failed'
            const latency = test?.latency !== undefined ? test.latency : p.health?.latency_ms
            const statusMessage = test?.message || p.health?.message
            const testedAt = test?.timestamp || (p.health?.tested_at ? formatDateTime(p.health.tested_at) : null)
            const selectionCount = p.usage?.selected_count || 0
            const lastUsedAt = p.usage?.last_used_at ? formatDateTime(p.usage.last_used_at) : '未使用'

            const providerLabel = p.provider || (p.protocol === 'google_native' ? 'Google 原生' : 'OpenAI 兼容')
            const endpoint = p.base_url || p.api_base || '—'
            const modelDisplay = formatModelDisplay(p.model)

            return (
              <div
                key={p.profile_id}
                className="newapi-card"
              >
                {/* 1. Header */}
                <div className="newapi-card-header">
                  <div className="newapi-card-title-group">
                    <span
                      className={`newapi-status-dot ${
                        isTesting
                          ? 'dot-testing'
                          : isOnline
                          ? 'dot-online'
                          : isFailed
                          ? 'dot-failed'
                          : 'dot-untested'
                      }`}
                      title={isTesting ? '正在测试连通性...' : isOnline ? '在线可用' : isFailed ? '服务异常或离线' : '未测试'}
                    />
                    <h3 className="newapi-card-name" title={p.name}>
                      {p.name}
                    </h3>
                  </div>

                  <div className="newapi-card-actions">
                    <button
                      type="button"
                      className="action-btn action-btn-edit"
                      onClick={() => handleOpenEdit(p)}
                      title="编辑配置"
                    >
                      <Edit2 size={12} />
                    </button>

                    <button
                      type="button"
                      className="action-btn action-btn-delete"
                      onClick={() => handleDeleteProfile(p.profile_id, p.name)}
                      title="删除配置"
                    >
                      <Trash2 size={12} />
                    </button>

                    <button
                      type="button"
                      className="action-btn action-btn-test"
                      onClick={() => handleTestProfile(p.profile_id)}
                      disabled={isTesting}
                      title="测试端点连通性与响应时间"
                    >
                      <Zap size={12} className={isTesting ? 'spin-slow' : ''} />
                    </button>
                  </div>
                </div>

                {/* 2. Subtitle: Model Badge + Provider + Endpoint */}
                <div className="newapi-card-sub">
                  <span className="newapi-model-badge" title={p.model}>{modelDisplay}</span>
                  <span className="newapi-dot-sep">·</span>
                  <span className="newapi-provider-tag">{providerLabel}</span>
                  <span className="newapi-dot-sep">·</span>
                  <span className="newapi-url-text" title={endpoint}>{cleanBaseUrl(endpoint)}</span>
                </div>

                {/* 3. Section 1: 真实连通与健康状态 */}
                <div className="newapi-subpanel">
                  <div className="newapi-subpanel-head">
                    <span className="newapi-subpanel-title">连通检测</span>
                    <span className="newapi-subpanel-meta">
                      {testedAt ? `测试于: ${testedAt}` : '尚未检测'}
                    </span>
                  </div>

                  <div className="newapi-metrics-row">
                    <div className="newapi-metric-item">
                      <span className="newapi-metric-label">状态</span>
                      <span className={`newapi-metric-val ${isOnline ? 'val-success' : isFailed ? 'val-failed' : isTesting ? 'val-testing' : 'val-dim'}`}>
                        {isTesting ? '检测中' : isOnline ? '正常' : isFailed ? '异常' : '未检测'}
                      </span>
                    </div>
                    <div className="newapi-metric-item">
                      <span className="newapi-metric-label">延迟</span>
                      <span className={`newapi-metric-val ${latency !== undefined && latency !== null ? 'val-latency' : 'val-dim'}`}>
                        {latency !== undefined && latency !== null ? `${latency}ms` : '—'}
                      </span>
                    </div>
                    <div className="newapi-metric-item">
                      <span className="newapi-metric-label">任务选用</span>
                      <span className="newapi-metric-val val-cost">
                        {selectionCount > 0 ? `${selectionCount} 次` : '0 次'}
                      </span>
                    </div>
                    <div className="newapi-metric-item" style={{ gridColumn: 'span 2' }}>
                      <span className="newapi-metric-label">最近任务调用</span>
                      <span className="newapi-metric-val val-dim" style={{ fontSize: '11.5px' }} title={p.usage?.last_used_at || ''}>
                        {lastUsedAt}
                      </span>
                    </div>
                  </div>

                  {/* 真实响应消息提示 */}
                  <div className={`newapi-health-banner ${isOnline ? 'banner-online' : isFailed ? 'banner-failed' : 'banner-untested'}`}>
                    {isFailed ? (
                      <>
                        <XCircle size={13} className="banner-icon" />
                        <span className="banner-text" title={statusMessage || '接口握手失败'}>
                          {statusMessage || '接口握手失败，请检查网络或密钥'}
                        </span>
                      </>
                    ) : isOnline ? (
                      <>
                        <CheckCircle2 size={13} className="banner-icon" />
                        <span className="banner-text">
                          {statusMessage || 'HTTP 200 握手成功 · 接口响应正常'}
                        </span>
                      </>
                    ) : (
                      <>
                        <Activity size={13} className="banner-icon" />
                        <span className="banner-text">点击右上角 ⚡ 按钮发起连通性测试</span>
                      </>
                    )}
                  </div>
                </div>

                {/* 4. Section 2: 配置规格与运行参数 */}
                <div className="newapi-subpanel">
                  <div className="newapi-subpanel-head">
                    <span className="newapi-subpanel-title">配置规格</span>
                    <div className="newapi-caps-row">
                      {(p.capabilities || ['translate']).map((cap) => (
                        <span key={cap} className="newapi-cap-tag">
                          {cap === 'translate' ? '翻译' : cap === 'transcribe' ? '语音转写' : cap === 'merge' ? '文本校对' : cap}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="newapi-specs-grid">
                    <div className="newapi-spec-item">
                      <span className="newapi-spec-label">API 密钥</span>
                      <span className="newapi-spec-val" title={p.api_key_masked}>
                        {formatKey(p.api_key_masked, p.has_key)}
                      </span>
                    </div>

                    <div className="newapi-spec-item">
                      <span className="newapi-spec-label">采样温度</span>
                      <span className="newapi-spec-val">
                        {p.temperature !== undefined ? p.temperature : 0.0}
                      </span>
                    </div>

                    <div className="newapi-spec-item">
                      <span className="newapi-spec-label">分片上限</span>
                      <span className="newapi-spec-val">
                        {p.max_request_seconds ? `${p.max_request_seconds}s` : '60s'}
                      </span>
                    </div>

                    <div className="newapi-spec-item">
                      <span className="newapi-spec-label">思考等级</span>
                      <span className="newapi-spec-val">
                        {p.reasoning_effort === 'none' ? '关闭 (0)' : p.reasoning_effort || '默认'}
                      </span>
                    </div>

                    <div className="newapi-spec-item">
                      <span className="newapi-spec-label">网络与证书</span>
                      <span className="newapi-spec-val">
                        {p.proxy_url ? '代理' : '直连'} · {p.verify_tls === false ? '跳过 TLS' : '验证 TLS'}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
        </>
      )}

      {/* ─── Bottom Pagination Bar (仿照 Image #1 底栏) ─── */}
      {displayed.length > 0 && (
        <div className="newapi-pagination-bar">
          <div className="newapi-pagination-left">
            <span>
              第 {currentPage} / {totalPages} 页 · 显示 {startIndex + 1}-{Math.min(startIndex + pageSize, totalItems)} / {totalItems}
            </span>
          </div>

          <div className="newapi-pagination-right">
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>每页</span>
              <select
                className="select-field"
                style={{ padding: '2px 8px', fontSize: 12, height: 28 }}
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value))
                  setCurrentPage(1)
                }}
              >
                <option value={6}>6 条/页</option>
                <option value={12}>12 条/页</option>
                <option value={24}>24 条/页</option>
              </select>
            </div>

            <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={currentPage <= 1}
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            >
              上一页
            </button>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={currentPage >= totalPages}
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
            >
              下一页
            </button>

            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>前往</span>
              <input
                type="number"
                min={1}
                max={totalPages}
                value={jumpPage}
                onChange={(e) => setJumpPage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    const pageNum = parseInt(jumpPage)
                    if (pageNum >= 1 && pageNum <= totalPages) {
                      setCurrentPage(pageNum)
                    }
                  }
                }}
                className="input-field"
                style={{ width: 44, padding: '2px 6px', textAlign: 'center', height: 28, fontSize: 12 }}
              />
              <span>页</span>
            </div>
          </div>
        </div>
      )}

      {/* Add / Edit Profile Modal */}
      {modalOpen && (
        <div className="modal-overlay" onClick={() => setModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">
                {editingProfile ? `编辑配置: ${editingProfile.name}` : '新建模型配置'}
              </h3>
              <button
                type="button"
                className="btn btn-ghost btn-circle"
                onClick={() => setModalOpen(false)}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSubmitModal}>
              <div className="modal-body">
                {!editingProfile && (
                  <div>
                    <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                      配置类型
                    </label>
                    <div style={{ display: 'flex', gap: 16 }}>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                        <input
                          type="radio"
                          name="formKind"
                          checked={formKind === 'llm'}
                          onChange={() => {
                            setFormKind('llm')
                            setFormProvider('openai_compatible')
                            setFormModel('deepseek-chat')
                            setFormCaps(['translate'])
                          }}
                        />
                        LLM 翻译模型
                      </label>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                        <input
                          type="radio"
                          name="formKind"
                          checked={formKind === 'asr'}
                          onChange={() => {
                            setFormKind('asr')
                            setFormProvider('faster-whisper')
                            setFormModel('large-v3')
                            setFormCaps(['transcribe'])
                          }}
                        />
                        ASR 语音识别
                      </label>
                    </div>
                  </div>
                )}

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                    配置显示名称 *
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="如: Lisang New API, DeepSeek, 或 本地 Ollama"
                    required
                    autoFocus
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                    引擎提供商 (Provider)
                  </label>
                  <select
                    className="select-field"
                    style={{ width: '100%' }}
                    value={formProvider}
                    onChange={(e) => setFormProvider(e.target.value)}
                  >
                    {formKind === 'asr' ? (
                      <>
                        <option value="faster-whisper">faster-whisper (本地离线 GPU)</option>
                        <option value="deepgram">Deepgram Nova-3 (云端极速)</option>
                        <option value="gemini">Google Gemini Audio (云端长音频)</option>
                        <option value="openai_compatible">OpenAI 兼容音频服务</option>
                      </>
                    ) : (
                      <>
                        <option value="openai_compatible">openai_compatible (DeepSeek / Qwen / Claude / New API)</option>
                        <option value="gemini">Google Gemini Flash</option>
                      </>
                    )}
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                    模型标识 (Model ID) *
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={formModel}
                    onChange={(e) => setFormModel(e.target.value)}
                    placeholder="如: deepseek-v4-flash, glm-5.3-flash, qwen-plus"
                    required
                  />
                </div>

                {formProvider !== 'faster-whisper' && (
                  <>
                    <div>
                      <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                        API Base URL
                      </label>
                      <input
                        type="text"
                        className="input-field"
                        value={formBaseUrl}
                        onChange={(e) => setFormBaseUrl(e.target.value)}
                        placeholder="如: https://api.deepseek.com/v1 或 http://127.0.0.1:11434/v1"
                      />
                    </div>
                    <div>
                      <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                        API Key{' '}
                        {editingProfile && editingProfile.api_key_masked && (
                          <span
                            style={{ color: 'var(--accent-base)', wordBreak: 'break-all' }}
                            title={editingProfile.api_key_masked}
                          >
                            (已安全配置: {compactMaskedKey(editingProfile.api_key_masked)})
                          </span>
                        )}
                      </label>
                      <input
                        type="password"
                        className="input-field"
                        value={formApiKey}
                        onChange={(e) => setFormApiKey(e.target.value)}
                        placeholder={editingProfile?.api_key_masked ? '留空保留已有 API 密钥，输入新 Key 则覆盖' : 'sk-...'}
                      />
                    </div>
                  </>
                )}

                {formProvider === 'faster-whisper' && (
                  <div>
                    <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                      运行设备
                    </label>
                    <select
                      className="select-field"
                      style={{ width: '100%' }}
                      value={formDevice}
                      onChange={(e) => setFormDevice(e.target.value)}
                    >
                      <option value="cuda">CUDA (NVIDIA 显卡)</option>
                      <option value="cpu">CPU (兼容模式)</option>
                    </select>
                  </div>
                )}

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                      温度 (Temperature)
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="2"
                      className="input-field"
                      value={formTemperature}
                      onChange={(e) => setFormTemperature(parseFloat(e.target.value) || 0)}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                      单次请求超时 (秒)
                    </label>
                    <input
                      type="number"
                      min="10"
                      max="300"
                      className="input-field"
                      value={formMaxSeconds}
                      onChange={(e) => setFormMaxSeconds(parseInt(e.target.value) || 60)}
                    />
                  </div>
                </div>

                {formProvider !== 'faster-whisper' && (
                  <div>
                    <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                      思考等级 / 推理深度 (Reasoning Effort)
                    </label>
                    <select
                      className="select-field"
                      style={{ width: '100%' }}
                      value={formReasoningEffort}
                      onChange={(e) => setFormReasoningEffort(e.target.value)}
                    >
                      <option value="">跟随服务端默认</option>
                      <option value="none">关闭思考 / Level 0 (none - 极速不思考)</option>
                      <option value="low">低思考预算 (low)</option>
                      <option value="medium">中等思考 (medium)</option>
                      <option value="high">高思考深度 (high)</option>
                    </select>
                    <span style={{ fontSize: 11, color: 'var(--fg-faint)', marginTop: 4, display: 'block' }}>
                      如需彻底关闭 Gemini / DeepSeek-R1 / o1 类模型的思考过程，请选择「关闭思考 / Level 0 (none)」。
                    </span>
                  </div>
                )}

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--fg-dim)', marginBottom: 6 }}>
                    模型适用流水线能力
                  </label>
                  <div style={{ display: 'flex', gap: 16 }}>
                    {[
                      { key: 'translate', label: '台本翻译' },
                      { key: 'transcribe', label: '语音转写' },
                      { key: 'merge', label: '台本对齐合并' },
                    ].map((cap) => {
                      const checked = formCaps.includes(cap.key)
                      return (
                        <label key={cap.key} style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13 }}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setFormCaps((prev) => [...prev, cap.key])
                              } else {
                                setFormCaps((prev) => prev.filter((k) => k !== cap.key))
                              }
                            }}
                          />
                          {cap.label}
                        </label>
                      )
                    })}
                  </div>
                </div>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setModalOpen(false)}
                  disabled={submitting}
                >
                  取消
                </button>
                <button type="submit" className="btn btn-primary" disabled={submitting || !formName.trim()}>
                  {submitting ? '正在保存…' : editingProfile ? '保存修改' : '确认添加'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
