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
