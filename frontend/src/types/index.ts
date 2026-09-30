export interface Creator {
  creator_id: string
  name: string
  kind: 'voice_actor' | 'circle'
  item_count?: number
}

export interface DlsiteMetadata {
  rj_code: string
  title: string
  circle?: string | null
  voice_actors: string[]
  tags: string[]
  cover_url?: string | null
  release_date?: string | null
}

export interface Track {
  track_id: string
  item_id: string
  title: string
  duration: number
  duration_label: string
  size: number
  status: string
  source_language: string
  target_language: string
  has_media: boolean
  has_source_sub: boolean
  has_target_sub: boolean
  latest_task?: {
    task_id: string
    status: string
    stage?: string
    progress: number
    message?: string
  } | null
}

export interface Item {
  item_id: string
  title: string
  original_title?: string | null
  rj_code?: string | null
  author?: string | null
  release_date?: string | null
  kind: string
  tags: string[]
  creator_ids: string[]
  creators: Creator[]
  cover_url: string
  cover_source?: string | null
  track_count: number
  total_duration: number
  total_duration_label: string
  total_size: number
  subtitle_status: 'none' | 'jp' | 'zh' | 'bilingual'
  created_at?: string | null
  updated_at?: string | null
}

export interface ItemDetailData {
  item: Item
  tracks: Track[]
  overview: {
    track_count: number
    total_duration_label: string
    total_size: number
    playable_count: number
    processing_count: number
    failed_count: number
    actionable_incomplete_count: number
    all_completed: boolean
    first_playable_track_id?: string | null
  }
  available_profiles: {
    asr_profiles: any[]
    llm_profiles: any[]
    cached_models: string[]
    default_model: string
    default_processing?: DefaultProcessingSettings
  }
}

export interface SubtitleEntry {
  index?: number
  start: number
  end: number
  text: string
}

export interface SubtitlesData {
  source_language: string
  target_language: string
  source: SubtitleEntry[]
  target: SubtitleEntry[]
}

export interface SubtitleTask {
  task_id: string
  track_id: string
  kind: string
  status: string
  stage?: string | null
  progress: number
  message?: string | null
  error?: string | null
  created_at?: string | null
  updated_at?: string | null
  track_title?: string | null
  item_title?: string | null
  item_id?: string | null
  profile_label?: string | null
  range?: string | null
  asr?: string | null
  translation?: string | null
}

export interface DownloadTask {
  task_id: string
  url: string
  title: string
  status: string
  message?: string | null
  error?: string | null
  progress: number
  item_id?: string | null
  auto_process_status?: string | null
}

export interface ProfileHealth {
  status: 'online' | 'failed' | 'untested'
  latency_ms?: number | null
  tested_at?: string | null
  message?: string | null
}

export interface ProfileUsage {
  selected_count: number
  last_used_at?: string | null
}

export interface ModelProfile {
  profile_id: string
  name: string
  kind?: string
  provider?: string
  model?: string
  api_base?: string
  base_url?: string
  protocol?: string
  capabilities?: string[]
  api_key_masked?: string
  max_request_seconds?: number
  context_size?: number
  temperature?: number
  reasoning_effort?: string
  prompt?: string
  has_key?: boolean
  compute_type?: string
  device?: string
  proxy_url?: string
  verify_tls?: boolean
  health?: ProfileHealth
  usage?: ProfileUsage
}

export interface DefaultCoverSettings {
  mode: 'preset' | 'url' | 'upload'
  preset: 'default' | 'headphones' | 'wave' | 'studio'
  url: string
  has_custom_file: boolean
}

export interface DefaultProcessingSettings {
  asr_provider: string
  asr_profile_id?: string
  whisper_model?: string
  llm_profile_id?: string
  merge_profile_id?: string
  scene?: string
  asr_chunk_seconds?: number
}

export interface UiSettings {
  library_root?: string | null
  proxy_url?: string | null
  asr_concurrency: number
  remote_asr_concurrency: number
  translate_workers: number
  translation_prompt?: string | null
  no_auth: boolean
  has_deepgram_key: boolean
  has_fixed_token: boolean
  default_cover?: DefaultCoverSettings
  default_processing?: DefaultProcessingSettings
}

export interface StatsData {
  total_items: number
  total_tracks: number
  total_duration: number
  total_duration_label: string
  total_creators: number
  subtitled_tracks: number
  subtitled_percentage: number
}

export interface ImportFolderGroup {
  title: string
  rj_code?: string | null
  tracks: any[]
}

export interface ImportFolderPreviewResponse {
  folder_name: string
  groups: ImportFolderGroup[]
}
