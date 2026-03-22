export interface TaskResponse {
  task_id: string;
  status: string;
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
}

export interface DashboardStats {
  totalVideos: number;
  processedToday: number;
  successRate: number;
  activeTasks: number;
}

export interface ProcessRequest {
  video_id: string;
  platforms: string[];
  subtitle_style?: Record<string, unknown>;
  subtitle_language_overrides?: Record<string, string>;
}

export interface ProcessResult {
  video_id: string;
  outputs: Record<string, string>;
  subtitle_languages: Record<string, string>;
}

export interface SubtitleStyleConfig {
  default: Record<string, unknown>;
  platforms: Record<string, Record<string, unknown>>;
}

export interface SaveSrtRequest {
  language: string;
  segments: SubtitleSegment[];
}

export interface PreviewFrameRequest {
  language: string;
  timestamp: number;
  subtitle_style?: Record<string, unknown>;
}

export interface PreviewClipRequest {
  language: string;
  start: number;
  duration: number;
  subtitle_style?: Record<string, unknown>;
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

export interface PlatformSpec {
  subtitle_language: string;
  max_duration: number | null;
  max_file_size_mb: number;
  resolution: string;
  max_bitrate: string;
  crf: number;
  title_max_length: number;
  hashtag_limit: number;
}
