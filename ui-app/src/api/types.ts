export interface TaskResponse {
  task_id: string;
  status: string;
}

export interface VersionEntry {
  id: string;
  name: string | null;
  created_at: string;
}

export interface VideoMetadata {
  video_id: string;
  title: string;
  author: string;
  duration: number;
  resolution: string;
  size: string;
  codec: string;
  description: string;
  hashtags: string[];
  source_url: string;
  file_path: string;
  thumbnail: string;
  has_srt: boolean;
  srt_languages: string[];
  status: string;
}

export interface VideoListResponse {
  videos: VideoMetadata[];
  total: number;
}

export interface SubtitleSegment {
  id: number;
  startTime: string;
  endTime: string;
  text: string;
  translation?: string;
}

export interface SrtResponse {
  video_id: string;
  segments: SubtitleSegment[];
  language: string;
  is_dubsync?: boolean;
}

export interface DashboardStats {
  totalVideos: number;
  processedToday: number;
  successRate: number;
  activeTasks: number;
}

export interface SaveSrtRequest {
  language: string;
  segments: SubtitleSegment[];
}

export interface PreviewClipRequest {
  language: string;
  start: number;
  duration: number;
}

export interface TranslationProfileSummary {
  name: string;
  description: string;
  target_language: string;
}

export interface TranslationProfile {
  name: string;
  description: string;
  target_language: string;
  source_language: string;
  style_guide: string;
  example_pairs: { source: string; target: string }[];
}

export interface OcrRegion {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface TTSRequest {
  video_id: string;
  language: string;
  provider: string;
  voice: string;
  api_key?: string;
}

export interface TTSProviderInfo {
  id: string;
  name: string;
  free: boolean;
  requires_key: boolean;
}

export interface TTSPreviewRequest {
  text: string;
  voice: string;
  provider: string;
  speed?: string;
  pitch?: string;
}

export interface TTSResult {
  video_id: string;
  language: string;
  audio_path: string;
  duration: number;
  segment_count: number;
}

export interface VoiceInfo {
  name: string;
  language: string;
  gender: string;
  provider: string;
  friendly_name: string;
}

export interface PipelineHistoryEntry {
  video_id: string;
  url: string;
  status: string;
  current_stage: string;
  progress: number;
  message: string;
  completed_stages: string[];
  stage_results: Record<string, Record<string, unknown>>;
  timestamps: Record<string, string>;
  platforms: string[];
  error: string | null;
  created_at: string;
  updated_at: string;
}

// --- Subtitle Replacement (Phase 6) ---

export interface SubtitleRegion {
  x: number;
  y: number;
  width: number;
  height: number;
  confidence: number;
  video_width: number;
  video_height: number;
}

export interface BlurSettings {
  enabled: boolean;
  strength: number;
  mode: 'blur' | 'fill' | 'pixelate';
  fill_color: string;
}

export interface PreviewBlurRequest {
  timestamp: number;
  blur_settings: BlurSettings;
  region?: SubtitleRegion;
}


