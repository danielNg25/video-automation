import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import TranslationProfilesPage from '../TranslationProfiles';

const SAMPLE_PROFILES = [
  { name: 'demo-vi', description: 'A demo profile', target_language: 'vi' },
];

const SAMPLE_FULL = {
  name: 'demo-vi',
  description: 'A demo profile',
  target_language: 'vi',
  source_language: 'zh',
  style_guide: 'Be casual.',
  example_pairs: [{ source: 'hi', target: 'chào' }],
};

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>(
    '../../api/client',
  );
  return {
    ...actual,
    getProfiles: vi.fn(),
    getProfile: vi.fn(),
    createProfile: vi.fn(),
    createProfileWithStatus: vi.fn(),
    updateProfile: vi.fn(),
    deleteProfileApi: vi.fn(),
  };
});

vi.mock('../../components/TopBar', () => ({
  TopBar: ({ breadcrumb }: { breadcrumb: string }) => <div>{breadcrumb}</div>,
}));

vi.mock('../../utils/profileJson', async () => {
  const actual = await vi.importActual<typeof import('../../utils/profileJson')>(
    '../../utils/profileJson',
  );
  return {
    ...actual,
    downloadProfileJson: vi.fn(),
  };
});

beforeEach(async () => {
  const api = await import('../../api/client');
  vi.mocked(api.getProfiles).mockResolvedValue(SAMPLE_PROFILES);
  vi.mocked(api.getProfile).mockResolvedValue(SAMPLE_FULL);
});

afterEach(() => {
  vi.clearAllMocks();
});

async function selectDemoProfile() {
  fireEvent.click(await screen.findByText('demo-vi'));
  // Wait for getProfile to populate the right pane (the "Edit" button
  // only renders once a non-editing profile is loaded).
  await screen.findByRole('button', { name: /^edit$/i });
}

describe('TranslationProfiles — Export', () => {
  it('Export button is hidden until a profile is selected', () => {
    render(<TranslationProfilesPage />);
    expect(screen.queryByRole('button', { name: /^export$/i })).not.toBeInTheDocument();
  });

  it('Export click fetches the full profile then triggers download', async () => {
    const api = await import('../../api/client');
    const fileUtils = await import('../../utils/profileJson');
    render(<TranslationProfilesPage />);
    await selectDemoProfile();

    fireEvent.click(screen.getByRole('button', { name: /^export$/i }));

    await waitFor(() => {
      expect(fileUtils.downloadProfileJson).toHaveBeenCalledWith(SAMPLE_FULL);
    });
    // Confirm getProfile was called (cached from the select, but the
    // export path is allowed to re-fetch — verify the download payload
    // matches the loaded body).
    expect(api.getProfile).toHaveBeenCalled();
  });
});

describe('TranslationProfiles — Import', () => {
  function pickFile(contents: string, filename = 'profile.json'): void {
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error('file input not found');
    const file = new File([contents], filename, { type: 'application/json' });
    fireEvent.change(input, { target: { files: [file] } });
  }

  it('Import button opens the hidden file input', () => {
    render(<TranslationProfilesPage />);
    const importBtn = screen.getByRole('button', { name: /^import$/i });
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error('file input not found');
    const clickSpy = vi.spyOn(input, 'click');
    fireEvent.click(importBtn);
    expect(clickSpy).toHaveBeenCalled();
  });

  it('invalid JSON shows inline error, no POST attempted', async () => {
    const api = await import('../../api/client');
    render(<TranslationProfilesPage />);

    pickFile('{not valid json');

    expect(await screen.findByText(/invalid json/i)).toBeInTheDocument();
    expect(api.createProfileWithStatus).not.toHaveBeenCalled();
  });

  it('missing-field JSON shows inline error, no POST attempted', async () => {
    const api = await import('../../api/client');
    render(<TranslationProfilesPage />);
    const incomplete = { ...SAMPLE_FULL };
    delete (incomplete as Partial<typeof SAMPLE_FULL>).style_guide;

    pickFile(JSON.stringify(incomplete));

    expect(await screen.findByText(/style_guide/i)).toBeInTheDocument();
    expect(api.createProfileWithStatus).not.toHaveBeenCalled();
  });

  it('happy path: POST returns 201, list refreshes', async () => {
    const api = await import('../../api/client');
    vi.mocked(api.createProfileWithStatus).mockResolvedValue({
      status: 201,
      profile: { ...SAMPLE_FULL, name: 'fresh-vi' },
    });
    vi.mocked(api.getProfiles).mockResolvedValueOnce(SAMPLE_PROFILES).mockResolvedValueOnce([
      ...SAMPLE_PROFILES,
      { name: 'fresh-vi', description: 'A demo profile', target_language: 'vi' },
    ]);
    render(<TranslationProfilesPage />);

    pickFile(JSON.stringify({ ...SAMPLE_FULL, name: 'fresh-vi' }));

    await waitFor(() => {
      expect(api.createProfileWithStatus).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'fresh-vi' }),
      );
    });
    // Second getProfiles call (the post-import refresh) brings 'fresh-vi'
    // into the list.
    expect(await screen.findByText('fresh-vi')).toBeInTheDocument();
  });

  it('409 shows the rename form with default suffix', async () => {
    const api = await import('../../api/client');
    vi.mocked(api.createProfileWithStatus).mockResolvedValue({
      status: 409,
      message: "Profile 'demo-vi' already exists",
    });
    render(<TranslationProfilesPage />);

    pickFile(JSON.stringify(SAMPLE_FULL));

    const input = await screen.findByLabelText(/rename/i) as HTMLInputElement;
    expect(input.value).toBe('demo-vi-imported');
  });

  it('rename Confirm re-posts with the new name', async () => {
    const api = await import('../../api/client');
    vi.mocked(api.createProfileWithStatus)
      .mockResolvedValueOnce({ status: 409, message: 'exists' })
      .mockResolvedValueOnce({
        status: 201,
        profile: { ...SAMPLE_FULL, name: 'my-rename' },
      });
    render(<TranslationProfilesPage />);

    pickFile(JSON.stringify(SAMPLE_FULL));

    const input = await screen.findByLabelText(/rename/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'my-rename' } });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => {
      expect(api.createProfileWithStatus).toHaveBeenCalledTimes(2);
    });
    expect(api.createProfileWithStatus).toHaveBeenLastCalledWith(
      expect.objectContaining({ name: 'my-rename' }),
    );
  });

  it('rename Cancel clears the import buffer', async () => {
    const api = await import('../../api/client');
    vi.mocked(api.createProfileWithStatus).mockResolvedValue({
      status: 409,
      message: 'exists',
    });
    render(<TranslationProfilesPage />);

    pickFile(JSON.stringify(SAMPLE_FULL));

    await screen.findByLabelText(/rename/i);
    fireEvent.click(screen.getByRole('button', { name: /^cancel rename$/i }));

    await waitFor(() => {
      expect(screen.queryByLabelText(/rename/i)).not.toBeInTheDocument();
    });
  });
});
