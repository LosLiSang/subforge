export interface Creator {
  creator_id: string
  name: string
  kind: 'voice_actor' | 'circle'
  item_count?: number
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

export interface ModelProfile {
  profile_id: string
  name: string
  kind?: string
  provider?: string
  model?: string
  api_base?: string
  context_size?: number
  temperature?: number
  prompt?: string
  has_key?: boolean
  compute_type?: string
  device?: string
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
