import type {
  TaskResponse,
  VideoMetadata,
  VideoListResponse,
  SrtResponse,
  DashboardStats,
  ProcessRequest,
  SubtitleStyleConfig,
  PlatformSpec,
} from './types';

const BASE = '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

export function postDownload(url: string): Promise<TaskResponse> {
  return request('/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
}

export function getVideos(status?: string): Promise<VideoListResponse> {
  const params = status ? `?status=${status}` : '';
  return request(`/videos${params}`);
}

export function getVideo(videoId: string): Promise<VideoMetadata> {
  return request(`/videos/${videoId}`);
}

export function postTranscribe(
  videoId: string,
  language: string = 'zh',
  task: string = 'transcribe',
): Promise<TaskResponse> {
  return request('/transcribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_id: videoId, language, task }),
  });
}

export function getSrt(videoId: string, language: string = 'zh'): Promise<SrtResponse> {
  return request(`/videos/${videoId}/srt?language=${language}`);
}

export function patchVideoTitle(videoId: string, title: string): Promise<VideoMetadata> {
  return request(`/videos/${videoId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
}

export async function deleteVideo(videoId: string): Promise<void> {
  await request(`/videos/${videoId}`, { method: 'DELETE' });
}

export function getStats(): Promise<DashboardStats> {
  return request('/stats');
}

export function postProcess(req: ProcessRequest): Promise<TaskResponse> {
  return request('/process', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
}

export function getSubtitleStyles(): Promise<SubtitleStyleConfig> {
  return request('/subtitle-styles');
}

export function getPlatforms(): Promise<Record<string, PlatformSpec>> {
  return request('/platforms');
}

export function getProcessedVideoUrl(videoId: string, platform: string): string {
  return `${BASE}/videos/${videoId}/output/${platform}`;
}

export function subscribeSSE(
  taskId: string,
  onEvent: (eventType: string, data: Record<string, unknown>) => void,
): EventSource {
  const es = new EventSource(`${BASE}/events/${taskId}`);

  for (const type of ['progress', 'complete', 'error']) {
    es.addEventListener(type, (e: MessageEvent) => {
      onEvent(type, JSON.parse(e.data));
    });
  }

  return es;
}
