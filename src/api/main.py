"""Uvicorn entrypoint for the API server."""

from src.api import create_app

app = create_app()

if __name__ == "__main__":
    import os

    import uvicorn

    # Default to loopback so the API isn't exposed on all interfaces. Set
    # HOST=0.0.0.0 explicitly (behind a trusted proxy / auth) for remote use.
    uvicorn.run(
        "src.api.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=True,
    )
