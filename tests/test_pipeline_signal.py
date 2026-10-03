"""Tests that Pipeline installs process signal handlers only when the CLI
asks (install_signal_handlers=True), never by default (e.g. from the API)."""

from __future__ import annotations

import pytest

import src.pipeline as pl


@pytest.mark.asyncio
async def test_no_signal_handlers_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(pl.signal, "signal", lambda *a: calls.append(a))

    async def boom(*a, **k):
        raise RuntimeError("stop early")

    monkeypatch.setattr("src.downloader.download_with_fallback", boom)

    p = pl.Pipeline({"ocr": {}})
    await p.process_single("http://x", {}, None)  # default: no handlers

    assert calls == []


@pytest.mark.asyncio
async def test_signal_handlers_installed_when_requested(monkeypatch):
    calls = []
    monkeypatch.setattr(pl.signal, "signal", lambda *a: calls.append(a))

    async def boom(*a, **k):
        raise RuntimeError("stop early")

    monkeypatch.setattr("src.downloader.download_with_fallback", boom)

    p = pl.Pipeline({"ocr": {}})
    await p.process_single("http://x", {}, None, install_signal_handlers=True)

    assert len(calls) >= 1  # SIGINT/SIGTERM registered
