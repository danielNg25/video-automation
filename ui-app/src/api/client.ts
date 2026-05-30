import type {
  TaskResponse,
  VideoMetadata,
  VideoListResponse,
  SrtResponse,
  DashboardStats,
  SaveSrtRequest,
  TranslationProfile,
  TranslationProfileSummary,
  VoiceInfo,
  TTSProviderInfo,
  SubtitleRegion,
  BlurSettings,
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
  ocrRegion?: { x: number; y: number; w: number; h: number },
  ocrConfig?: Record<string, unknown>,
): Promise<TaskResponse> {
  return request('/transcribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      video_id: videoId,
      language,
      task,
      ocr_region: ocrRegion ?? null,
      ocr_config: ocrConfig ?? null,
    }),
  });
}

export function getSampleFrameUrl(videoId: string, timestamp: number = 1.0): string {
  return `${BASE}/videos/${videoId}/sample-frame?timestamp=${timestamp}`;
}

export function getSrt(
  videoId: string,
  language: string = 'zh',
  version: string = 'draft',
): Promise<SrtResponse> {
  return request(
    `/videos/${videoId}/srt?language=${language}&version=${version}`,
  );
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

export function putSrt(videoId: string, req: SaveSrtRequest): Promise<SrtResponse> {
  return request(`/videos/${videoId}/srt`, {
    method: 'PUT',
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
  overrides?: { backend?: string; model?: string; api_key?: string; base_url?: string },
): Promise<TaskResponse> {
  return request('/translate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      video_id: videoId,
      profile_name: profileName,
      source_language: sourceLang,
      ...overrides,
    }),
  });
}

// --- Pipeline ---

export function postPipeline(
  url: string,
  translateProfile?: string,
  sourceLanguage: string = 'zh',
  translationOverride?: { backend: string; model: string; api_key?: string; base_url?: string },
  blurEnabled: boolean = true,
  ttsOverrides?: {
    tts_provider?: string;
    tts_voice?: string;
    tts_language?: string;
    tts_api_key?: string;
    llm_api_key?: string;
    llm_backend?: string;
    playback_speed?: number;
    underlay_db?: number;
    subtitle_style?: Record<string, unknown> | null;
  },
): Promise<TaskResponse> {
  return request('/pipeline/full', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      url,
      platforms: ['youtube', 'tiktok'],
      translate_profile: translateProfile ?? null,
      translation_override: translationOverride ?? null,
      source_language: sourceLanguage,
      blur_enabled: blurEnabled,
      tts_provider: ttsOverrides?.tts_provider ?? 'google',
      tts_voice: ttsOverrides?.tts_voice ?? null,
      tts_language: ttsOverrides?.tts_language ?? 'vi',
      tts_api_key: ttsOverrides?.tts_api_key ?? null,
      llm_api_key: ttsOverrides?.llm_api_key ?? null,
      llm_backend: ttsOverrides?.llm_backend ?? null,
      playback_speed: ttsOverrides?.playback_speed ?? null,
      underlay_db: ttsOverrides?.underlay_db ?? null,
      subtitle_style: ttsOverrides?.subtitle_style ?? null,
    }),
  });
}

// --- Config ---

export function getConfig(): Promise<Record<string, unknown>> {
  return request('/settings/config');
}

export function putConfig(config: Record<string, unknown>): Promise<{ status: string; message: string }> {
  return request('/settings/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
}

// --- TTS ---

export function postTTS(
  videoId: string,
  language: string,
  provider: string,
  voice: string,
  version: string = 'draft',
  shortenToFit: boolean = true,
  apiKey?: string,
  llmApiKey?: string,
  llmBackend?: string,
  playbackSpeed?: number,
  underlayDb?: number,
): Promise<TaskResponse> {
  return request('/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      video_id: videoId,
      language,
      provider,
      voice,
      version,
      enable_shortening: shortenToFit,
      api_key: apiKey ?? null,
      llm_api_key: llmApiKey ?? null,
      llm_backend: llmBackend ?? null,
      playback_speed: playbackSpeed ?? null,
      underlay_db: underlayDb ?? null,
    }),
  });
}

export function getTTSProviders(): Promise<TTSProviderInfo[]> {
  return request('/tts/providers');
}

export function getTTSVoices(language?: string, provider: string = 'google', apiKey?: string): Promise<VoiceInfo[]> {
  const params = new URLSearchParams({ provider });
  if (language) params.set('language', language);
  if (apiKey) params.set('api_key', apiKey);
  return request(`/tts/voices?${params}`);
}

export function getTTSAudioUrl(videoId: string, language: string, filename?: string): string {
  const base = `${BASE}/videos/${videoId}/tts/${language}`;
  return filename ? `${base}?file=${encodeURIComponent(filename)}` : base;
}

export interface TTSAudioEntry {
  filename: string;
  language: string;
  provider: string;
  voice: string;
  size: number;
  created_at: number;
  version: string;
}

export async function deleteTTSAudio(videoId: string, filename: string): Promise<void> {
  await request(`/videos/${videoId}/tts/${encodeURIComponent(filename)}`, { method: 'DELETE' });
}

export async function getTTSList(videoId: string): Promise<TTSAudioEntry[]> {
  return request(`/videos/${videoId}/tts`);
}

export async function postTTSPreview(
  text: string,
  voice: string,
  provider: string = 'edge',
  speed: string = '+0%',
  pitch: string = '+0Hz',
  apiKey?: string,
  playbackSpeed: number = 1.0,
  underlayDb: number = 0,
): Promise<Blob> {
  const res = await fetch(`${BASE}/tts/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice, provider, speed, pitch, api_key: apiKey ?? null, playback_speed: playbackSpeed, underlay_db: underlayDb }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    // FastAPI returns {"detail": "..."} JSON
    let msg = `TTS preview failed (${res.status})`;
    try { const parsed = JSON.parse(detail); if (parsed.detail) msg = parsed.detail; } catch { if (detail) msg = detail; }
    throw new Error(msg);
  }
  return res.blob();
}

// --- Download URLs ---

export function getSrtDownloadUrl(videoId: string, language: string): string {
  return `${BASE}/videos/${videoId}/srt/download?language=${language}`;
}

// --- System info ---

export function getPlatform(): Promise<{ platform: string }> {
  return request('/settings/platform');
}

// --- Cookie management ---

export interface CookieStatus {
  exists: boolean;
  preview: string;
  length: number;
  file_path: string;
  helper_config_synced: boolean;
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

// --- Subtitle Replacement (Phase 6) ---

export function getSubtitleRegion(videoId: string): Promise<SubtitleRegion> {
  return request(`/videos/${videoId}/subtitle-region`);
}

export async function postPreviewBlur(
  videoId: string,
  timestamp: number,
  blurSettings: BlurSettings,
  region?: SubtitleRegion,
): Promise<Blob> {
  const res = await fetch(`${BASE}/videos/${videoId}/preview-blur`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      timestamp,
      blur_settings: blurSettings,
      region: region ?? null,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Blur preview failed (${res.status})`);
  }
  return res.blob();
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

// ── Task cancellation ────────────────────────────────────────────────

export interface CancelTaskResponse {
  task_id: string;
  status: 'cancelled' | 'cancelling' | 'completed' | 'failed';
  cleaned: boolean;
  video_id: string | null;
  message?: string;
}

export function cancelTask(taskId: string): Promise<CancelTaskResponse> {
  return request(`/tasks/${taskId}/cancel`, { method: 'POST' });
}
