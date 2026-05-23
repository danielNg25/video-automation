import type { TranslationProfileSummary } from '../../api/types';

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

interface Props {
  profiles: TranslationProfileSummary[];
  selectedProfile: string;
  onChangeProfile: (v: string) => void;
  llmBackend: string;
  onChangeLlmBackend: (v: string) => void;
  llmModel: string;
  onChangeLlmModel: (v: string) => void;
  llmApiKey: string;
  onChangeLlmApiKey: (v: string) => void;
  llmBaseUrl: string;
  onChangeLlmBaseUrl: (v: string) => void;
  isTranslating: boolean;
  translateMessage: string;
  translateProgress: number;
  onTranslate: () => void;
}

export function TranslateTab(props: Props) {
  const {
    profiles, selectedProfile, onChangeProfile,
    llmBackend, onChangeLlmBackend, llmModel, onChangeLlmModel,
    llmApiKey, onChangeLlmApiKey, llmBaseUrl, onChangeLlmBaseUrl,
    isTranslating, translateMessage, translateProgress, onTranslate,
  } = props;

  const models = MODEL_OPTIONS[llmBackend] || [];

  return (
    <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10">
      <div className="p-5 space-y-4">
        <div>
          <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 block mb-1">Translation Profile</label>
          <div className="flex gap-2">
            <select
              value={selectedProfile}
              onChange={(e) => onChangeProfile(e.target.value)}
              className="flex-1 bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
            >
              {profiles.length === 0 && <option value="">No profiles available</option>}
              {profiles.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
            </select>
          </div>
          <p className="text-[10px] text-on-surface-variant mt-1">
            LLM defaults loaded from Settings. Edits below apply only to this run. Manage profiles in <a href="/profiles" className="text-primary underline">Translation Profiles</a>.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 block mb-1">LLM Backend</label>
            <select
              value={llmBackend}
              onChange={(e) => onChangeLlmBackend(e.target.value)}
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
              value={llmModel}
              onChange={(e) => onChangeLlmModel(e.target.value)}
              className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
            >
              {models.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 block mb-1">API Key</label>
            <input
              type="password"
              value={llmApiKey}
              onChange={(e) => onChangeLlmApiKey(e.target.value)}
              placeholder="sk-…"
              className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0 font-mono"
            />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 block mb-1">Base URL (optional)</label>
            <input
              type="text"
              value={llmBaseUrl}
              onChange={(e) => onChangeLlmBaseUrl(e.target.value)}
              placeholder="https://api.openai.com"
              className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0 font-mono"
            />
          </div>
        </div>

        <button
          onClick={onTranslate}
          disabled={isTranslating || !selectedProfile}
          className="bg-primary text-on-primary-fixed px-5 py-2 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 whitespace-nowrap active:scale-95 transition-all disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-sm">translate</span>
          {isTranslating ? 'Translating…' : 'Run Translation'}
        </button>

        {isTranslating && (
          <div className="space-y-2">
            <div className="flex justify-between text-[10px] font-mono text-on-surface-variant">
              <span>{translateMessage}</span>
              <span>{Math.round(translateProgress)}%</span>
            </div>
            <div className="w-full bg-surface-container-highest h-1.5 rounded-full overflow-hidden">
              <div className="h-full bg-primary transition-all" style={{ width: `${translateProgress}%` }} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
