"""Pydantic request/response models for the API."""

from __future__ import annotations

from pydantic import BaseModel

# --- Requests ---


class DownloadRequest(BaseModel):
    url: str


class BatchDownloadRequest(BaseModel):
    urls: list[str]
    concurrency: int = 3


class TranscribeRequest(BaseModel):
    video_id: str
    language: str = "zh"
    task: str = "transcribe"
    ocr_region: dict | None = None  # Optional manual override: {"x", "y", "w", "h"}
    ocr_config: dict | None = None  # Optional OCR settings override from UI


class UpdateVideoRequest(BaseModel):
    title: str


class TranslateRequest(BaseModel):
    video_id: str
    profile_name: str = "funny-casual-vi"
    source_language: str = "zh"
    backend: str | None = None    # override config: "anthropic" | "openai"
    model: str | None = None      # override config: model ID
    api_key: str | None = None    # override config: API key
    base_url: str | None = None   # override config: custom API base URL (for local models)


class TranslationProfileCreate(BaseModel):
    name: str
    description: str
    target_language: str
    source_language: str = "zh"
    style_guide: str
    example_pairs: list[dict] = []


class PipelineRequest(BaseModel):
    url: str
    translate_profile: str | None = None
    source_language: str = "zh"


class FullPipelineRequest(BaseModel):
    url: str
    platforms: list[str] = ["youtube", "tiktok"]
    auto_upload: bool = False
    translate_profile: str | None = None
    translation_override: dict | None = None  # {backend, model, api_key, base_url}
    source_language: str = "zh"
    force: bool = False
    metadata: dict | None = None
    blur_enabled: bool = False  # blur original subtitles before burn-in
    # TTS dub fields. tts_voice is the trigger — when set, the pipeline runs
    # the dub stage; otherwise it skips. Provider defaults to 'google', and
    # language defaults to 'vi'. Mirror of TTSRequest so the pipeline and
    # per-video flows produce identical output.
    tts_provider: str = "google"
    tts_voice: str | None = None
    tts_language: str = "vi"
    tts_api_key: str | None = None  # ElevenLabs/OpenAI/Google API key
    tts_model: str | None = None  # Gemini model ID; ignored by other providers
    llm_api_key: str | None = None  # for the TTS-shortening LLM
    llm_backend: str | None = None  # deepseek, openai, anthropic
    playback_speed: float | None = None  # fixed dub playback speed
    # Underlay level (dB) for the original-language audio mixed under the dub.
    # 0 disables the underlay entirely. When None, the runner falls back to
    # config.yaml then the assembler default (-12 dB).
    underlay_db: float | None = None
    # ASS style overrides merged with per-platform styles in the processor.
    # E.g. {"background_color": "&H80000000", "background_opacity": 128} for a
    # semi-transparent black background behind subtitles.
    subtitle_style: dict | None = None
    # Per-request OCR crop override. When None, the pipeline uses the global
    # `ocr.crop_bottom_pct` from config.yaml; when set (0.0 = full frame, 0.25
    # = bottom quarter, etc.), it overrides for this run only.
    ocr_crop_bottom_pct: float | None = None


class BatchPipelineRequest(BaseModel):
    urls: list[str]
    platforms: list[str] = ["youtube", "tiktok"]
    concurrency: int = 3
    translate_profile: str | None = None
    translation_override: dict | None = None  # {backend, model, api_key, base_url}
    source_language: str = "zh"
    force: bool = False
    blur_enabled: bool = False  # blur original subtitles before burn-in
    # TTS dub fields — same shape as FullPipelineRequest.
    tts_provider: str = "google"
    tts_voice: str | None = None
    tts_language: str = "vi"
    tts_api_key: str | None = None
    tts_model: str | None = None  # Gemini model ID; ignored by other providers
    llm_api_key: str | None = None
    llm_backend: str | None = None
    playback_speed: float | None = None
    # Underlay level (dB) for the original-language audio mixed under the dub.
    # 0 disables the underlay entirely. When None, the runner falls back to
    # config.yaml then the assembler default (-12 dB).
    underlay_db: float | None = None
    # ASS style overrides merged with per-platform styles in the processor.
    # E.g. {"background_color": "&H80000000", "background_opacity": 128} for a
    # semi-transparent black background behind subtitles.
    subtitle_style: dict | None = None
    # Per-batch OCR crop override (applies to every URL in the batch).
    # See FullPipelineRequest.ocr_crop_bottom_pct for semantics.
    ocr_crop_bottom_pct: float | None = None


class PipelineHistoryEntry(BaseModel):
    video_id: str
    url: str = ""
    status: str = "unknown"
    current_stage: str = ""
    progress: float = 0.0
    message: str = ""
    completed_stages: list[str] = []
    stage_results: dict = {}
    timestamps: dict = {}
    platforms: list[str] = []
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""


class ProcessRequest(BaseModel):
    video_id: str
    platforms: list[str]
    subtitle_style: dict | None = None
    subtitle_language_overrides: dict[str, str] | None = None  # {platform: lang_code}
    enable_tts: bool = False
    tts_mix_settings: dict[str, dict] | None = None  # {platform: {original_volume, tts_volume}}
    blur_settings: BlurSettings | None = None  # Phase 6: blur original subs
    manual_region: SubtitleRegionResponse | None = None  # Phase 6: manual region override


class ExportRequest(BaseModel):
    subtitle_language: str | None = None  # which SRT to burn, None = no subs
    tts_file: str | None = None  # specific TTS filename to mix in
    video_volume: float = 1.0  # 0.0-2.0
    tts_volume: float = 1.0  # 0.0-2.0
    # When None/empty, export at the source video's native resolution — no
    # scale, no letterbox pad. Pass an explicit "WxH" to scale to that size
    # (kept for callers that need a hard target like 1080x1920).
    resolution: str | None = None


class SaveSrtRequest(BaseModel):
    language: str
    segments: list[SubtitleSegment]
    version: str = "draft"


class PreviewFrameRequest(BaseModel):
    language: str = "en"
    timestamp: float = 0.0
    subtitle_style: dict | None = None


class PreviewClipRequest(BaseModel):
    language: str = "en"
    start: float = 0.0
    duration: float = 10.0
    subtitle_style: dict | None = None


# --- Responses ---


class TaskResponse(BaseModel):
    task_id: str
    status: str


class VideoResponse(BaseModel):
    video_id: str
    title: str = ""
    author: str = ""
    duration: float = 0.0
    resolution: str = ""
    size: str = ""
    codec: str = ""
    description: str = ""
    hashtags: list[str] = []
    source_url: str = ""
    file_path: str = ""
    thumbnail: str = ""
    has_srt: bool = False
    srt_languages: list[str] = []
    status: str = "downloaded"


class VideoListResponse(BaseModel):
    videos: list[VideoResponse]
    total: int


class SubtitleSegment(BaseModel):
    id: int
    startTime: str
    endTime: str
    text: str
    translation: str | None = None


class SrtResponse(BaseModel):
    video_id: str
    segments: list[SubtitleSegment]
    language: str
    is_dubsync: bool = False


class ProcessResult(BaseModel):
    video_id: str
    outputs: dict[str, str] = {}
    subtitle_languages: dict[str, str] = {}


class TranslationProfileResponse(BaseModel):
    name: str
    description: str
    target_language: str
    source_language: str
    style_guide: str
    example_pairs: list[dict]


class TranslationProfileSummary(BaseModel):
    name: str
    description: str
    target_language: str


class TTSRequest(BaseModel):
    video_id: str
    language: str = "vi"
    provider: str = "google"  # google | elevenlabs | openai | gemini (FE picks)
    model: str | None = None  # Gemini model ID; ignored by other providers
    voice: str                # provider's voice ID (e.g. "vi-VN-Wavenet-A"); required
    api_key: str | None = None  # per-request API key for paid providers
    llm_api_key: str | None = None  # API key for LLM text shortening
    llm_backend: str | None = None  # deepseek, openai, anthropic
    # Fixed dub playback speed (atempo target). Every sentence plays at
    # exactly this speed (uniform pacing). When None, the assembler default
    # (1.5×) is used.
    playback_speed: float | None = None
    version: str = "draft"
    enable_shortening: bool = True



class TTSPreviewRequest(BaseModel):
    text: str
    voice: str = "vi-VN-HoaiMyNeural"
    provider: str = "google"
    model: str | None = None  # Gemini model ID; ignored by other providers
    # Apply atempo at this speed to the previewed sample so the user can
    # hear what the dub will sound like at their chosen playback speed.
    playback_speed: float = 1.0
    speed: str = "+0%"
    pitch: str = "+0Hz"
    api_key: str | None = None  # per-request API key for paid providers


class VoiceInfo(BaseModel):
    name: str
    language: str
    gender: str
    provider: str
    friendly_name: str = ""


class TTSResult(BaseModel):
    video_id: str
    language: str
    audio_path: str
    duration: float = 0.0
    segment_count: int = 0


class DashboardStats(BaseModel):
    totalVideos: int
    processedToday: int
    successRate: float
    activeTasks: int


# --- Subtitle Replacement (Phase 6) ---


class SubtitleRegionResponse(BaseModel):
    x: int
    y: int
    width: int
    height: int
    confidence: float = 1.0
    video_width: int = 0
    video_height: int = 0


class BlurSettings(BaseModel):
    enabled: bool = True
    strength: int = 15
    mode: str = "blur"  # "blur" | "fill" | "pixelate"
    fill_color: str = "#000000"


class SubtitleReplacementRequest(BaseModel):
    video_id: str
    language: str = "en"
    blur_settings: BlurSettings = BlurSettings()
    manual_region: SubtitleRegionResponse | None = None
    auto_match_style: bool = True


class PreviewBlurRequest(BaseModel):
    timestamp: float = 5.0
    blur_settings: BlurSettings = BlurSettings()
    region: SubtitleRegionResponse | None = None  # None = use auto-detected
