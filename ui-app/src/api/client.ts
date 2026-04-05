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
  VoiceInfo,
  VoiceProfileConfig,
  TTSPlatformConfig,
  TTSProviderInfo,
  VoiceInfo,
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
  ttsProfile?: string,
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
      tts_profile: ttsProfile ?? null,
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
  voiceProfile: string,
  provider?: string,
  voice?: string,
  apiKey?: string,
  llmApiKey?: string,
  llmBackend?: string,
): Promise<TaskResponse> {
  return request('/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      video_id: videoId,
      language,
      voice_profile: voiceProfile,
      provider: provider ?? null,
      voice: voice ?? null,
      api_key: apiKey ?? null,
      llm_api_key: llmApiKey ?? null,
      llm_backend: llmBackend ?? null,
    }),
  });
}

export function getTTSProviders(): Promise<TTSProviderInfo[]> {
  return request('/tts/providers');
}

export function getTTSVoices(language?: string, provider: string = 'edge', apiKey?: string): Promise<VoiceInfo[]> {
  const params = new URLSearchParams({ provider });
  if (language) params.set('language', language);
  if (apiKey) params.set('api_key', apiKey);
  return request(`/tts/voices?${params}`);
}

export function getTTSProfiles(): Promise<Record<string, VoiceProfileConfig>> {
  return request('/tts/profiles');
}

export function getTTSPlatforms(): Promise<Record<string, TTSPlatformConfig>> {
  return request('/tts/platforms');
}

export function putTTSProfile(name: string, profile: VoiceProfileConfig): Promise<VoiceProfileConfig> {
  return request(`/tts/profiles/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(profile),
  });
}

export async function deleteTTSProfile(name: string): Promise<void> {
  await fetch(`${BASE}/tts/profiles/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export function getTTSAudioUrl(videoId: string, language: string, filename?: string): string {
  const base = `${BASE}/videos/${videoId}/tts/${language}`;
  return filename ? `${base}?file=${encodeURIComponent(filename)}` : base;
}

export interface TTSAudioEntry {
  filename: string;
  language: string;
  provider: string;
  profile: string;
  size: number;
  created_at: number;
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
): Promise<Blob> {
  const res = await fetch(`${BASE}/tts/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice, provider, speed, pitch, api_key: apiKey ?? null }),
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

export function postExport(
  videoId: string,
  subtitleLanguage: string | null,
  ttsFile: string | null,
  videoVolume: number,
  ttsVolume: number,
): Promise<TaskResponse> {
  return request(`/videos/${videoId}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      subtitle_language: subtitleLanguage,
      tts_file: ttsFile,
      video_volume: videoVolume,
      tts_volume: ttsVolume,
    }),
  });
}

export function postExportPreview(
  videoId: string,
  subtitleLanguage: string | null,
  ttsFile: string | null,
  videoVolume: number,
  ttsVolume: number,
): Promise<Blob> {
  return fetch(`${BASE}/videos/${videoId}/export/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      subtitle_language: subtitleLanguage,
      tts_file: ttsFile,
      video_volume: videoVolume,
      tts_volume: ttsVolume,
    }),
  }).then(r => {
    if (!r.ok) throw new Error('Preview failed');
    return r.blob();
  });
}

export function getExportedVideoUrl(videoId: string): string {
  return `${BASE}/videos/${videoId}/export`;
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
