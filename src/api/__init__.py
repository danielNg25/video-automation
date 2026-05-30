"""FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.deps import get_data_dir, get_task_manager
from src.api.routers import (
    download,
    editor,
    events,
    pipeline,
    settings,
    tasks,
    transcribe,
    translate,
    tts,
)
from src.api.routers import (
    versions as versions_router,
)

UI_DIST = Path("ui-app/dist")


def create_app() -> FastAPI:
    app = FastAPI(title="Douyin Pipeline API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    app.include_router(download.router)
    app.include_router(transcribe.router)
    app.include_router(translate.router)
    app.include_router(editor.router)
    app.include_router(settings.router)
    app.include_router(pipeline.router)
    app.include_router(tts.router)
    app.include_router(events.router)
    app.include_router(tasks.router)
    app.include_router(versions_router.router)

    # Mount static dirs BEFORE the SPA catch-all so concrete paths win.
    data_dir = get_data_dir()
    app.mount("/files/raw", StaticFiles(directory=str(data_dir / "raw")), name="raw_videos")
    app.mount("/files/srt", StaticFiles(directory=str(data_dir / "srt")), name="srt_files")
    app.mount(
        "/files/output", StaticFiles(directory=str(data_dir / "output")), name="output_videos"
    )
    app.mount(
        "/files/proxy", StaticFiles(directory=str(data_dir / "proxy")), name="proxy_videos"
    )
    app.mount("/files/tts", StaticFiles(directory=str(data_dir / "tts")), name="tts_audio")

    if (UI_DIST / "index.html").exists():
        assets_dir = UI_DIST / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="ui_assets")

        @app.get("/", include_in_schema=False)
        async def spa_root():
            return FileResponse(UI_DIST / "index.html")

        # Reserved server-side prefixes — return 404 instead of the SPA so
        # typo'd API/files paths surface as real errors during debugging.
        _RESERVED = ("api/", "files/", "assets/", "docs", "openapi.json", "redoc")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if full_path.startswith(_RESERVED):
                raise HTTPException(status_code=404)
            candidate = UI_DIST / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(UI_DIST / "index.html")

    @app.on_event("startup")
    async def startup():
        tm = get_task_manager()
        await tm.scan_existing_videos()

    return app
