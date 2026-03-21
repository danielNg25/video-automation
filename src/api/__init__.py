"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.deps import get_data_dir, get_task_manager
from src.api.routers import download, editor, events, process, transcribe


def create_app() -> FastAPI:
    app = FastAPI(title="Douyin Pipeline API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(download.router)
    app.include_router(transcribe.router)
    app.include_router(process.router)
    app.include_router(editor.router)
    app.include_router(events.router)

    @app.on_event("startup")
    async def startup():
        data_dir = get_data_dir()
        app.mount("/files/raw", StaticFiles(directory=str(data_dir / "raw")), name="raw_videos")
        app.mount("/files/srt", StaticFiles(directory=str(data_dir / "srt")), name="srt_files")
        app.mount(
            "/files/output",
            StaticFiles(directory=str(data_dir / "output")),
            name="output_videos",
        )

        tm = get_task_manager()
        await tm.scan_existing_videos()

    return app
