"""Pydantic request/response models for the API."""

from pydantic import BaseModel

# --- Requests ---


class DownloadRequest(BaseModel):
    url: str


class TranscribeRequest(BaseModel):
    video_id: str
    language: str = "zh"
    task: str = "transcribe"


class UpdateVideoRequest(BaseModel):
    title: str


class ProcessRequest(BaseModel):
    video_id: str
    platforms: list[str]
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


class DashboardStats(BaseModel):
    totalVideos: int
    processedToday: int
    successRate: float
    activeTasks: int
