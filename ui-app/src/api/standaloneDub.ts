import type { TaskResponse } from './types';

export interface StandaloneDubEntry {
  uuid: string;
  original_filename: string;
  provider: string;
  voice: string;
  language: string;
  playback_speed: number;
  enable_shortening: boolean;
  duration_seconds: number;
  created_at: string;
  file_size_bytes: number;
}

export interface PostStandaloneDubOpts {
  file: File;
  provider: string;
  voice: string;
  language: string;
  playbackSpeed: number;
  enableShortening: boolean;
  apiKey?: string;
  llmApiKey?: string;
  llmBackend?: string;
  model?: string;
}

export async function postStandaloneDub(
  opts: PostStandaloneDubOpts,
): Promise<TaskResponse> {
  const formData = new FormData();
  formData.append('file', opts.file);
  formData.append('provider', opts.provider);
  formData.append('voice', opts.voice);
  formData.append('language', opts.language);
  formData.append('playback_speed', String(opts.playbackSpeed));
  formData.append('enable_shortening', String(opts.enableShortening));
  if (opts.apiKey) formData.append('api_key', opts.apiKey);
  if (opts.llmApiKey) formData.append('llm_api_key', opts.llmApiKey);
  if (opts.llmBackend) formData.append('llm_backend', opts.llmBackend);
  if (opts.model) formData.append('model', opts.model);

  const r = await fetch('/api/standalone-dub', {
    method: 'POST',
    body: formData,
  });
  if (!r.ok) {
    const body = await r.text().catch(() => '');
    throw new Error(`${r.status} ${body}`);
  }
  return r.json();
}

export async function getStandaloneDubs(): Promise<StandaloneDubEntry[]> {
  const r = await fetch('/api/standalone-dub');
  if (!r.ok) {
    throw new Error(`${r.status}`);
  }
  return r.json();
}

export async function deleteStandaloneDub(dubUuid: string): Promise<void> {
  const r = await fetch(`/api/standalone-dub/${dubUuid}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) {
    throw new Error(`${r.status}`);
  }
}

export function getStandaloneDubUrl(dubUuid: string): string {
  return `/api/standalone-dub/${dubUuid}.wav`;
}
