# 字幕修订与片段重处理 — Design

## 设计原则

1. 正式 SRT 始终是播放器与导出的真相来源。
2. 模型只能生成候选；用户确认是正式字幕发生变化的唯一入口。
3. 时间轴由 SubForge 确定性维护，Gemini 只负责文本理解。
4. 长音频主链保持稳定，原生音频模型只增加短片段能力。
5. 密钥、原始音频请求体和字幕正文不进入 SQLite、metadata 或任务事件。

## 深模块与 seam

新增 `SegmentProcessor` 深模块，将媒体截取、模型调用、翻译、时间偏移、结果校验和错误归一隐藏在统一 Interface 后面。

```python
@dataclass(frozen=True)
class SegmentRequest:
    media_path: Path
    target_start: float
    target_end: float
    context_before: float = 2.0
    context_after: float = 2.0
    source_language: str = "ja"
    target_language: str = "zh"
    processing_mode: str = "transcribe_then_translate"
    recognition_prompt: str = ""

@dataclass(frozen=True)
class SegmentCandidate:
    source_entries: list[SubtitleEntry]
    target_entries: list[SubtitleEntry]
    processor: str
    warnings: tuple[str, ...] = ()

class SegmentProcessor(Protocol):
    async def process(
        self,
        request: SegmentRequest,
        *,
        event_sink: EventSink | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> SegmentCandidate: ...
```

Adapter：

- `WhisperSegmentAdapter`：截取片段后调用现有 ASR；恢复相对时间偏移；再调用文本翻译模块。
- `GeminiAudioAdapter`：截取并编码短音频；调用 Gemini；忽略模型时间戳；按处理模式决定是否调用文本翻译模块。

UI、LibraryStore 和字幕修订模块只依赖 `SegmentProcessor` Interface，不分支处理 Gemini 请求格式。

## Gemini 内部传输 seam

Gemini Adapter 内部包含两个私有 Transport Adapter，但不向 UI 暴露协议细节：

```python
class GeminiAudioTransport(Protocol):
    async def generate(
        self,
        audio: bytes,
        mime_type: str,
        prompt: str,
    ) -> str: ...
```

- `GoogleGeminiTransport`
  - `POST {base_url}/v1beta/models/{model}:generateContent`
  - audio 使用 `inlineData`/`inline_data`
  - API Key 通过受保护的 header/query 发送
- `OpenAICompatibleAudioTransport`
  - `POST {base_url}/chat/completions` 或配置约定的兼容路径
  - message content 包含 `input_audio`
  - 显式指令要求逐字转写或结构化双语结果

两个 Transport 共用：

- 有界超时
- 3 次以内重试
- 空 content/语义空/格式错误按失败处理
- `trust_env=False`
- Profile 显式 proxy
- TLS/CA 配置
- 安全错误清洗

## 处理模式

### `transcribe_then_translate`（推荐）

```text
Gemini 音频 → 源语言文本 → 现有文本 LLM Profile → 目标译文
```

优点：

- 源文可追溯
- ASR 和翻译可独立重试
- 用户可先校正源文再翻译
- 沿用现有翻译质量控制和空响应重试

### `bilingual_once`

```text
Gemini 音频 → {source_text, target_text}
```

作为可选快速模式。必须返回严格结构；缺少源文或译文均失败。不得提供只返回目标译文的正式模式。

## 时间轴策略

### 选区

MVP 从播放器选择单条或连续字幕行：

```text
target_start = selected[0].start
target_end = selected[-1].end
clip_start = max(0, target_start - context_before)
clip_end = min(media_duration, target_end + context_after)
```

### Whisper 候选

Whisper 返回相对 `clip_start` 的时间戳。系统加回偏移后，只保留与目标范围相交的结果；候选可以保留原始边缘文字供用户预览，但确认替换时不得越过目标范围。

### Gemini 候选

Gemini 时间戳不可信：

- 返回单个文本块：复用整个目标范围。
- 返回多块且数量等于原选择条数：可以按原条目时间范围对应，但必须标记“沿用原时间轴”。
- 数量不一致：合并成一个覆盖目标范围的候选；用户可在字幕校正界面手动拆分。

## 字幕修订模块

字幕修订属于独立深模块，负责双 SRT 原子提交、校验、快照和恢复。

```python
class SubtitleRevisionStore:
    def load(self, track_id: str) -> SubtitleDocument: ...
    def commit(self, track_id: str, revision: SubtitleRevision) -> SubtitleDocument: ...
    def restore_previous(self, track_id: str) -> SubtitleDocument: ...
    def restore_baseline(self, track_id: str) -> SubtitleDocument: ...
```

Interface 不暴露 `.bak` 文件布局。实现内部：

1. 读取源字幕和翻译字幕。
2. 校验整个修订后的文档。
3. 首次修改时保存自动生成基线。
4. 每次写入前保存 previous 快照。
5. 两份新 SRT 先写入临时文件并 flush。
6. 全部成功后原子替换正式文件。
7. 任一步失败时回滚，不留下半完成状态。

建议资产布局：

```text
<item>/.subforge/tracks/<track-id>/subtitles/
├── baseline.<source>.srt
├── baseline.<target>.srt
├── previous.<source>.srt
└── previous.<target>.srt
```

具体布局属于实现细节，不进入公共术语。

## Gemini Profile

新增独立 Profile 类型，不复用普通 LLM Profile：

```python
@dataclass
class GeminiAudioProfile:
    profile_id: str
    name: str
    protocol: Literal["google_native", "openai_compatible"]
    base_url: str
    model: str
    default_processing_mode: Literal["transcribe_then_translate", "bilingual_once"]
    max_segment_seconds: int = 60
    recognition_prompt: str = ""
    proxy_url: str = ""
    verify_tls: bool = True
    ca_bundle: str = ""
```

API Key 使用与现有 LLM Profile 相同的安全规则，但存储命名空间独立。`max_segment_seconds` 表示单次模型调用的切块上限（默认 60，不设硬上限）：选区超过该值时，用 ffmpeg silencedetect 检测语音区间并切块逐段识别，时间偏移由 SubForge 拼回；单段语音超限均匀切分，检测失败回退整段一次识别并附带警告。

## UI 流程

播放器字幕行增加选择态与编辑入口：

```text
选择连续字幕
→ [校正所选] [重新处理片段]
```

“重新处理片段”Dialog：

- 目标时间范围
- 前后上下文秒数
- 处理器：Whisper / Gemini
- 对应 Profile/模型
- Gemini 处理模式（操作时可覆盖 Profile 默认值）
- 识别提示词
- “相同配置可能产生相同结果”提示

候选完成后展示：

```text
当前源文 | 候选源文
当前译文 | 候选译文
警告：沿用原时间轴 / 候选条数变化

[接受候选] [编辑后接受] [放弃]
```

片段任务是局部临时任务，不把 Track 标记为 failed；其事件 stage 为 `segment_extract`、`segment_asr`、`segment_translate`、`segment_candidate`。

## 配置页面

新增“原生音频模型”分区，与：

- Whisper/Deepgram ASR 设置
- 文本 LLM 翻译配置

并列，而不是嵌套在任一类别中。

每个 Gemini Profile 显示：

- 名称
- 协议
- 模型名
- 默认处理模式
- 最大片段时长
- 代理/TLS
- Key 来源（掩码）
- 测试、编辑、删除

配置测试必须发送一段内置的极短静音/语音测试资产或要求用户选择测试片段，并验证响应不是空内容。只调用 `/models` 不算通过。

## 测试 seam

沿用项目既定公开测试面：

1. `SegmentProcessor.process()`：通过临时媒体和假 HTTP 上游验证参数、音频传输、错误归一和候选结果。
2. `SubtitleRevisionStore`：通过真实临时 SRT 验证原子提交、快照和恢复。
3. `create_app()` ASGI HTTP：验证选择、提交、候选确认、CSRF 和未确认不落盘。
4. 真实 Worker/ffmpeg 路径：用短临时音频验证截取、时间偏移和取消。

不测试私有 prompt 拼接函数或 Transport 内部方法；测试从上述 Interface 观察行为。

## 失败策略

- 音频截取失败：不调用模型。
- HTTP 200 空结果：重试，耗尽后失败。
- 双语模式缺源文/译文：重试，耗尽后失败。
- 翻译失败：保留源文候选并显示翻译失败，但不能直接接受为完整双语替换；允许用户手动补译。
- 候选确认提交失败：正式 SRT 保持原样。
- 页面关闭：运行中任务可取消；未确认候选可视为临时产物清理。
- Gemini 配置不可用：fail closed，不自动降级到其他含费用或隐私差异的模型。
