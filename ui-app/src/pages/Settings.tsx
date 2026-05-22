import { useSearchParams } from 'react-router-dom';
import { TopBar } from '../components/TopBar';
import { DouyinSection } from './settings/DouyinSection';
import { ApiKeysSection } from './settings/ApiKeysSection';
import { OcrSection } from './settings/OcrSection';
import { TtsSection } from './settings/TtsSection';
import { VideoExportSection } from './settings/VideoExportSection';
import { PipelineSection } from './settings/PipelineSection';

type CategoryId = 'douyin' | 'apikeys' | 'ocr' | 'translation' | 'tts' | 'video' | 'pipeline';

const categoryGroups: { group: string; items: { id: CategoryId; icon: string; label: string }[] }[] = [
  {
    group: 'SOURCES',
    items: [
      { id: 'douyin', icon: 'api', label: 'Douyin API' },
      { id: 'apikeys', icon: 'key', label: 'API Keys' },
    ],
  },
  {
    group: 'PROCESSING',
    items: [
      { id: 'ocr', icon: 'document_scanner', label: 'Subtitles (OCR)' },
      { id: 'translation', icon: 'translate', label: 'Translation' },
      { id: 'tts', icon: 'record_voice_over', label: 'Dubbing (TTS)' },
      { id: 'video', icon: 'movie_filter', label: 'Export & Video' },
    ],
  },
  {
    group: 'SYSTEM',
    items: [
      { id: 'pipeline', icon: 'account_tree', label: 'Pipeline' },
    ],
  },
];

function TranslationPlaceholder() {
  return (
    <div className="bg-surface-container-low rounded-xl p-6 text-center text-on-surface-variant">
      <p className="text-sm">Translation defaults — coming in Task 11.</p>
      <p className="text-xs mt-2">Manage translation style profiles on the <a href="/profiles" className="text-primary underline">Translation Profiles</a> page.</p>
    </div>
  );
}

function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeCategory = (searchParams.get('category') as CategoryId) || 'douyin';
  const setActiveCategory = (id: CategoryId) =>
    setSearchParams(
      (p) => {
        p.set('category', id);
        return p;
      },
      { replace: true },
    );

  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar breadcrumb="Settings" />

      {/* Settings Workspace */}
      <div className="flex flex-1 overflow-hidden">
        {/* Settings Sidebar (Sub-nav) */}
        <nav className="w-56 bg-surface-container-lowest flex flex-col p-2 gap-2 border-r border-zinc-800/10 overflow-y-auto">
          {categoryGroups.map((g) => (
            <div key={g.group} className="space-y-0.5">
              <div className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 px-3 pt-2 pb-1">{g.group}</div>
              {g.items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setActiveCategory(item.id)}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded text-sm font-medium transition-colors text-left ${
                    activeCategory === item.id
                      ? 'bg-surface-container-high text-primary'
                      : 'text-zinc-400 hover:bg-surface-container-low'
                  }`}
                >
                  <span className="material-symbols-outlined text-[18px]">{item.icon}</span>
                  {item.label}
                </button>
              ))}
            </div>
          ))}
        </nav>

        {/* Settings Content */}
        <div className="flex-1 overflow-y-auto p-8">
          <div className="max-w-3xl mx-auto pb-12">
            {activeCategory === 'douyin' && <DouyinSection />}
            {activeCategory === 'apikeys' && <ApiKeysSection />}
            {activeCategory === 'ocr' && <OcrSection />}
            {activeCategory === 'translation' && <TranslationPlaceholder />}
            {activeCategory === 'tts' && <TtsSection />}
            {activeCategory === 'video' && <VideoExportSection />}
            {activeCategory === 'pipeline' && <PipelineSection />}
          </div>
        </div>
      </div>
    </div>
  );
}

export default SettingsPage;
