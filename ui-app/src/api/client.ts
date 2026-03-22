import type {
  TaskResponse,
  VideoMetadata,
  VideoListResponse,
  SrtResponse,
  DashboardStats,
  ProcessRequest,
  SubtitleStyleConfig,
  PlatformSpec,
  SaveSrtRequest,
  PreviewClipRequest,
  TranslationProfile,
  TranslationProfileSummary,
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

export function putSubtitleStyleDefault(style: Record<string, unknown>): Promise<SubtitleStyleConfig> {
  return request('/subtitle-styles', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(style),
  });
}

export function getVideoStyle(videoId: string): Promise<{ video_id: string; style: Record<string, unknown>; is_custom: boolean }> {
  return request(`/videos/${videoId}/style`);
}

export function putVideoStyle(videoId: string, style: Record<string, unknown>): Promise<{ video_id: string; style: Record<string, unknown>; is_custom: boolean }> {
  return request(`/videos/${videoId}/style`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(style),
  });
}

export function getPlatforms(): Promise<Record<string, PlatformSpec>> {
  return request('/platforms');
}

export function getProcessedVideoUrl(videoId: string, platform: string): string {
  return `${BASE}/videos/${videoId}/output/${platform}`;
}

export function putSrt(videoId: string, req: SaveSrtRequest): Promise<SrtResponse> {
  return request(`/videos/${videoId}/srt`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
}

export function getPreviewFrameUrl(videoId: string, language: string, timestamp: number): string {
  return `${BASE}/videos/${videoId}/preview-frame?language=${language}&timestamp=${timestamp}`;
}

export function postPreviewClip(videoId: string, req: PreviewClipRequest): Promise<TaskResponse> {
  return request(`/videos/${videoId}/preview-clip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
}

export function getRawVideoUrl(videoId: string): string {
  return `${BASE}/videos/${videoId}/raw`;
}

export function getProxyVideoUrl(videoId: string): string {
  return `${BASE}/videos/${videoId}/proxy`;
}

// --- Translation + Profiles ---

export function getProfiles(): Promise<TranslationProfileSummary[]> {
  return request('/profiles');
}

export function getProfile(name: string): Promise<TranslationProfile> {
  return request(`/profiles/${encodeURIComponent(name)}`);
}

export function createProfile(profile: TranslationProfile): Promise<TranslationProfile> {
  return request('/profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(profile),
  });
}

export function updateProfile(name: string, profile: TranslationProfile): Promise<TranslationProfile> {
  return request(`/profiles/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(profile),
  });
}

export async function deleteProfileApi(name: string): Promise<void> {
  await fetch(`${BASE}/profiles/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export function postTranslate(
  videoId: string,
  profileName: string,
  sourceLang: string = 'zh',
): Promise<TaskResponse> {
  return request('/translate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_id: videoId, profile_name: profileName, source_language: sourceLang }),
  });
}

// --- Cookie management ---

export interface CookieStatus {
  exists: boolean;
  preview: string;
  length: number;
  file_path: string;
}

export interface CookieTestResult {
  success: boolean;
  message: string;
}

export function getCookieStatus(): Promise<CookieStatus> {
  return request('/settings/cookie');
}

export function putCookie(cookie: string): Promise<CookieStatus> {
  return request('/settings/cookie', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cookie }),
  });
}

export function testCookie(): Promise<CookieTestResult> {
  return request('/settings/cookie/test', { method: 'POST' });
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
