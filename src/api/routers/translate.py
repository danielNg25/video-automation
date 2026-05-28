"""Translation and profile management endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from src.api.deps import get_config, get_task_manager
from src.api.models import (
    TaskResponse,
    TranslateRequest,
    TranslationProfileCreate,
    TranslationProfileResponse,
    TranslationProfileSummary,
)
from src.translator.profiles import (
    TranslationProfile,
    delete_profile,
    list_profiles,
    load_profile,
    save_profile,
)

router = APIRouter()


# --- Translation ---


@router.post("/api/translate", response_model=TaskResponse)
async def start_translate(request: TranslateRequest):
    tm = get_task_manager()
    config = get_config()

    if request.video_id not in tm.video_index:
        raise HTTPException(status_code=404, detail=f"Video {request.video_id} not found")

    # Verify profile exists
    try:
        load_profile(request.profile_name)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Profile '{request.profile_name}' not found"
        )

    # Apply overrides to config copy
    effective_config = dict(config)
    if request.backend or request.model or request.api_key or request.base_url:
        trans_cfg = dict(effective_config.get("translation", {}))
        if request.backend:
            trans_cfg["backend"] = request.backend
        if request.model:
            trans_cfg["model"] = request.model
        if request.api_key:
            trans_cfg["api_key"] = request.api_key
        if request.base_url:
            trans_cfg["base_url"] = request.base_url
        effective_config["translation"] = trans_cfg

    task = tm.create_task("translate")
    task._asyncio_task = asyncio.create_task(
        tm.run_translate(
            task.task_id,
            request.video_id,
            request.profile_name,
            request.source_language,
            effective_config,
        )
    )
    return TaskResponse(task_id=task.task_id, status=task.status)


# --- Profile CRUD ---


@router.get("/api/profiles", response_model=list[TranslationProfileSummary])
async def get_profiles():
    names = list_profiles()
    result = []
    for name in names:
        try:
            p = load_profile(name)
            result.append(
                TranslationProfileSummary(
                    name=p.name,
                    description=p.description,
                    target_language=p.target_language,
                )
            )
        except Exception:
            continue
    return result


@router.get("/api/profiles/{name}", response_model=TranslationProfileResponse)
async def get_profile(name: str):
    try:
        p = load_profile(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

    return TranslationProfileResponse(
        name=p.name,
        description=p.description,
        target_language=p.target_language,
        source_language=p.source_language,
        style_guide=p.style_guide,
        example_pairs=p.example_pairs,
    )


@router.post("/api/profiles", response_model=TranslationProfileResponse, status_code=201)
async def create_profile(req: TranslationProfileCreate):
    # Check for existing
    if req.name in list_profiles():
        raise HTTPException(status_code=409, detail=f"Profile '{req.name}' already exists")

    profile = TranslationProfile(
        name=req.name,
        description=req.description,
        target_language=req.target_language,
        source_language=req.source_language,
        style_guide=req.style_guide,
        example_pairs=req.example_pairs,
    )
    save_profile(profile)

    return TranslationProfileResponse(
        name=profile.name,
        description=profile.description,
        target_language=profile.target_language,
        source_language=profile.source_language,
        style_guide=profile.style_guide,
        example_pairs=profile.example_pairs,
    )


@router.put("/api/profiles/{name}", response_model=TranslationProfileResponse)
async def update_profile(name: str, req: TranslationProfileCreate):
    if name not in list_profiles():
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

    # If renaming, delete old
    if req.name != name:
        try:
            delete_profile(name)
        except FileNotFoundError:
            pass

    profile = TranslationProfile(
        name=req.name,
        description=req.description,
        target_language=req.target_language,
        source_language=req.source_language,
        style_guide=req.style_guide,
        example_pairs=req.example_pairs,
    )
    save_profile(profile)

    return TranslationProfileResponse(
        name=profile.name,
        description=profile.description,
        target_language=profile.target_language,
        source_language=profile.source_language,
        style_guide=profile.style_guide,
        example_pairs=profile.example_pairs,
    )


@router.delete("/api/profiles/{name}", status_code=204)
async def remove_profile(name: str):
    try:
        delete_profile(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
