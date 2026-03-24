"""Pydantic request/response models for the API."""

from __future__ import annotations

from pydantic import BaseModel

# --- Requests ---


class DownloadRequest(BaseModel):
    url: str


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


class ProcessRequest(BaseModel):
    video_id: str
    platforms: list[str]
    subtitle_style: dict | None = None
    subtitle_language_overrides: dict[str, str] | None = None  # {platform: lang_code}
    enable_tts: bool = False
    tts_mix_settings: dict[str, dict] | None = None  # {platform: {original_volume, tts_volume}}


class SaveSrtRequest(BaseModel):
    language: str
    segments: list[SubtitleSegment]


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
    voice_profile: str = "female-vi-natural"
    provider: str | None = None  # override default provider
    voice: str | None = None  # direct voice ID (overrides profile voice)
    api_key: str | None = None  # per-request API key for paid providers


class TTSPreviewRequest(BaseModel):
    text: str
    voice: str = "vi-VN-HoaiMyNeural"
    provider: str = "edge"
    speed: str = "+0%"
    pitch: str = "+0Hz"
    api_key: str | None = None  # per-request API key for paid providers


class VoiceInfo(BaseModel):
    name: str
    language: str
    gender: str
    provider: str
    friendly_name: str = ""


class VoiceProfileConfig(BaseModel):
    provider: str = "edge"
    voice: str
    language: str
    speed: str = "+0%"
    pitch: str = "+0Hz"


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
