# Docker Operations Guide

Run, troubleshoot, and maintain this project under Docker. Read this once before your first run.

---

## 1. Prerequisites

| OS | What you need |
|---|---|
| macOS (Intel or Apple Silicon) | Docker Desktop 4.30+ |
| Linux | Docker Engine 24+ with the `docker compose` plugin |
| Windows 10/11 | Docker Desktop with the WSL 2 backend |

Verify:

```bash
docker --version
docker compose version
```

You also need ~4 GB of free disk for the built image plus headroom for `data/` (videos, audio, models).

---

## 2. First-run setup

Three steps. Almost everything else is configured later in the Settings UI.

```bash
# 2.1  App config (ffmpeg, OCR, transcription, etc.) — edit later in the UI.
cp config/config.example.yaml config/config.yaml

# 2.2  Helper-API cookie — REQUIRED. The douyin-api container needs a real
# Douyin Cookie header to scrape Douyin. Copy this template and paste your
# cookie into the `Cookie:` field:
#   https://github.com/Evil0ctal/Douyin_TikTok_Download_API/blob/main/crawlers/douyin/web/config.yaml
# Save it as config/douyin_web_config.yaml. (Gitignored — it's personal.)
#   To get the cookie: log into https://www.douyin.com in a browser,
#   open DevTools → Application → Cookies → copy the full Cookie header.
ls config/douyin_web_config.yaml          # must exist before `docker compose up`

# 2.3  Build and start.
docker compose up -d --build
```

Open <http://localhost:8000> and finish configuration in the **Settings** page:

- **Douyin API** → paste your Douyin user cookie (separate from 2.2 — this is for the app's downloader, not the helper container)
- **API Keys** → Anthropic / DeepSeek / OpenAI / ElevenLabs / Google (whichever backend you want)
- **Transcription / OCR / Video / Pipeline** → tweak as needed

API keys live in your browser only and are sent with each translate / TTS request — they never leave your machine and aren't stored on the server.

---

## 3. URLs and ports

| URL | What |
|---|---|
| <http://localhost:8000> | Web UI (Dashboard, Subtitle Editor, Video Studio) |
| <http://localhost:8000/api/health> | Health check — returns `{"status":"ok"}` |
| <http://localhost:8000/docs> | FastAPI Swagger UI |
| <http://localhost:8081> | Internal Douyin helper API (you usually don't open this) |

If 8000 or 8081 is already in use, change the host port in `docker-compose.yml` (left side of `"8000:8000"`).

---

## 4. Daily commands

```bash
docker compose up -d            # start (uses existing image)
docker compose up -d --build    # rebuild then start (after code changes)
docker compose restart app      # restart without rebuild (after config edits)
docker compose ps               # status of both containers
docker compose logs -f app      # tail backend logs
docker compose logs -f douyin-api
docker compose down             # stop and remove containers (volumes survive)
docker compose down -v          # ALSO wipe any compose volumes
```

Make targets: `make docker-up`, `make docker-down`, `make docker-build`, `make docker-rebuild`, `make docker-logs`.

### When to rebuild vs restart

| You changed... | Action |
|---|---|
| `src/`, `ui-app/`, `Dockerfile`, `pyproject.toml` | `docker compose up -d --build app` |
| `config/*.yaml` or files under `data/` | `docker compose restart app` (or just refresh — most config is hot-read) |
| `docker-compose.yml` | `docker compose up -d` |

`--build` reuses pip and npm caches across rebuilds, so most rebuilds are 30–90 s, not the full first-run time.

---

## 5. What's persisted, what isn't

Mounts in `docker-compose.yml`:

| Path | Type | Purpose |
|---|---|---|
| `./data` ↔ `/app/data` | Bind mount | All pipeline outputs (raw videos, SRT, TTS audio, exports, logs, state) |
| `./config` ↔ `/app/config` | Bind mount | Live-edit config without rebuilding |

Everything else inside the container is ephemeral. RapidOCR ships its ONNX models bundled inside the python package — no download at runtime, no model cache volume.

**Cleanup tip** — if you upgraded from a previous PaddleOCR build, the old `paddleocr_cache` volume is now orphaned (~170 MB). Reclaim it once:

```bash
docker volume rm douyin-automation_paddleocr_cache
```

---

## 6. Apple Silicon notes

`docker-compose.yml` pins the app to `platform: linux/amd64`. OnnxRuntime ships aarch64 wheels, but Rosetta amd64 is the better-tested path on the current image — the OCR speedup work was validated on amd64.

To try native arm64: comment the `platform: linux/amd64` line, run `docker compose build --no-cache app && docker compose up -d`. Revert if OCR misbehaves.

---

## 7. GPU acceleration (Linux / Windows with NVIDIA)

The OCR engine (RapidOCR / ONNX Runtime) auto-detects available execution providers at startup. CPU is the bundled fallback. For NVIDIA-CUDA:

1. Install with the `[gpu]` extra: `pip install -e ".[gpu]"` (this pulls `onnxruntime-gpu`). In the Dockerfile that means switching the install command for GPU images — or doing it manually inside a running container for ad-hoc tests.
2. Run docker with GPU passthrough: `docker compose run --gpus all ...` or add `gpus: all` to the compose service (Docker Engine + NVIDIA Container Toolkit must already be set up on the host).
3. Optionally pin the provider in `config/config.yaml` under `ocr:`: `execution_provider: cuda`. The default `auto` already picks CUDA when it's available.

Apple Silicon Docker can't pass through the M-series GPU, so Macs run CPU-only. Frame-diff skipping is what makes that path acceptable on a Mac.

---

## 8. Linux file-permission gotcha

The container runs as root, so files written into bind-mounted `./data` and `./config` are owned by **root** on the host. Invisible on macOS / Windows Docker Desktop; on Linux you'll hit "permission denied" trying to edit/delete those files from the host.

Workaround: `sudo chown -R $USER data/ config/` after each container run, or add a `USER ${UID}:${GID}` directive to the Dockerfile and rebuild (not done by default to keep cross-platform behavior consistent).

---

## 9. Troubleshooting

### Blank page at <http://localhost:8000>; logs show 404 for `/assets/index-*.js`

Stale image. Run `docker compose up -d --build app`.

### `docker compose up` fails with `no such file or directory: ./config/douyin_web_config.yaml`

Step 2.2 wasn't completed. Create the file with a real Douyin cookie.

### Backend logs `Connection refused` to the Douyin helper

`config/config.yaml` line 2 must be:

```yaml
douyin:
  api_base: '${DOUYIN_API_BASE:-http://localhost:8081}'
```

Inside the container, `localhost` is the container itself — it can't reach the helper that way. Compose sets `DOUYIN_API_BASE=http://douyin-api:80`, and the interpolation picks it up.

### Translation fails with auth / 401

You haven't entered an API key in **Settings → API Keys** yet. Open the UI and add one.

### OCR seems slower than the speedup notes promise

Check the assembler logs for the line `OCR streaming: N engine calls, M frame-diff skips (X% skip rate)`. If `skip rate` is below ~50% on a video with steady subtitles, raise `frame_diff_threshold` in `config/config.yaml` under `ocr:` (try 5–10). If skip rate is high but per-OCR time is still slow, you're CPU-bound — see Section 7 for the GPU path.

### `make api` on the host can't reach the Douyin helper

Bare-metal expects the helper at `http://localhost:8081`. The `${DOUYIN_API_BASE:-...}` default handles this as long as `DOUYIN_API_BASE` is unset in your shell. If you exported it for Docker testing, `unset DOUYIN_API_BASE` before running `make api`.

### Build is slow

The Dockerfile uses BuildKit cache mounts. Make sure BuildKit is on:

```bash
export DOCKER_BUILDKIT=1
docker compose build app
```

Docker Desktop has BuildKit enabled by default.

### Port 8000 already in use

Edit `docker-compose.yml`, change `"8000:8000"` to `"8001:8000"` (or any free host port). Open <http://localhost:8001>.

---

## 10. Upgrading

```bash
git pull
docker compose up -d --build
```

The `data/` bind mount survives image rebuilds (RapidOCR models are bundled in the python package — no model cache to worry about). If a release notes a config schema change, re-diff `config/config.example.yaml` against your `config/config.yaml`.

---

## 11. Clean slate

```bash
docker compose down -v          # drops containers + any compose volumes
docker rmi douyin-automation-app:latest
docker volume rm douyin-automation_paddleocr_cache 2>/dev/null || true  # legacy
rm -rf data/                    # WARNING: erases all videos, subtitles, TTS, logs
```

`config/` is not touched — keep or delete by hand.
