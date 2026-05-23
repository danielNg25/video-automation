import { useEffect, useState } from 'react';
import { getCookieStatus, getConfig, putCookie, testCookie } from '../../api/client';
import type { CookieStatus, CookieTestResult } from '../../api/client';

export function DouyinSection() {
  const [cookie, setCookie] = useState<CookieStatus | null>(null);
  const [cookieInput, setCookieInput] = useState('');
  const [cookieSaving, setCookieSaving] = useState(false);
  const [cookieTesting, setCookieTesting] = useState(false);
  const [cookieTestResult, setCookieTestResult] = useState<CookieTestResult | null>(null);
  const [cookieSaveMsg, setCookieSaveMsg] = useState('');
  const [serviceUrl, setServiceUrl] = useState<string>('');

  useEffect(() => {
    getCookieStatus().then(setCookie).catch(() => {});
    getConfig().then((cfg) => {
      const d = (cfg.douyin || {}) as Record<string, unknown>;
      if (d.api_base) setServiceUrl(String(d.api_base));
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!cookieSaveMsg) return;
    const t = setTimeout(() => setCookieSaveMsg(''), 3000);
    return () => clearTimeout(t);
  }, [cookieSaveMsg]);

  const handleCookieSave = async () => {
    setCookieSaving(true);
    setCookieSaveMsg('');
    try {
      const updated = await putCookie(cookieInput);
      setCookie(updated);
      setCookieInput('');
      setCookieSaveMsg('Saved');
      setCookieTestResult(null);
    } catch (e: unknown) {
      setCookieSaveMsg(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setCookieSaving(false);
    }
  };

  const handleCookieTest = async () => {
    setCookieTesting(true);
    setCookieTestResult(null);
    try {
      const result = await testCookie();
      setCookieTestResult(result);
    } catch (e: unknown) {
      setCookieTestResult({ success: false, message: e instanceof Error ? e.message : 'Test failed' });
    } finally {
      setCookieTesting(false);
    }
  };

  return (
    <section className="space-y-6" id="douyin">
      <div className="border-b border-zinc-800/30 pb-4">
        <h2 className="text-xl font-semibold text-on-surface">Douyin API</h2>
        <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">Cookie and service configuration.</p>
      </div>

      {/* Service URL */}
      <div className="space-y-2">
        <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Service URL</label>
        <div className="w-full bg-surface-container-lowest border border-outline-variant/10 rounded p-3 text-sm font-mono text-on-surface-variant flex items-center justify-between">
          <span>{serviceUrl || 'Not configured'}</span>
          <span className="text-[10px] text-zinc-500">configured in config/config.yaml</span>
        </div>
      </div>

      {/* Cookie Management */}
      <div className="bg-surface-container-low p-5 rounded-lg space-y-4">
        {/* Status header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-xs font-bold uppercase tracking-widest text-zinc-500">Cookie</span>
            {cookie?.exists ? (
              <span className="text-[10px] font-mono bg-emerald-900/30 text-emerald-400 px-2 py-0.5 rounded">
                ACTIVE ({cookie.length} chars)
              </span>
            ) : (
              <span className="text-[10px] font-mono bg-red-900/30 text-red-400 px-2 py-0.5 rounded">
                {cookie === null ? 'LOADING...' : 'MISSING'}
              </span>
            )}
          </div>
          {cookie?.preview && (
            <span className="text-xs font-mono text-zinc-500">{cookie.preview}</span>
          )}
        </div>

        {/* File path */}
        {cookie?.file_path && (
          <p className="text-[10px] font-mono text-zinc-600">{cookie.file_path}</p>
        )}

        {/* Paste new cookie */}
        <textarea
          className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono resize-none text-on-surface"
          rows={3}
          placeholder="Paste new cookie string here..."
          value={cookieInput}
          onChange={(e) => setCookieInput(e.target.value)}
        />

        {/* Action buttons */}
        <div className="flex items-center gap-3">
          <button
            disabled={!cookieInput.trim() || cookieSaving}
            onClick={handleCookieSave}
            className="px-5 py-2.5 bg-primary text-on-primary-fixed text-xs font-bold uppercase tracking-widest rounded disabled:opacity-40 transition-all"
          >
            {cookieSaving ? 'Saving...' : 'Save Cookie'}
          </button>
          <button
            disabled={!cookie?.exists || cookieTesting}
            onClick={handleCookieTest}
            className="px-5 py-2.5 bg-surface-container-high hover:bg-surface-variant text-xs font-bold uppercase tracking-widest rounded disabled:opacity-40 transition-colors"
          >
            {cookieTesting ? 'Testing...' : 'Test Cookie'}
          </button>
          {cookieSaveMsg && (
            <span className={`text-xs font-mono ${cookieSaveMsg.toLowerCase().startsWith('save failed') || cookieSaveMsg.toLowerCase().includes('error') ? 'text-red-400' : 'text-emerald-400'}`}>
              {cookieSaveMsg}
            </span>
          )}
        </div>

        {/* Test result */}
        {cookieTestResult && (
          <div className={`flex items-center gap-2 text-xs font-mono ${cookieTestResult.success ? 'text-emerald-400' : 'text-red-400'}`}>
            <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>
              {cookieTestResult.success ? 'check_circle' : 'error'}
            </span>
            {cookieTestResult.message}
          </div>
        )}
      </div>
    </section>
  );
}
