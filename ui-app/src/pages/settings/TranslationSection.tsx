import { useState, useCallback, useEffect } from 'react';
import { loadLLMPrefs, saveLLMPrefs, loadApiKeys, saveApiKey } from '../../utils/storage';

const MODEL_OPTIONS: Record<string, { label: string; value: string }[]> = {
  deepseek: [
    { label: 'DeepSeek V3', value: 'deepseek-chat' },
    { label: 'DeepSeek R1', value: 'deepseek-reasoner' },
  ],
  anthropic: [
    { label: 'Claude Sonnet 4', value: 'claude-sonnet-4-20250514' },
    { label: 'Claude Haiku 3.5', value: 'claude-3-5-haiku-20241022' },
    { label: 'Claude Opus 4', value: 'claude-opus-4-20250514' },
  ],
  openai: [
    { label: 'GPT-4o', value: 'gpt-4o' },
    { label: 'GPT-4o Mini', value: 'gpt-4o-mini' },
    { label: 'GPT-4.1', value: 'gpt-4.1' },
    { label: 'GPT-4.1 Mini', value: 'gpt-4.1-mini' },
  ],
};

function getDefaultBaseUrl(backend: string): string {
  return backend === 'deepseek' ? 'https://api.deepseek.com' : '';
}

function getApiKeyForBackend(backend: string): string {
  const keys = loadApiKeys();
  return keys[backend] || '';
}

export function TranslationSection() {
  const [prefs, setPrefs] = useState(loadLLMPrefs);
  const [apiKey, setApiKey] = useState(() => getApiKeyForBackend(loadLLMPrefs().backend));
  const [baseUrl, setBaseUrl] = useState(() => getDefaultBaseUrl(loadLLMPrefs().backend));
  const [savedMsg, setSavedMsg] = useState('');

  useEffect(() => {
    if (!savedMsg) return;
    const t = setTimeout(() => setSavedMsg(''), 2000);
    return () => clearTimeout(t);
  }, [savedMsg]);

  const handleBackendChange = useCallback((newBackend: string) => {
    setPrefs((prev) => ({ ...prev, backend: newBackend }));
    setApiKey(getApiKeyForBackend(newBackend));
    setBaseUrl(getDefaultBaseUrl(newBackend));
  }, []);

  const handleSave = useCallback(() => {
    try {
      saveLLMPrefs(prefs.backend, prefs.model);
      if (
        apiKey &&
        (prefs.backend === 'anthropic' || prefs.backend === 'openai' || prefs.backend === 'deepseek')
      ) {
        saveApiKey(prefs.backend, apiKey);
      }
      setSavedMsg('Saved.');
    } catch (e) {
      setSavedMsg(`Save failed: ${e instanceof Error ? e.message : 'unknown error'}`);
    }
  }, [prefs.backend, prefs.model, apiKey]);

  const models = MODEL_OPTIONS[prefs.backend] || [];

  return (
    <section className="space-y-6">
      <div className="border-b border-zinc-800/30 pb-4">
        <h2 className="text-xl font-semibold text-on-surface">Translation</h2>
        <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">
          Default LLM used by translation runs. Manage translation style profiles on the{' '}
          <a href="/profiles" className="text-primary underline">Translation Profiles</a> page.
        </p>
      </div>

      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 block mb-1">Backend</label>
            <select
              value={prefs.backend}
              onChange={(e) => handleBackendChange(e.target.value)}
              className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
            >
              <option value="anthropic">Anthropic</option>
              <option value="deepseek">DeepSeek</option>
              <option value="openai">OpenAI</option>
            </select>
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 block mb-1">Model</label>
            <select
              value={prefs.model}
              onChange={(e) => setPrefs({ ...prefs, model: e.target.value })}
              className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
            >
              {models.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 block mb-1">API Key</label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-…"
            className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0 font-mono"
          />
          <p className="text-[10px] text-on-surface-variant mt-1">Stored in browser only. Never sent to the server config.</p>
        </div>

        <div>
          <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 block mb-1">Base URL (optional)</label>
          <input
            type="text"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.openai.com"
            className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0 font-mono"
          />
        </div>

        <div className="flex items-center gap-3 pt-2 border-t border-outline-variant/10">
          <button
            onClick={handleSave}
            className="bg-primary text-on-primary-fixed px-4 py-2 rounded-md font-bold text-xs uppercase tracking-wider"
          >
            Save defaults
          </button>
          {savedMsg && (
            <span
              className={`text-[10px] font-mono ${
                savedMsg.toLowerCase().startsWith('save failed') || savedMsg.toLowerCase().includes('error')
                  ? 'text-red-400'
                  : 'text-emerald-400'
              }`}
            >
              {savedMsg}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
