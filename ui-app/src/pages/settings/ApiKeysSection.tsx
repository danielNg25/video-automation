import { useEffect, useState } from 'react';
import { loadApiKeys, saveApiKey } from '../../utils/storage';

const PROVIDERS: { key: string; label: string; placeholder: string; icon: string }[] = [
  { key: 'anthropic', label: 'Anthropic', placeholder: 'sk-ant-...', icon: 'neurology' },
  { key: 'openai', label: 'OpenAI', placeholder: 'sk-...', icon: 'psychology' },
  { key: 'deepseek', label: 'DeepSeek', placeholder: 'sk-...', icon: 'model_training' },
  { key: 'elevenlabs', label: 'ElevenLabs', placeholder: 'xi-...', icon: 'record_voice_over' },
  { key: 'google', label: 'Google Cloud', placeholder: 'AIza...', icon: 'cloud' },
  { key: 'gemini', label: 'Gemini (Google AI Studio)', placeholder: 'AIza...', icon: 'auto_awesome' },
  { key: 'vbee', label: 'Vbee Token', placeholder: 'Bearer access token', icon: 'graphic_eq' },
  { key: 'vbee_app_id', label: 'Vbee App ID', placeholder: 'app-id UUID', icon: 'badge' },
];

export function ApiKeysSection() {
  const [apiKeys, setApiKeys] = useState(loadApiKeys);
  const [apiKeySaveMsg, setApiKeySaveMsg] = useState('');

  useEffect(() => {
    if (!apiKeySaveMsg) return;
    const t = setTimeout(() => setApiKeySaveMsg(''), 3000);
    return () => clearTimeout(t);
  }, [apiKeySaveMsg]);

  const handleSave = (providerKey: string, providerLabel: string) => {
    saveApiKey(providerKey, apiKeys[providerKey]);
    setApiKeySaveMsg(`${providerLabel} key saved`);
  };

  const handleClear = (providerKey: string, providerLabel: string) => {
    saveApiKey(providerKey, '');
    setApiKeys({ ...apiKeys, [providerKey]: '' });
    setApiKeySaveMsg(`${providerLabel} key removed`);
  };

  return (
    <section className="space-y-6" id="apikeys">
      <div className="border-b border-zinc-800/30 pb-4">
        <h2 className="text-xl font-semibold text-on-surface">API Keys</h2>
        <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">LLM provider keys for subtitle translation. Stored in browser only.</p>
      </div>
      <div className="bg-surface-container-low p-5 rounded-lg space-y-5">
        <div className="flex items-center gap-2 text-[10px] font-mono text-zinc-500">
          <span className="material-symbols-outlined text-sm">lock</span>
          Keys are saved in your browser&apos;s localStorage — never sent to our server, only to the provider&apos;s API directly.
        </div>

        {PROVIDERS.map((provider) => (
          <div key={provider.key} className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-sm text-zinc-400">{provider.icon}</span>
              <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">{provider.label}</label>
              {apiKeys[provider.key] && (
                <span className="text-[10px] font-mono bg-emerald-900/30 text-emerald-400 px-2 py-0.5 rounded">SAVED</span>
              )}
            </div>
            <div className="flex gap-2">
              <input
                type="password"
                className="flex-1 bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono text-on-surface"
                placeholder={provider.placeholder}
                value={apiKeys[provider.key]}
                onChange={(e) => setApiKeys({ ...apiKeys, [provider.key]: e.target.value })}
              />
              <button
                onClick={() => handleSave(provider.key, provider.label)}
                className="px-4 py-2 bg-primary text-on-primary-fixed text-xs font-bold uppercase tracking-widest rounded"
              >
                Save
              </button>
              {apiKeys[provider.key] && (
                <button
                  onClick={() => handleClear(provider.key, provider.label)}
                  className="px-3 py-2 bg-surface-container-high hover:bg-error/10 hover:text-error text-xs font-bold uppercase tracking-widest rounded transition-colors"
                >
                  Clear
                </button>
              )}
            </div>
          </div>
        ))}

        {apiKeySaveMsg && (
          <div className={`flex items-center gap-2 text-xs font-mono ${apiKeySaveMsg.toLowerCase().startsWith('save failed') || apiKeySaveMsg.toLowerCase().includes('error') ? 'text-red-400' : 'text-emerald-400'}`}>
            <span className="material-symbols-outlined text-sm">check_circle</span>
            {apiKeySaveMsg}
          </div>
        )}
      </div>
    </section>
  );
}
