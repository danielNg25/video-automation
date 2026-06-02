import { useState, useEffect, useCallback, useRef } from 'react';
import { TopBar } from '../components/TopBar';
import {
  getProfiles, getProfile, createProfile, createProfileWithStatus,
  updateProfile, deleteProfileApi,
} from '../api/client';
import type { TranslationProfileSummary, TranslationProfile } from '../api/types';
import { downloadProfileJson, validateProfileJson } from '../utils/profileJson';

const EMPTY_PROFILE: TranslationProfile = {
  name: '', description: '', target_language: 'vi', source_language: 'zh',
  style_guide: '', example_pairs: [],
};

function TranslationProfilesPage() {
  const [profiles, setProfiles] = useState<TranslationProfileSummary[]>([]);
  const [selectedName, setSelectedName] = useState('');
  const [profileDraft, setProfileDraft] = useState<TranslationProfile>({ ...EMPTY_PROFILE });
  const [isEditing, setIsEditing] = useState(false);
  const [isNew, setIsNew] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Import state. importError surfaces parse + validation + non-409 HTTP errors.
  // pendingImport holds the parsed profile while the user is in the rename form
  // (set when createProfileWithStatus returns 409).
  const [importError, setImportError] = useState('');
  const [pendingImport, setPendingImport] = useState<TranslationProfile | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadProfiles = useCallback(async () => {
    try {
      const p = await getProfiles();
      setProfiles(p);
    } catch {
      // API not available
    }
  }, []);

  useEffect(() => { loadProfiles(); }, [loadProfiles]);

  const handleSelect = async (name: string) => {
    setSelectedName(name);
    setError('');
    setSuccess('');
    try {
      const full = await getProfile(name);
      setProfileDraft(full);
      setIsEditing(false);
      setIsNew(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load profile');
    }
  };

  const handleNew = () => {
    setSelectedName('');
    setProfileDraft({ ...EMPTY_PROFILE });
    setIsEditing(true);
    setIsNew(true);
    setError('');
    setSuccess('');
  };

  const handleEdit = () => {
    setIsEditing(true);
    setIsNew(false);
    setError('');
    setSuccess('');
  };

  const handleSave = async () => {
    setError('');
    try {
      if (isNew) {
        await createProfile(profileDraft);
      } else {
        await updateProfile(selectedName, profileDraft);
      }
      setSuccess(isNew ? 'Profile created' : 'Profile updated');
      setIsEditing(false);
      setIsNew(false);
      setSelectedName(profileDraft.name);
      await loadProfiles();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save profile');
    }
  };

  const handleDelete = async (name: string) => {
    setError('');
    try {
      await deleteProfileApi(name);
      if (selectedName === name) {
        setSelectedName('');
        setProfileDraft({ ...EMPTY_PROFILE });
        setIsEditing(false);
      }
      await loadProfiles();
      setSuccess('Profile deleted');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete profile');
    }
  };

  const handleExport = async () => {
    if (!selectedName) return;
    setError('');
    try {
      const full = await getProfile(selectedName);
      downloadProfileJson(full);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to export profile');
    }
  };

  const handleImportFilePicked = (file: File) => {
    setImportError('');
    setError('');
    setSuccess('');

    const reader = new FileReader();
    reader.onload = async (evt) => {
      const text = evt.target?.result as string;

      let parsed: unknown;
      try {
        parsed = JSON.parse(text);
      } catch (e) {
        setImportError(`Invalid JSON: ${e instanceof Error ? e.message : String(e)}`);
        return;
      }

      const validated = validateProfileJson(parsed);
      if (!validated.ok) {
        setImportError(validated.reason);
        return;
      }

      await tryImport(validated.profile);
    };
    reader.onerror = () => {
      setImportError(`Could not read file: ${reader.error?.message ?? 'unknown error'}`);
    };
    reader.readAsText(file);
  };

  const tryImport = async (profile: TranslationProfile) => {
    const result = await createProfileWithStatus(profile);
    if (result.status === 201) {
      setSuccess(`Imported "${result.profile.name}"`);
      setPendingImport(null);
      setRenameValue('');
      await loadProfiles();
      return;
    }
    if (result.status === 409) {
      setPendingImport(profile);
      setRenameValue(`${profile.name}-imported`);
      setImportError('');
      return;
    }
    setImportError(result.message || `Import failed: HTTP ${result.status}`);
  };

  const handleRenameConfirm = async () => {
    if (!pendingImport) return;
    const next = renameValue.trim();
    if (!next) {
      setImportError('Name cannot be empty');
      return;
    }
    await tryImport({ ...pendingImport, name: next });
  };

  const handleRenameCancel = () => {
    setPendingImport(null);
    setRenameValue('');
    setImportError('');
  };

  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar breadcrumb="Translation Profiles" />

      <section className="flex-1 overflow-y-auto p-6">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 max-w-5xl">
          {/* Left: Profile List */}
          <div className="lg:col-span-4 space-y-3">
            <div className="flex justify-between items-center mb-2">
              <h2 className="text-xs font-bold uppercase tracking-widest">Profiles</h2>
              <div className="flex gap-3">
                <button
                  onClick={() => fileInputRef.current?.click()}
                  aria-label="Import"
                  className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline flex items-center gap-1"
                >
                  <span className="material-symbols-outlined text-sm" aria-hidden="true">upload</span>
                  Import
                </button>
                <button
                  onClick={handleNew}
                  className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline flex items-center gap-1"
                >
                  <span className="material-symbols-outlined text-sm" aria-hidden="true">add</span>
                  New
                </button>
              </div>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleImportFilePicked(file);
                e.target.value = ''; // allow re-selecting the same file
              }}
            />
            {importError && (
              <div className="bg-error/10 border border-error/30 text-error text-xs p-3 rounded-lg flex items-start gap-2">
                <span className="material-symbols-outlined text-sm">error</span>
                <span className="flex-1 break-words">{importError}</span>
                <button onClick={() => setImportError('')} aria-label="Dismiss import error">
                  <span className="material-symbols-outlined text-sm">close</span>
                </button>
              </div>
            )}
            {pendingImport && (
              <div className="bg-primary/5 border border-primary/30 rounded-lg p-3 space-y-2">
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider">
                  Name already exists. Pick a new name to import as:
                </p>
                <label className="block">
                  <span className="sr-only">Rename profile</span>
                  <input
                    type="text"
                    aria-label="Rename profile"
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-1 focus:ring-primary"
                  />
                </label>
                <div className="flex gap-2 justify-end">
                  <button
                    onClick={handleRenameCancel}
                    className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider hover:underline"
                  >
                    Cancel rename
                  </button>
                  <button
                    onClick={handleRenameConfirm}
                    className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline"
                  >
                    Confirm
                  </button>
                </div>
              </div>
            )}
            {profiles.length === 0 && (
              <p className="text-xs text-zinc-500">No profiles yet. Create one to get started.</p>
            )}
            {profiles.map((p) => (
              <div
                key={p.name}
                onClick={() => handleSelect(p.name)}
                className={`p-3 rounded-lg cursor-pointer transition-all border ${
                  selectedName === p.name
                    ? 'bg-primary/10 border-primary/30'
                    : 'bg-surface-container-low border-outline-variant/10 hover:border-primary/20'
                }`}
              >
                <div className="flex justify-between items-start">
                  <div>
                    <div className="text-xs font-bold">{p.name}</div>
                    <div className="text-[10px] text-zinc-500 mt-0.5">{p.description}</div>
                  </div>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-container-highest text-zinc-400 font-mono">
                    {p.target_language}
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* Right: Profile Editor / Viewer */}
          <div className="lg:col-span-8">
            {!selectedName && !isNew ? (
              <div className="bg-surface-container-low rounded-xl p-12 flex flex-col items-center justify-center text-center border border-outline-variant/10">
                <span className="material-symbols-outlined text-4xl text-zinc-700 mb-3">translate</span>
                <h3 className="text-sm font-bold text-on-surface-variant mb-1">Select a Profile</h3>
                <p className="text-xs text-zinc-500">Choose a profile from the list or create a new one</p>
              </div>
            ) : (
              <div className="bg-surface-container-low rounded-xl border border-outline-variant/10 overflow-hidden">
                <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center">
                  <h3 className="text-xs font-bold uppercase tracking-widest">
                    {isNew ? 'New Profile' : isEditing ? 'Edit Profile' : 'Profile Details'}
                  </h3>
                  <div className="flex gap-2">
                    {!isEditing && !isNew && (
                      <>
                        <button
                          onClick={handleEdit}
                          className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline"
                        >
                          Edit
                        </button>
                        <button
                          onClick={handleExport}
                          className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline"
                        >
                          Export
                        </button>
                        <button
                          onClick={() => handleDelete(selectedName)}
                          className="text-[10px] font-bold text-error uppercase tracking-wider hover:underline"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </div>

                <div className="p-5 space-y-4">
                  {/* Error / Success */}
                  {error && (
                    <div className="bg-error/10 border border-error/30 text-error text-xs p-3 rounded-lg flex items-center gap-2">
                      <span className="material-symbols-outlined text-sm">error</span>
                      {error}
                    </div>
                  )}
                  {success && (
                    <div className="bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs p-3 rounded-lg flex items-center gap-2">
                      <span className="material-symbols-outlined text-sm">check_circle</span>
                      {success}
                      <button onClick={() => setSuccess('')} className="ml-auto">
                        <span className="material-symbols-outlined text-sm">close</span>
                      </button>
                    </div>
                  )}

                  {/* Name + Target Language */}
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="text-[10px] text-zinc-500 uppercase block mb-1">Name</label>
                      {isEditing || isNew ? (
                        <input
                          className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-1 focus:ring-primary"
                          value={profileDraft.name}
                          onChange={(e) => setProfileDraft({ ...profileDraft, name: e.target.value })}
                          placeholder="my-profile-vi"
                        />
                      ) : (
                        <div className="text-xs font-medium py-2">{profileDraft.name}</div>
                      )}
                    </div>
                    <div>
                      <label className="text-[10px] text-zinc-500 uppercase block mb-1">Target Language</label>
                      {isEditing || isNew ? (
                        <select
                          className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
                          value={profileDraft.target_language}
                          onChange={(e) => setProfileDraft({ ...profileDraft, target_language: e.target.value })}
                        >
                          <option value="vi">Vietnamese</option>
                          <option value="en">English</option>
                          <option value="ko">Korean</option>
                          <option value="ja">Japanese</option>
                          <option value="es">Spanish</option>
                        </select>
                      ) : (
                        <div className="text-xs font-medium py-2">{profileDraft.target_language}</div>
                      )}
                    </div>
                  </div>

                  {/* Description */}
                  <div>
                    <label className="text-[10px] text-zinc-500 uppercase block mb-1">Description</label>
                    {isEditing || isNew ? (
                      <input
                        className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-1 focus:ring-primary"
                        value={profileDraft.description}
                        onChange={(e) => setProfileDraft({ ...profileDraft, description: e.target.value })}
                        placeholder="Short description of this translation style"
                      />
                    ) : (
                      <div className="text-xs text-on-surface-variant py-2">{profileDraft.description}</div>
                    )}
                  </div>

                  {/* Source Language */}
                  <div>
                    <label className="text-[10px] text-zinc-500 uppercase block mb-1">Source Language</label>
                    {isEditing || isNew ? (
                      <select
                        className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
                        value={profileDraft.source_language}
                        onChange={(e) => setProfileDraft({ ...profileDraft, source_language: e.target.value })}
                      >
                        <option value="zh">Chinese</option>
                        <option value="en">English</option>
                      </select>
                    ) : (
                      <div className="text-xs font-medium py-2">{profileDraft.source_language}</div>
                    )}
                  </div>

                  {/* Style Guide */}
                  <div>
                    <label className="text-[10px] text-zinc-500 uppercase block mb-1">Style Guide</label>
                    {isEditing || isNew ? (
                      <textarea
                        className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-1 focus:ring-primary h-32 resize-y"
                        value={profileDraft.style_guide}
                        onChange={(e) => setProfileDraft({ ...profileDraft, style_guide: e.target.value })}
                        placeholder="Describe the personality, tone, and rules for translation..."
                      />
                    ) : (
                      <div className="text-xs text-on-surface-variant py-2 whitespace-pre-wrap">{profileDraft.style_guide}</div>
                    )}
                  </div>

                  {/* Example Pairs */}
                  <div>
                    <div className="flex justify-between items-center mb-2">
                      <label className="text-[10px] text-zinc-500 uppercase">Example Pairs</label>
                      {(isEditing || isNew) && (
                        <button
                          onClick={() =>
                            setProfileDraft({
                              ...profileDraft,
                              example_pairs: [...profileDraft.example_pairs, { source: '', target: '' }],
                            })
                          }
                          className="text-[10px] text-primary font-bold uppercase hover:underline"
                        >
                          + Add
                        </button>
                      )}
                    </div>
                    {profileDraft.example_pairs.length === 0 && (
                      <p className="text-[10px] text-zinc-600">No example pairs</p>
                    )}
                    {profileDraft.example_pairs.map((pair, i) => (
                      <div key={i} className="flex gap-2 mb-2 items-center">
                        {isEditing || isNew ? (
                          <>
                            <input
                              className="flex-1 bg-surface-container-highest border-none text-xs text-on-surface py-1.5 px-2 rounded focus:ring-1 focus:ring-primary"
                              placeholder="Source text"
                              value={pair.source}
                              onChange={(e) => {
                                const pairs = [...profileDraft.example_pairs];
                                pairs[i] = { ...pairs[i], source: e.target.value };
                                setProfileDraft({ ...profileDraft, example_pairs: pairs });
                              }}
                            />
                            <span className="text-zinc-600 text-[10px]">→</span>
                            <input
                              className="flex-1 bg-surface-container-highest border-none text-xs text-on-surface py-1.5 px-2 rounded focus:ring-1 focus:ring-primary"
                              placeholder="Target text"
                              value={pair.target}
                              onChange={(e) => {
                                const pairs = [...profileDraft.example_pairs];
                                pairs[i] = { ...pairs[i], target: e.target.value };
                                setProfileDraft({ ...profileDraft, example_pairs: pairs });
                              }}
                            />
                            <button
                              onClick={() => {
                                const pairs = profileDraft.example_pairs.filter((_, j) => j !== i);
                                setProfileDraft({ ...profileDraft, example_pairs: pairs });
                              }}
                              className="text-zinc-500 hover:text-error"
                            >
                              <span className="material-symbols-outlined text-sm">close</span>
                            </button>
                          </>
                        ) : (
                          <>
                            <span className="flex-1 text-xs text-on-surface-variant">{pair.source}</span>
                            <span className="text-zinc-600 text-[10px]">→</span>
                            <span className="flex-1 text-xs text-on-surface-variant">{pair.target}</span>
                          </>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* Actions */}
                  {(isEditing || isNew) && (
                    <div className="flex justify-end gap-2 pt-2 border-t border-outline-variant/10">
                      <button
                        onClick={() => {
                          setIsEditing(false);
                          setIsNew(false);
                          if (!selectedName) setProfileDraft({ ...EMPTY_PROFILE });
                        }}
                        className="px-4 py-2 text-xs font-bold uppercase tracking-wider text-zinc-400 hover:text-on-surface"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleSave}
                        disabled={!profileDraft.name.trim()}
                        className="bg-primary text-on-primary-fixed px-4 py-2 rounded-md font-bold text-xs uppercase tracking-wider disabled:opacity-50"
                      >
                        {isNew ? 'Create' : 'Update'} Profile
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

export default TranslationProfilesPage;
