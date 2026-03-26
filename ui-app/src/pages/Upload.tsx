import { TopBar } from '../components/TopBar';

function UploadPage() {
  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar breadcrumb="Upload" />
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center space-y-3">
          <span className="material-symbols-outlined text-5xl text-zinc-700">cloud_upload</span>
          <h2 className="text-lg font-semibold text-on-surface-variant">Upload — Coming Soon</h2>
          <p className="text-xs text-zinc-500 max-w-xs">
            Platform uploaders for YouTube, TikTok, Facebook, and X will be available in a future update.
          </p>
        </div>
      </div>
    </div>
  );
}

export default UploadPage;
