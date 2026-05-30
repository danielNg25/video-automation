import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { storageSet } from '../../utils/storage';
import { TTSPreview } from '../../components/TTSPreview';
import { deleteTTSAudio, getTTSAudioUrl } from '../../api/client';
import type { TTSAudioEntry } from '../../api/client';
import type {
  TTSProviderInfo, VoiceInfo, VersionEntry,
} from '../../api/types';
import { VersionPicker } from '../../components/dub/VersionPicker';

interface Props {
  videoId: string;
  // Version state (parent owns)
  versions: VersionEntry[];
  selectedVersion: string;
  onVersionChange: (v: string) => void;
  // Provider / voice state (parent owns)
  ttsProviders: TTSProviderInfo[];
  selectedTtsProvider: string;
  onChangeTtsProvider: (v: string) => void;
  ttsVoices: VoiceInfo[];
  selectedVoiceId: string;
  onChangeSelectedVoiceId: (v: string) => void;
  voiceIdInput: string;
  onChangeVoiceIdInput: (v: string) => void;
  voiceIdSaved: boolean;
  onSaveVoiceId: () => void;
  ttsApiKey: string;
  onChangeTtsApiKey: (v: string) => void;
  ttsLanguage: string;
  onChangeTtsLanguage: (v: string) => void;
  availableTtsLanguages: string[];
  playbackSpeed: number;
  onChangePlaybackSpeed: (v: number) => void;
  underlayDb: number;
  onChangeUnderlayDb: (v: number) => void;
  useDirectVoice: boolean;
  onChangeUseDirectVoice: (v: boolean) => void;
  // Generation state
  isGeneratingTts: boolean;
  ttsProgress: { pct: number; message: string };
  ttsGenerated: boolean;
  ttsError: string;
  ttsList: TTSAudioEntry[];
  onReloadTtsList: () => void;
  onGenerate: () => void;
  // LLM context (TTSPreview/postTTSPreview don't currently use it, kept for
  // future generate-preview wiring and parity with the legacy fragment).
  llmBackend: string;
  llmApiKey: string;
  // Shortening toggle
  enableShortening: boolean;
  onChangeEnableShortening: (next: boolean) => void;
}

export function DubTab(props: Props) {
  const {
    videoId,
    versions, selectedVersion, onVersionChange,
    ttsProviders, selectedTtsProvider, onChangeTtsProvider,
    ttsVoices, selectedVoiceId, onChangeSelectedVoiceId,
    voiceIdInput, onChangeVoiceIdInput, voiceIdSaved, onSaveVoiceId,
    ttsApiKey,
    ttsLanguage, onChangeTtsLanguage, availableTtsLanguages,
    playbackSpeed, onChangePlaybackSpeed,
    enableShortening, onChangeEnableShortening,
    underlayDb, onChangeUnderlayDb,
    isGeneratingTts, ttsProgress, ttsGenerated, ttsError,
    ttsList, onReloadTtsList, onGenerate,
  } = props;

  const navigate = useNavigate();
  const [playingFilename, setPlayingFilename] = useState<string | null>(null);
  const [savedDefault, setSavedDefault] = useState(false);

  const handleSaveAsDefault = () => {
    storageSet('tts_playback_speed', String(playbackSpeed));
    storageSet('tts_underlay_db', String(underlayDb));
    storageSet('tts_selected_provider', selectedTtsProvider);
    if (selectedVoiceId) {
      storageSet(`tts_voice_id_${selectedTtsProvider}`, selectedVoiceId);
    }
    storageSet('tts_language', ttsLanguage);
    setSavedDefault(true);
    setTimeout(() => setSavedDefault(false), 2000);
  };

  const providerInfo = ttsProviders.find((p) => p.id === selectedTtsProvider);

  return (
    <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10 p-5 space-y-4">
      <div className="flex items-center gap-2 pb-2 border-b border-outline-variant/10">
        <span className="material-symbols-outlined text-primary text-lg">record_voice_over</span>
        <span className="text-xs font-bold uppercase tracking-widest">TTS Dubbing</span>
        <span className="font-mono text-[10px] text-primary bg-primary/10 px-2 py-0.5 rounded uppercase ml-auto">
          {selectedTtsProvider}
        </span>
      </div>

      {/* Version picker */}
      <VersionPicker
        versions={versions}
        value={selectedVersion}
        onChange={onVersionChange}
      />

      {/* Provider + Language */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block mb-1">Provider</label>
          <select
            value={selectedTtsProvider}
            onChange={(e) => onChangeTtsProvider(e.target.value)}
            className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
          >
            {ttsProviders.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} {p.free ? '(Free)' : ''}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block mb-1">Language</label>
          <select
            value={ttsLanguage}
            onChange={(e) => onChangeTtsLanguage(e.target.value)}
            className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
          >
            {availableTtsLanguages.map((lang) => (
              <option key={lang} value={lang}>
                {lang === 'vi' ? 'Vietnamese' : lang === 'en' ? 'English' : lang.toUpperCase()}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* API key warning for paid providers */}
      {providerInfo?.requires_key && !ttsApiKey && (
        <div className="bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs p-3 rounded-lg flex items-center gap-2">
          <span className="material-symbols-outlined text-sm">warning</span>
          <span>No API key configured for <strong>{selectedTtsProvider}</strong>.</span>
          <button
            onClick={() => navigate('/settings#apikeys')}
            className="ml-auto text-[10px] font-bold uppercase tracking-wider text-amber-300 hover:text-amber-200 flex items-center gap-1 whitespace-nowrap"
          >
            <span className="material-symbols-outlined text-xs">settings</span>
            Configure
          </button>
        </div>
      )}

      {/* ElevenLabs: Voice ID input */}
      {selectedTtsProvider === 'elevenlabs' && (
        <div className="space-y-2">
          <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block">Voice ID</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={voiceIdInput}
              onChange={(e) => onChangeVoiceIdInput(e.target.value)}
              placeholder="Paste ElevenLabs voice ID"
              className="flex-1 bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-1 focus:ring-primary placeholder:text-zinc-600 font-mono"
            />
            <button
              onClick={onSaveVoiceId}
              disabled={!voiceIdInput}
              className="px-3 py-2 rounded text-[10px] font-bold uppercase bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-50 transition-colors"
            >
              {voiceIdSaved ? 'Saved' : 'Save'}
            </button>
          </div>
        </div>
      )}

      {/* Other providers: voice dropdown */}
      {selectedTtsProvider !== 'elevenlabs' && (
        <div className="space-y-1">
          <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block">Voice</label>
          <select
            value={selectedVoiceId}
            onChange={(e) => {
              const v = e.target.value;
              onChangeSelectedVoiceId(v);
              storageSet(`tts_voice_id_${selectedTtsProvider}`, v);
            }}
            className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
          >
            {ttsVoices.length === 0 && <option value="">Loading voices...</option>}
            {ttsVoices.map((v) => (
              <option key={v.name} value={v.name}>
                {v.friendly_name || v.name} ({v.gender}) — {v.language}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Dub playback speed */}
      <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-surface-container-highest">
        <span className="material-symbols-outlined text-sm text-on-surface-variant">speed</span>
        <label className="text-xs text-on-surface-variant flex-1">
          Dub playback speed
        </label>
        <input
          type="number"
          min={1.0}
          max={2.0}
          step={0.1}
          value={playbackSpeed}
          onChange={(e) => {
            const v = parseFloat(e.target.value);
            if (Number.isFinite(v) && v >= 1.0 && v <= 2.0) {
              onChangePlaybackSpeed(v);
              storageSet('tts_playback_speed', String(v));
            }
          }}
          className="w-16 px-2 py-1 text-xs font-mono text-on-surface bg-surface-container-low border border-outline-variant/30 rounded focus:outline-none focus:border-primary"
        />
        <span className="text-[10px] text-on-surface-variant font-mono">×</span>
      </div>

      {/* Shorten-to-fit toggle */}
      <div className="px-3 py-3 rounded-lg border border-outline-variant/15">
        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={enableShortening}
            onChange={(e) => onChangeEnableShortening(e.target.checked)}
            className="mt-0.5 accent-primary"
          />
          <div className="flex-1">
            <div className="text-xs font-medium text-on-surface">
              Shorten dub to fit timeline
            </div>
            <div className="text-[10px] text-on-surface-variant mt-0.5 leading-snug">
              Uses the LLM to compress text when a sentence would overrun its
              time slot. Uncheck to keep the original translation — clips may
              overrun.
            </div>
          </div>
        </label>
      </div>

      {/* Original-language underlay */}
      <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-surface-container-highest">
        <span className="material-symbols-outlined text-sm text-on-surface-variant">graphic_eq</span>
        <label className="text-xs text-on-surface-variant flex-1">
          Original underlay
        </label>
        <select
          value={String(underlayDb)}
          onChange={(e) => {
            const v = parseFloat(e.target.value);
            onChangeUnderlayDb(v);
            storageSet('tts_underlay_db', String(v));
          }}
          className="px-2 py-1 text-xs font-mono text-on-surface bg-surface-container-low border border-outline-variant/30 rounded focus:outline-none focus:border-primary"
        >
          <option value="0">Off</option>
          <option value="-24">-24</option>
          <option value="-18">-18</option>
          <option value="-12">-12</option>
          <option value="-6">-6</option>
        </select>
        <span className="text-[10px] text-on-surface-variant font-mono">dB</span>
      </div>

      {/* Voice preview */}
      {selectedVoiceId && (
        <div className="flex items-center gap-3">
          <TTSPreview
            voice={selectedVoiceId}
            provider={selectedTtsProvider}
            speed="+0%"
            pitch="+0Hz"
            apiKey={ttsApiKey || undefined}
            playbackSpeed={playbackSpeed}
            underlayDb={underlayDb}
            sampleText={
              ttsLanguage === 'vi'
                ? 'Xin chào các bạn, hôm nay chúng ta sẽ nói về một chủ đề rất thú vị.'
                : 'Hello everyone, today we will talk about a very interesting topic.'
            }
          />
          <span className="font-mono text-[9px] text-on-surface-variant truncate">
            {selectedVoiceId}
          </span>
        </div>
      )}

      {/* Generate TTS button */}
      <button
        disabled={isGeneratingTts}
        onClick={onGenerate}
        className={`w-full py-2.5 rounded-md font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 transition-all ${
          ttsGenerated
            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20'
            : isGeneratingTts
              ? 'bg-surface-container-highest text-on-surface-variant cursor-wait'
              : 'bg-primary text-on-primary-fixed hover:brightness-110 active:scale-95'
        }`}
      >
        {isGeneratingTts ? (
          <>
            <span className="material-symbols-outlined animate-spin text-sm">progress_activity</span>
            {ttsProgress.message || 'Generating...'}
          </>
        ) : ttsGenerated ? (
          <>
            <span className="material-symbols-outlined text-sm">check_circle</span>
            TTS Generated — Regenerate
          </>
        ) : (
          <>
            <span className="material-symbols-outlined text-sm">record_voice_over</span>
            Generate TTS Audio
          </>
        )}
      </button>

      {/* TTS Progress */}
      {isGeneratingTts && (
        <div className="space-y-1.5">
          <div className="flex justify-between items-center">
            <span className="text-[10px] font-mono text-zinc-500 uppercase">{ttsProgress.message}</span>
            <span className="text-xs font-bold font-mono text-primary">{ttsProgress.pct}%</span>
          </div>
          <div className="w-full bg-surface-container-highest h-1.5 rounded-full overflow-hidden">
            <div
              className="bg-primary h-full transition-all duration-500 shadow-[0_0_8px_rgba(208,188,255,0.4)]"
              style={{ width: `${ttsProgress.pct}%` }}
            />
          </div>
        </div>
      )}

      {/* TTS audio library */}
      {ttsList.length > 0 && (
        <div className="space-y-2">
          <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">
            Generated Dubs ({ttsList.length})
          </label>
          <div className="space-y-1">
            {ttsList.map((entry) => {
              const isPlaying = playingFilename === entry.filename;
              const audioUrl = getTTSAudioUrl(videoId, entry.language, entry.filename);
              const ago = (() => {
                const diff = (Date.now() / 1000) - entry.created_at;
                if (diff < 60) return 'just now';
                if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
                if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
                return `${Math.floor(diff / 86400)}d ago`;
              })();
              const sizeMb = (entry.size / 1024 / 1024).toFixed(1);
              return (
                <div key={entry.filename} className="flex items-center gap-2 px-3 py-2 bg-surface-container-lowest rounded-lg group">
                  <button
                    onClick={() => {
                      if (isPlaying) {
                        document.querySelectorAll<HTMLAudioElement>('audio.tts-player').forEach(a => { a.pause(); a.currentTime = 0; });
                        setPlayingFilename(null);
                      } else {
                        document.querySelectorAll<HTMLAudioElement>('audio.tts-player').forEach(a => { a.pause(); a.currentTime = 0; });
                        setPlayingFilename(entry.filename);
                      }
                    }}
                    className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${isPlaying ? 'bg-primary text-on-primary-fixed' : 'bg-surface-container-high text-on-surface-variant hover:bg-primary/20'}`}
                  >
                    <span className="material-symbols-outlined text-sm">{isPlaying ? 'stop' : 'play_arrow'}</span>
                  </button>
                  <div className="flex-1 min-w-0 flex items-center gap-1.5 min-w-0">
                    {entry.version && (
                      <span className="shrink-0 bg-primary/15 text-primary text-[9px] font-semibold px-1.5 py-0.5 rounded">
                        {entry.version}
                      </span>
                    )}
                    <span className="text-[11px] font-semibold text-on-surface truncate">{entry.voice}</span>
                    <span className="text-[9px] text-zinc-500 shrink-0">{entry.provider} · {entry.language} · {sizeMb}MB</span>
                  </div>
                  <span className="text-[9px] font-mono text-zinc-600">{ago}</span>
                  <a
                    href={audioUrl}
                    download={entry.filename}
                    className="p-1 rounded hover:bg-primary/20 text-zinc-600 hover:text-primary transition-all"
                    title={`Download ${entry.filename}`}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <span className="material-symbols-outlined text-sm">download</span>
                  </a>
                  <button
                    onClick={async (e) => {
                      e.stopPropagation();
                      if (!confirm(`Delete dub "${entry.voice}"?`)) return;
                      try {
                        await deleteTTSAudio(videoId, entry.filename);
                        onReloadTtsList();
                      } catch { /* ignore */ }
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-500/20 text-zinc-600 hover:text-red-400 transition-all"
                    title="Delete dub"
                  >
                    <span className="material-symbols-outlined text-sm">delete</span>
                  </button>
                  {isPlaying && (
                    <audio
                      className="tts-player"
                      autoPlay
                      src={audioUrl}
                      onEnded={() => setPlayingFilename(null)}
                      style={{ display: 'none' }}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {ttsError && (
        <div className="bg-error/10 border border-error/30 text-error text-xs p-3 rounded-lg flex items-center gap-2">
          <span className="material-symbols-outlined text-sm">error</span>
          {ttsError}
        </div>
      )}

      {/* Save-as-default block */}
      <div className="flex items-center gap-2 pt-2 border-t border-outline-variant/10">
        <button
          onClick={handleSaveAsDefault}
          className="text-[10px] font-bold uppercase tracking-wider bg-surface-container-highest text-on-surface px-3 py-1.5 rounded hover:bg-surface-container-high transition-colors"
        >
          Save current as default
        </button>
        {savedDefault && (
          <span className="text-[10px] font-mono text-emerald-400">Saved.</span>
        )}
        <span className="text-[9px] text-on-surface-variant ml-auto">
          Defaults pre-fill new pipeline runs. Manage in <a href="/settings?category=tts" className="text-primary underline">Settings</a>.
        </span>
      </div>
    </div>
  );
}
