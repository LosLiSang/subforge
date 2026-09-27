export function AboutPage() {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>关于</h1>
          <p className="page-sub">SubForge Library</p>
        </div>
      </div>

      <section className="dash-section">
        <div className="field-list">
          <div className="field">
            <div className="field-label">版本</div>
            <code>v0.5.0 · React 19 + TypeScript + FastAPI</code>
          </div>

          <div className="field">
            <div className="field-label">仓库源码</div>
            <a href="https://github.com/LosLiSang/subforge" target="_blank" rel="noopener">
              github.com/LosLiSang/subforge
            </a>
          </div>

          <div className="field">
            <div className="field-label">功能说明</div>
            <small>
              本地同人音声与 ASMR 沉浸式双语字幕生成与媒体库管理工具：ASR 识别日语音频 → LLM 翻译成中文 → 双语逐行对照播放与字幕校对。
            </small>
          </div>

          <div className="field">
            <div className="field-label">技术架构</div>
            <small>
              全异步 FastAPI 架构 + Pydantic Schema 强类型约束 + SubForge 原版 OLED 玻璃拟态设计系统 + React 19 全局无中断底栏播放器。
            </small>
          </div>
        </div>
      </section>
    </>
  )
}
