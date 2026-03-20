"""Uvicorn entrypoint for the API server."""

from src.api import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
