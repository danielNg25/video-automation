# UI Design Prompt

Use this prompt with a general-purpose LLM (ChatGPT, Claude, etc.) to generate UI designs for the Douyin Video Repurposing Pipeline.

---

## The Prompt

```
Design a complete web UI for a "Douyin Video Repurposing Pipeline" — a tool that downloads Douyin (Chinese TikTok) videos, generates AI subtitles, burns subtitles into the video, and uploads to YouTube, TikTok, Facebook, and X/Twitter.

The UI uses React + Tailwind CSS + shadcn/ui. It's a local desktop tool (not public-facing), so prioritize usability and information density over marketing aesthetics. Use a clean, dark-mode-first design with a sidebar navigation.

Design these 5 pages with detailed layouts, component choices, and interactions:

---

### PAGE 1: Download & Transcribe

Purpose: Paste a Douyin URL, download the video, then transcribe it to subtitles.

Layout:
- Top section: Large URL input field with a "Download" button. Should accept messy share text (the backend extracts the URL). Show a subtle hint: "Paste Douyin share link or URL"
- Middle section: When downloading, show a progress bar with speed + ETA (e.g., "2.3 MB / 5.1 MB — 1.2 MB/s"). Show the fallback indicator if yt-dlp kicks in ("Douyin API failed, using yt-dlp fallback")
- After download: Show a video card with:
  - Video thumbnail (left)
  - Metadata (right): title, author, duration, resolution, file size
  - "Transcribe" button with a dropdown for language: Chinese (default), or Chinese + English translation
- Transcription progress: Indeterminate progress bar with stage text ("Loading model...", "Transcribing...", "Generating SRT...")
- After transcription: SRT preview panel — scrollable list of subtitle segments, each showing:
  - Timestamp range (e.g., "00:01:23 → 00:01:27")
  - Chinese text
  - English translation below (if generated), in a lighter color
- Bottom: "Recent Downloads" section showing a compact list/grid of previously downloaded videos with status badges (Downloaded / Transcribed / Processed)

Key interactions:
- Download button shows loading spinner while active
- Progress updates in real-time via SSE (Server-Sent Events)
- Clicking a recent video card expands to show its SRT preview
- Error states: red banner with error message + "Retry" button

---

### PAGE 2: Subtitle & Process

Purpose: Configure subtitle styling, select target platforms, and process videos with burned-in subtitles.

Layout:
- Left panel (40%): Subtitle Style Editor
  - Font selector (dropdown: "Noto Sans CJK SC", "PingFang SC", etc.)
  - Font size slider (16–36px)
  - Color pickers: text color (default white), outline color (default black)
  - Outline width slider (0–4px)
  - Shadow toggle + depth
  - Position selector: bottom-center (default), top-center, middle
  - Vertical margin slider (20–100px)
  - Bold toggle
  - Live preview: a dark rectangle simulating a video frame with sample subtitle text rendered using the current style settings (CSS approximation)

- Right panel (60%): Processing Controls
  - Video selector: dropdown or card list of videos that have SRT files
  - Subtitle language for burn-in: Chinese only / English only / Dual-line (Chinese + English)
  - Platform selector: checkboxes for each platform, each showing constraints as badges:
    - ☑ TikTok — "9:16 · max 10min · 4GB"
    - ☑ YouTube — "9:16 · max 60s (Shorts) · English subs"
    - ☑ Facebook — "9:16 · max 15min · 4GB"
    - ☐ X/Twitter — "9:16 · max 2:20 · 512MB" (grayed out if disabled in config)
  - "Process" button
  - Processing progress: separate progress bar per platform, showing percentage parsed from ffmpeg output. Only one active at a time, others queued.
  - After processing: video player per platform output. Tabs for each platform, HTML5 video player showing the result.

Key interactions:
- Style changes update the live preview instantly
- Platform checkboxes are disabled if the video doesn't meet constraints (e.g., too long for YouTube Shorts)
- Processing is sequential per platform; UI shows which is active vs queued vs done
- "Process" button disabled until at least one platform selected

---

### PAGE 3: Upload

Purpose: Connect platform accounts, configure metadata, and upload processed videos.

Layout:
- Top: Auth Status Bar — horizontal row of platform cards:
  - Each card shows: platform icon, platform name, connection status (green dot = connected, red = disconnected)
  - Connected: shows account name/email, "Disconnect" link
  - Disconnected: "Connect" button that opens OAuth popup
  - Disabled platforms (from config): grayed out card with "Disabled in settings" text

- Middle: Upload Form
  - Video selector: dropdown of processed videos (only those with platform outputs)
  - Platform checkboxes: only platforms that are both connected AND have processed output
  - Per-platform metadata editor (tabs or accordion):
    - Title field with character counter (YouTube: 100 max, X: 280 max)
    - Description textarea with counter
    - Tags/hashtags input (pill-style tag input)
    - Privacy selector: Public / Private / Unlisted (YouTube), Draft (TikTok)
    - Pre-filled from video metadata with platform-specific formatting
  - "Upload to Selected Platforms" button

- Bottom: Upload Progress + Results
  - Per-platform progress cards showing stages:
    - "Authenticating..." → "Uploading (45%)" → "Processing on platform..." → "Complete ✓" / "Failed ✗"
  - After completion: result cards with:
    - Platform icon + name
    - Success: clickable post URL, thumbnail if available
    - Failed: error message + "Retry" button
  - Summary line: "3/4 platforms succeeded"

Key interactions:
- OAuth flow opens in popup, returns to app on completion
- Upload progress updates via SSE
- Retry button only re-uploads to failed platforms
- Character counters turn red when exceeding limits

---

### PAGE 4: Dashboard

Purpose: Overview of all pipeline activity, batch processing, and quick actions.

Layout:
- Top: Stats Row — 4 metric cards in a horizontal row:
  - "Total Videos" (all-time count)
  - "Processed Today" (today's count)
  - "Success Rate" (percentage with small trend indicator)
  - "Active Tasks" (currently running, with spinning indicator if > 0)

- Middle-left (60%): Pipeline Table
  - Sortable, filterable table with columns:
    - Video: thumbnail + title (truncated)
    - Status: multi-stage indicator showing 4 dots/steps (Download → Transcribe → Process → Upload), colored: green (done), blue (active), gray (pending), red (failed)
    - Platforms: small icons for each target platform
    - Started: relative time ("2 min ago")
    - Duration: total time
    - Actions: "View" button, "Retry" button (for failed)
  - Filter tabs above table: All / Running / Completed / Failed
  - Expandable row detail: shows per-stage timing, error messages, output file links

- Middle-right (40%): Quick Actions
  - "Quick Process" card: URL input + platform checkboxes + "Go" button (runs full pipeline)
  - "Batch Process" card: textarea for multiple URLs (one per line), platform selector, concurrency slider (1-5), "Process All" button
  - Active batch progress: shows "Processing 3/10 videos..." with overall progress bar

- Bottom: Recent Activity Feed
  - Compact timeline of events: "Video 7xxx downloaded", "Video 7xxx uploaded to YouTube", "Video 7xxx failed on TikTok: rate limit"
  - Auto-scrolls, max 20 entries

Key interactions:
- Pipeline table auto-refreshes via SSE
- Clicking "View" opens a slide-out panel with full video details
- Batch processing shows per-video progress rows as they start
- Failed items have one-click retry

---

### PAGE 5: Settings

Purpose: Configure all pipeline settings without editing YAML files.

Layout:
- Sidebar sections (vertical tabs on left):
  - Douyin API
  - Transcription
  - Video Processing
  - Platforms
  - Pipeline

- Douyin API section:
  - API Base URL (text input, default "http://localhost:8081")
  - Cookie file path (text input + file picker)
  - Download timeout (number input, seconds)
  - Docker status indicator: green "Running" / red "Stopped" with "Start Container" button

- Transcription section:
  - Model size selector: dropdown (tiny / base / small / medium / large-v3)
  - Device: dropdown (auto / cpu / cuda / mps)
  - Compute type: dropdown (float16 / int8 / float32)
  - Default language: dropdown (zh / en)
  - VAD filter toggle + min silence duration slider
  - Model download status: "Downloaded ✓" or "Not downloaded — Download Now" button

- Video Processing section:
  - Default CRF slider (18–28, show quality label)
  - Preset: dropdown (ultrafast → slow)
  - Audio bitrate: dropdown (96k / 128k / 192k / 256k)

- Platforms section:
  - One card per platform (YouTube, TikTok, Facebook, X)
  - Each card: Enable/Disable toggle, connection status, platform-specific settings
  - YouTube: default privacy, default category
  - TikTok: post mode (direct / draft)
  - Facebook: post type (reels / feed), page ID
  - X: note about $100/mo requirement

- Pipeline section:
  - Data directory path
  - Max concurrent tasks slider (1–10)
  - Retry attempts (1–5)
  - Retry base delay (seconds)
  - Skip existing toggle

- Bottom sticky bar: "Save Changes" button (disabled until changes made) + "Reset to Defaults" link

Key interactions:
- Changes are validated before saving (e.g., API URL must be valid)
- Save button sends PUT to /api/config
- Docker status checks on page load
- Model download shows progress

---

### GLOBAL LAYOUT

- Sidebar navigation (left, collapsible):
  - Logo/app name at top: "Douyin Pipeline" with a play-button icon
  - Nav items with icons:
    - 📥 Download & Transcribe
    - 🎬 Subtitle & Process
    - 📤 Upload
    - 📊 Dashboard
    - ⚙️ Settings
  - Active item highlighted with accent color
  - Collapsed mode: icons only

- Color scheme (dark mode):
  - Background: zinc-950 (#09090b)
  - Card/surface: zinc-900 (#18181b)
  - Border: zinc-800 (#27272a)
  - Primary accent: violet-500 (#8b5cf6)
  - Success: emerald-500
  - Error: red-500
  - Warning: amber-500
  - Text primary: zinc-50
  - Text secondary: zinc-400

- Typography:
  - Font: Inter (body) + JetBrains Mono (code/timestamps)
  - Headings: semibold, tracking-tight
  - Body: regular, text-sm (14px)

- Component library: shadcn/ui components throughout:
  - Card, Button, Input, Select, Slider, Switch, Progress, Badge, Table, Tabs, Dialog, Popover, Tooltip

Please generate detailed mockups or wireframes for each page, showing the exact component layout, spacing, and visual hierarchy. Include both empty states and active states (with data).
```
