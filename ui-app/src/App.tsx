import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { lazy, Suspense } from 'react';
import { PipelineStatusProvider } from './lib/pipelineStatus';

const DownloadTranscribePage = lazy(() => import('./pages/DownloadTranscribe'));
const SettingsPage = lazy(() => import('./pages/Settings'));
const TranslationProfilesPage = lazy(() => import('./pages/TranslationProfiles'));
const VideoListPage = lazy(() => import('./pages/VideoList'));
const VideoDetailPage = lazy(() => import('./pages/VideoDetail'));
const DubStudioPageLazy = lazy(() =>
  import('./pages/DubStudio').then((m) => ({ default: m.DubStudioPage }))
);

function LoadingFallback() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="w-8 h-8 rounded-full border-2 border-primary border-t-transparent animate-spin" />
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <PipelineStatusProvider>
        <Suspense fallback={<LoadingFallback />}>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<DownloadTranscribePage />} />
              <Route path="/download" element={<Navigate to="/" replace />} />
              <Route path="/videos" element={<VideoListPage />} />
              <Route path="/videos/:videoId" element={<VideoDetailPage />} />
              <Route path="/dub-studio" element={<DubStudioPageLazy />} />
              <Route path="/profiles" element={<TranslationProfilesPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
          </Routes>
        </Suspense>
      </PipelineStatusProvider>
    </BrowserRouter>
  );
}

export default App;
