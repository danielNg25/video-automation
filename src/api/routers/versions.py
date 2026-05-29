"""Subtitle versions CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api import versions as versions_mod

router = APIRouter()


class CreateVersionRequest(BaseModel):
    name: str | None = None


class RenameVersionRequest(BaseModel):
    name: str | None


@router.get(
    "/api/videos/{video_id}/versions",
    response_model=list[versions_mod.VersionEntry],
)
async def list_versions(video_id: str, language: str):
    versions_mod.ensure_migrated(video_id, language)
    return versions_mod.load_versions(video_id, language)


@router.post(
    "/api/videos/{video_id}/versions",
    response_model=versions_mod.VersionEntry,
    status_code=201,
)
async def create_version(
    video_id: str, language: str, request: CreateVersionRequest
):
    versions_mod.ensure_migrated(video_id, language)
    try:
        return versions_mod.snapshot_working_draft(
            video_id, language, request.name
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch(
    "/api/videos/{video_id}/versions/{version_id}",
    response_model=versions_mod.VersionEntry,
)
async def rename_version(
    video_id: str,
    language: str,
    version_id: str,
    request: RenameVersionRequest,
):
    versions_mod.ensure_migrated(video_id, language)
    entries = versions_mod.load_versions(video_id, language)
    found = next((e for e in entries if e.id == version_id), None)
    if found is None:
        raise HTTPException(
            status_code=404,
            detail=f"Version {version_id} not found",
        )
    found.name = request.name
    versions_mod.save_versions(video_id, language, entries)
    return found


@router.delete(
    "/api/videos/{video_id}/versions/{version_id}",
    status_code=204,
)
async def delete_version(
    video_id: str, language: str, version_id: str
):
    versions_mod.ensure_migrated(video_id, language)
    deleted = versions_mod.delete_version(video_id, language, version_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Version {version_id} not found",
        )
    return None
