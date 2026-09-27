import { Headphones, Sparkles, Cpu, Layers } from 'lucide-react'

export function AboutPage() {
  return (
    <div className="page-container space-y-8 max-w-2xl">
      <div className="text-center py-6 space-y-3">
        <div className="w-16 h-16 rounded-2xl bg-accent/15 border border-accent/30 flex items-center justify-center mx-auto text-accent">
          <Headphones size={32} />
        </div>
        <h1 className="text-2xl font-bold tracking-tight text-white">SubForge</h1>
        <div className="text-xs font-mono px-2.5 py-1 rounded-full bg-panel-2 border border-line inline-block text-fg-dim">
          v0.5.0 · React + TypeScript + FastAPI
        </div>
        <p className="text-sm text-fg-dim max-w-md mx-auto">
          本地同人音声与 ASMR 沉浸式双语字幕生成与媒体库管理工具
        </p>
      </div>

      <div className="p-5 bg-panel rounded-xl border border-line space-y-4">
        <h2 className="text-base font-semibold text-white">技术架构</h2>
        <div className="space-y-3 text-sm text-fg-dim">
          <div className="flex items-start gap-3">
            <Sparkles size={18} className="text-accent flex-none mt-0.5" />
            <div>
              <strong className="text-white">前端技术栈：</strong>
              React 19 + TypeScript + Vite + Tailwind CSS，全局无间断跨页面底栏播放器，逐行跟随双语字幕编辑器与悬浮歌词系统。
            </div>
          </div>

          <div className="flex items-start gap-3">
            <Layers size={18} className="text-purple-400 flex-none mt-0.5" />
            <div>
              <strong className="text-white">后端服务架构：</strong>
              基于 FastAPI 现代异步框架重塑，Pydantic Schema 强类型约束，流式 Range 切片音频传输，任务中心异步队列。
            </div>
          </div>

          <div className="flex items-start gap-3">
            <Cpu size={18} className="text-green-400 flex-none mt-0.5" />
            <div>
              <strong className="text-white">语音与翻译模型引擎：</strong>
              内置 Faster-Whisper 本地离线高精度转录，原生支持 Deepgram 与 Google Gemini 1.5 音频大模型，融合上下文感知流式 LLM 二次元术语翻译。
            </div>
          </div>
        </div>
      </div>

      <div className="text-center text-xs text-fg-faint space-y-1">
        <p>开源许可：MIT License</p>
        <p>基于开源社区贡献者们的智慧共同打造</p>
      </div>
    </div>
  )
}
