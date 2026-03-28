import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './components/Layout';
import { lazy, Suspense } from 'react';

const DashboardPage = lazy(() => import('./pages/Dashboard'));
const DownloadTranscribePage = lazy(() => import('./pages/DownloadTranscribe'));
const UploadPage = lazy(() => import('./pages/Upload'));
const SettingsPage = lazy(() => import('./pages/Settings'));
const SubtitleEditorPage = lazy(() => import('./pages/SubtitleEditor'));
const TranslationProfilesPage = lazy(() => import('./pages/TranslationProfiles'));
const VideoListPage = lazy(() => import('./pages/VideoList'));
const VideoDetailPage = lazy(() => import('./pages/VideoDetail'));

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
      <Suspense fallback={<LoadingFallback />}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="/download" element={<DownloadTranscribePage />} />
            <Route path="/videos" element={<VideoListPage />} />
            <Route path="/videos/:videoId" element={<VideoDetailPage />} />
            <Route path="/editor/:videoId" element={<SubtitleEditorPage />} />
            <Route path="/profiles" element={<TranslationProfilesPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

export default App;
