import type { VersionEntry } from './types';

const BASE = '/api';

function request(path: string, init?: RequestInit) {
  return fetch(`${BASE}${path}`, init).then(async (r) => {
    if (!r.ok) {
      const body = await r.text().catch(() => '');
      throw new Error(`${r.status} ${body}`);
    }
    if (r.status === 204) return undefined;
    return r.json();
  });
}

export async function getVersions(
  videoId: string,
  language: string,
): Promise<VersionEntry[]> {
  return request(`/videos/${videoId}/versions?language=${language}`);
}

export async function createVersion(
  videoId: string,
  language: string,
  name: string | null,
): Promise<VersionEntry> {
  return request(`/videos/${videoId}/versions?language=${language}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}

export async function renameVersion(
  videoId: string,
  language: string,
  versionId: string,
  name: string | null,
): Promise<VersionEntry> {
  return request(
    `/videos/${videoId}/versions/${versionId}?language=${language}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    },
  );
}

export async function deleteVersion(
  videoId: string,
  language: string,
  versionId: string,
): Promise<void> {
  await request(
    `/videos/${videoId}/versions/${versionId}?language=${language}`,
    { method: 'DELETE' },
  );
}
