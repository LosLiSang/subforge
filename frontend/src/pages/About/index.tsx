import React from 'react'
import {
  ExternalLink,
  Code2,
  Cpu,
  Sparkles,
  Headphones,
} from 'lucide-react'
import subforgeLogo from '../../assets/subforge-icon.svg'

export function AboutPage() {
  return (
    <div className="about-page-container">
      <div className="page-header">
        <div className="page-title-wrap">
          <h1 className="page-title">关于 SubForge</h1>
          <span className="page-subtitle">面向同人音声与 ASMR 的本地媒体管理与双语字幕工作台</span>
        </div>
      </div>

      <div className="card-panel" style={{ display: 'flex', flexDirection: 'column', gap: 24, padding: 32 }}>
        {/* Brand Banner */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
          <img src={subforgeLogo} alt="SubForge" style={{ width: 64, height: 64 }} />
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <h2 style={{ fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em' }}>SubForge</h2>
              <span className="chip" style={{ background: 'var(--accent-soft)', color: 'var(--accent-base)', fontWeight: 700 }}>
                v0.5.0
              </span>
            </div>
            <p style={{ fontSize: 14, color: 'var(--fg-dim)', marginTop: 4 }}>
              音声工坊 · 本地同人音声管理、沉浸式双语播放与 AI 语音转写翻译流水线
            </p>
          </div>
        </div>

        {/* Architecture details */}
        <div>
          <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 14, color: '#fff' }}>
            技术架构与核心组件
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14 }}>
            <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: 14, borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600, marginBottom: 4, color: 'var(--accent-base)' }}>
                <Code2 size={16} />
                现代全栈架构
              </div>
              <p style={{ fontSize: 12.5, color: 'var(--fg-dim)' }}>
                React 19 + TypeScript + Vite 前端，搭配 FastAPI + Starlette + Uvicorn 异步服务驱动。
              </p>
            </div>

            <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: 14, borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600, marginBottom: 4, color: 'var(--color-purple)' }}>
                <Cpu size={16} />
                前沿语音识别引擎
              </div>
              <p style={{ fontSize: 12.5, color: 'var(--fg-dim)' }}>
                支持 faster-whisper (本地离线 GPU/CPU)、Deepgram Nova-3 与 Google Gemini 长音频转写。
              </p>
            </div>

            <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: 14, borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600, marginBottom: 4, color: 'var(--color-green)' }}>
                <Sparkles size={16} />
                LLM 双语剧情翻译
              </div>
              <p style={{ fontSize: 12.5, color: 'var(--fg-dim)' }}>
                支持任意 OpenAI-Compatible 模型（DeepSeek, Qwen, Claude, GPT），专为同人音声与 ASMR 定制台本。
              </p>
            </div>

            <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: 14, borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600, marginBottom: 4, color: 'var(--color-amber)' }}>
                <Headphones size={16} />
                沉浸式双语播放体验
              </div>
              <p style={{ fontSize: 12.5, color: 'var(--fg-dim)' }}>
                对齐 asmr.one / Apple Music 设计规范，支持中日双语字幕逐句高亮、倍速播放、睡眠定时器与时间轴校对。
              </p>
            </div>
          </div>
        </div>

        {/* Open source link */}
        <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 13, color: 'var(--fg-faint)' }}>
            基于 MIT License 开源发布
          </span>

          <a
            href="https://github.com/LosLiSang/subforge"
            target="_blank"
            rel="noreferrer"
            className="btn btn-ghost btn-sm"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
              <path
                d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
              />
            </svg>
            GitHub 仓库
            <ExternalLink size={12} />
          </a>
        </div>
      </div>
    </div>
  )
}
