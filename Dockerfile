# syntax=docker/dockerfile:1.6

FROM node:20-alpine AS ui-builder
WORKDIR /build
COPY ui-app/package.json ui-app/package-lock.json ./
RUN npm ci
COPY ui-app/ ./
# Run vite directly instead of `npm run build` (which also runs `tsc -b`).
# Type-checking belongs in CI / the dev loop, not in the container build —
# the image must ship regardless of in-progress TypeScript refactors.
RUN npx vite build

FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libass9 \
        fontconfig \
        fonts-dejavu \
        fonts-noto-cjk \
        libgl1 \
        libglib2.0-0 \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps from pyproject.toml first, with a stub src package so
# setuptools' editable install succeeds without invalidating this layer on
# every code change. The real src/ is copied after — editable mode picks it up.
COPY pyproject.toml ./
RUN mkdir -p src && touch src/__init__.py
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e ".[linux]" "faster-whisper>=1.1.0"

COPY src/ ./src/
COPY scripts/ ./scripts/

COPY --from=ui-builder /build/dist ./ui-app/dist

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
