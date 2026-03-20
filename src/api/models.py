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


class DashboardStats(BaseModel):
    totalVideos: int
    processedToday: int
    successRate: float
    activeTasks: int
