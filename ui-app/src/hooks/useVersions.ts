import { useCallback, useEffect, useState } from 'react';
import {
  getVersions,
  createVersion,
  renameVersion,
  deleteVersion,
  importVersion,
} from '../api/versions';
import type { VersionEntry } from '../api/types';

export function useVersions(videoId: string | undefined, language: string) {
  const [versions, setVersions] = useState<VersionEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!videoId) return;
    setLoading(true);
    try {
      const list = await getVersions(videoId, language);
      setVersions(list);
    } finally {
      setLoading(false);
    }
  }, [videoId, language]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const createSnapshot = useCallback(
    async (name: string | null) => {
      if (!videoId) return;
      await createVersion(videoId, language, name);
      await refresh();
    },
    [videoId, language, refresh],
  );

  const rename = useCallback(
    async (versionId: string, name: string | null) => {
      if (!videoId) return;
      await renameVersion(videoId, language, versionId, name);
      await refresh();
    },
    [videoId, language, refresh],
  );

  const remove = useCallback(
    async (versionId: string) => {
      if (!videoId) return;
      await deleteVersion(videoId, language, versionId);
      await refresh();
    },
    [videoId, language, refresh],
  );

  const importFile = useCallback(
    async (file: File, name: string | null) => {
      if (!videoId) return;
      await importVersion(videoId, language, file, name);
      await refresh();
    },
    [videoId, language, refresh],
  );

  return { versions, loading, createSnapshot, rename, remove, refresh, importFile };
}
