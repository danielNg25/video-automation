export interface NavItem {
  readonly icon: string;
  readonly label: string;
  readonly path: string;
}

export const navItems: readonly NavItem[] = [
  { icon: 'dashboard', label: 'Dashboard', path: '/' },
  { icon: 'download', label: 'Download & Transcribe', path: '/download' },
  { icon: 'movie_edit', label: 'Subtitle & Process', path: '/process' },
  { icon: 'upload', label: 'Upload', path: '/upload' },
  { icon: 'settings', label: 'Settings', path: '/settings' },
];

export interface SubtitleSegment {
  readonly id: number;
  readonly startTime: string;
  readonly endTime: string;
  readonly text: string;
  readonly translation?: string;
}

export const srtSegments: readonly SubtitleSegment[] = [
  { id: 1, startTime: '00:00:01,240', endTime: '00:00:04,500', text: '你好，欢迎来到东京。今天我们要探索的是新宿区的独特魅力。' },
  { id: 2, startTime: '00:00:04,500', endTime: '00:00:08,120', text: 'Hello and welcome to Tokyo. Today we\'re exploring the unique charm of Shinjuku.' },
  { id: 3, startTime: '00:00:08,120', endTime: '00:00:12,800', text: '这里的霓虹灯光在雨后显得格外迷人，充满了赛博朋克的氛围。' },
  { id: 4, startTime: '00:00:12,800', endTime: '00:00:15,340', text: 'The neon lights here are particularly enchanting after rain, filled with a cyberpunk vibe.' },
  { id: 5, startTime: '00:00:15,340', endTime: '00:00:19,200', text: '我们将深入这些小巷，寻找那些被隐藏的视觉宝藏。' },
];

export interface RecentDownload {
  readonly id: string;
  readonly filename: string;
  readonly size: string;
  readonly status: 'success' | 'transcribing' | 'failed';
}

export const recentDownloads: readonly RecentDownload[] = [
  { id: '1', filename: 'douyin_v_9122.mp4', size: '12.4 MB', status: 'success' },
  { id: '2', filename: 'tutorial_01_remix.mp4', size: '156.2 MB', status: 'transcribing' },
  { id: '3', filename: 'unknown_stream_f9.m3u8', size: '0.0 KB', status: 'failed' },
];

export interface PipelineRow {
  readonly id: string;
  readonly title: string;
  readonly subId: string;
  readonly stages: readonly ('done' | 'active' | 'pending' | 'failed')[];
  readonly platformIcons: readonly string[];
  readonly started: string;
}

export const pipelineRows: readonly PipelineRow[] = [
  { id: '1', title: 'Product_Demo_Final_v2.mp4', subId: 'ID: 8219-AX', stages: ['done', 'done', 'active', 'pending'], platformIcons: ['movie', 'cloud_upload'], started: '2m ago' },
  { id: '2', title: 'Tutorial_Stream_Rec.ts', subId: 'Status: Connection Timed Out', stages: ['failed', 'pending', 'pending', 'pending'], platformIcons: ['smart_display'], started: '14m ago' },
  { id: '3', title: 'Marketing_Short_A.mp4', subId: 'ID: 9022-KL', stages: ['done', 'done', 'done', 'done'], platformIcons: ['share', 'public'], started: '42m ago' },
];

export interface ActivityEvent {
  readonly time: string;
  readonly level: 'info' | 'success' | 'error' | 'neutral';
  readonly label: string;
  readonly message: string;
}

export const activityFeed: readonly ActivityEvent[] = [
  { time: '14:22:01', level: 'info', label: 'TRANSCODER:', message: 'FFmpeg process initialized for VID-992' },
  { time: '14:19:45', level: 'success', label: 'UPLOADER:', message: 'Dispatch successful to S3_PRIMARY_BUCKET' },
  { time: '14:15:22', level: 'error', label: 'CRITICAL:', message: 'API limit reached for Whisper V3. Rotating keys...' },
  { time: '14:10:05', level: 'neutral', label: '', message: 'System check completed. All nodes operational.' },
];

export interface PlatformAuth {
  readonly id: string;
  readonly name: string;
  readonly icon: string;
  readonly iconBg: string;
  readonly iconColor: string;
  readonly connected: boolean;
  readonly account?: string;
}

export const platformAuths: readonly PlatformAuth[] = [
  { id: 'youtube', name: 'YouTube', icon: 'video_library', iconBg: 'bg-red-900/20', iconColor: 'text-red-500', connected: true, account: '@videopro' },
  { id: 'tiktok', name: 'TikTok', icon: 'music_video', iconBg: 'bg-zinc-900', iconColor: 'text-zinc-100', connected: true, account: 'prod_main' },
  { id: 'facebook', name: 'Facebook', icon: 'groups', iconBg: 'bg-blue-900/20', iconColor: 'text-blue-400', connected: false },
  { id: 'x', name: 'X / Twitter', icon: 'close', iconBg: 'bg-zinc-800', iconColor: 'text-zinc-100', connected: false },
];

export interface PlatformOption {
  readonly id: string;
  readonly name: string;
  readonly badge: string;
  readonly description: string;
  readonly checked: boolean;
}

export const platformOptions: readonly PlatformOption[] = [
  { id: 'tiktok', name: 'TikTok', badge: '9:16', description: 'Max 10min / Vertical Burn-in', checked: true },
  { id: 'youtube', name: 'YouTube', badge: 'MAX 60s', description: 'Shorts optimization enabled', checked: true },
  { id: 'facebook', name: 'Facebook', badge: '15:00', description: 'Standard 16:9 Letterbox', checked: false },
  { id: 'x', name: 'X / Twitter', badge: '2:20', description: 'High-bitrate processing', checked: false },
];

export const fontOptions = ['Inter Display', 'JetBrains Mono', 'Roboto Condensed', 'Impact Heavy'] as const;

export const languageOptions = [
  { label: 'English (Auto)', checked: true },
  { label: 'Spanish (ES)', checked: false },
  { label: 'French (FR)', checked: false },
  { label: 'German (DE)', checked: false },
] as const;

export interface SettingsSection {
  readonly id: string;
  readonly icon: string;
  readonly label: string;
}

export const settingsSections: readonly SettingsSection[] = [
  { id: 'douyin', icon: 'api', label: 'Douyin API' },
  { id: 'transcription', icon: 'description', label: 'Transcription' },
  { id: 'video', icon: 'movie_filter', label: 'Video Processing' },
  { id: 'platforms', icon: 'hub', label: 'Platforms' },
  { id: 'pipeline', icon: 'account_tree', label: 'Pipeline' },
];
