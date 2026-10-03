"""Tests for identifier validation + path containment (API step 1).

Covers the pure validators and `ensure_within`, plus endpoint-level checks
that crafted language/version/video_id values are rejected with 422 before
any path is built, and that valid input still works.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api.validation import (
    ensure_within,
    validate_language,
    validate_profile_name,
    validate_uuid,
    validate_version,
    validate_video_id,
)


class TestValidateVideoId:
    @pytest.mark.parametrize("value", ["7412345678901234567", "abc_DEF-123", "x"])
    def test_accepts_real_ids(self, value):
        assert validate_video_id(value) == value

    @pytest.mark.parametrize(
        "value",
        ["../etc", "a/b", "a.b", "a\\b", "", "x" * 129, "foo bar", "a;b", "vid\n", "\nvid"],
    )
    def test_rejects_bad_ids(self, value):
        with pytest.raises(HTTPException) as exc:
            validate_video_id(value)
        assert exc.value.status_code == 422


class TestValidateLanguage:
    @pytest.mark.parametrize("value", ["zh", "en", "vi", "vi-VN", "zh-Hans"])
    def test_accepts_language_tags(self, value):
        assert validate_language(value) == value

    @pytest.mark.parametrize(
        "value",
        ["../x", "e", "EN", "", "en/us", "vi-", "a_b", "../../etc/passwd", "en\n", "vi\nvi"],
    )
    def test_rejects_bad_languages(self, value):
        with pytest.raises(HTTPException) as exc:
            validate_language(value)
        assert exc.value.status_code == 422


class TestValidateVersion:
    @pytest.mark.parametrize("value", ["draft", "v1", "v12", "v999999", "v123456789"])
    def test_accepts_slots(self, value):
        assert validate_version(value) == value

    @pytest.mark.parametrize(
        "value", ["v", "v1.5", "V1", "../x", "", "latest", "v-1", "v1234567890", "v1\n"]
    )
    def test_rejects_bad_versions(self, value):
        with pytest.raises(HTTPException) as exc:
            validate_version(value)
        assert exc.value.status_code == 422

    def test_accepts_generator_output_bound(self):
        # The generator increments without a cap; the validator must accept
        # anything it can realistically emit (9 digits >> any real count).
        assert validate_version("v1000000") == "v1000000"


class TestValidateProfileName:
    @pytest.mark.parametrize("value", ["funny-casual-vi", "a", "My Profile_1", "x" * 64])
    def test_accepts_slugs(self, value):
        assert validate_profile_name(value) == value

    @pytest.mark.parametrize(
        "value", ["../config", "a/b", "a.yaml", ".hidden", "", "x" * 65, "p\n", "a\\b"]
    )
    def test_rejects_bad_names(self, value):
        with pytest.raises(HTTPException) as exc:
            validate_profile_name(value)
        assert exc.value.status_code == 422


class TestValidateUuid:
    @pytest.mark.parametrize(
        "value", ["550e8400-e29b-41d4-a716-446655440000", "abc123", "A-B-C"]
    )
    def test_accepts_uuids(self, value):
        assert validate_uuid(value) == value

    @pytest.mark.parametrize("value", ["../x", "a/b", "a.b", "a_b", "", "u\n"])
    def test_rejects_bad_uuids(self, value):
        with pytest.raises(HTTPException) as exc:
            validate_uuid(value)
        assert exc.value.status_code == 422


class TestEnsureWithin:
    def test_allows_child(self, tmp_path):
        base = tmp_path / "srt"
        base.mkdir()
        resolved = ensure_within(base, base / "vid_vi.srt")
        assert resolved == (base / "vid_vi.srt").resolve()

    def test_allows_base_itself(self, tmp_path):
        base = tmp_path / "srt"
        base.mkdir()
        assert ensure_within(base, base) == base.resolve()

    def test_rejects_escape(self, tmp_path):
        base = tmp_path / "srt"
        base.mkdir()
        with pytest.raises(HTTPException) as exc:
            ensure_within(base, base / ".." / ".." / "etc" / "passwd")
        assert exc.value.status_code == 422

    def test_rejects_absolute_outside(self, tmp_path):
        base = tmp_path / "srt"
        base.mkdir()
        with pytest.raises(HTTPException) as exc:
            ensure_within(base, Path("/etc/passwd"))
        assert exc.value.status_code == 422


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Redirect the versions SRT dir and reset the TaskManager singleton so
    # video_index doesn't leak between tests.
    from src.api import deps, versions

    monkeypatch.setattr(versions, "SRT_DIR", tmp_path / "srt")
    monkeypatch.setattr(deps, "_task_manager", None)
    deps.get_config.cache_clear()
    from src.api import create_app

    return TestClient(create_app())


def _write_srt(tmp_path, video_id, language, body):
    srt_dir = tmp_path / "srt"
    srt_dir.mkdir(parents=True, exist_ok=True)
    (srt_dir / f"{video_id}_{language}.srt").write_text(body, encoding="utf-8")


@pytest.mark.parametrize(
    "params",
    [
        {"language": "../../../etc/passwd"},
        {"language": "en/../../secret"},
        {"language": "en", "version": "../../etc"},
        {"language": "en", "version": "v1; rm -rf"},
    ],
)
def test_download_srt_rejects_crafted_params(client, params):
    r = client.get("/api/videos/vid1/srt/download", params=params)
    assert r.status_code == 422, r.text


def test_download_srt_rejects_crafted_video_id(client):
    # The path segment can't contain a slash; use a dot-traversal id.
    r = client.get("/api/videos/..%2f..%2fetc/srt/download", params={"language": "en"})
    assert r.status_code in (404, 422), r.text


def test_get_srt_rejects_bad_language(client):
    r = client.get("/api/videos/vid1/srt", params={"language": "../x"})
    assert r.status_code == 422, r.text


def test_versions_list_rejects_bad_language(client):
    r = client.get("/api/videos/vid1/versions", params={"language": "../x"})
    assert r.status_code == 422, r.text


def test_save_srt_rejects_bad_version(client):
    r = client.put(
        "/api/videos/vid1/srt",
        json={"language": "en", "version": "../../etc", "segments": []},
    )
    assert r.status_code == 422, r.text


def test_tts_rejects_bad_language(client):
    r = client.post(
        "/api/tts",
        json={"video_id": "vid1", "language": "../x", "voice": "v", "provider": "google"},
    )
    assert r.status_code == 422, r.text


def test_tts_rejects_bad_version(client):
    r = client.post(
        "/api/tts",
        json={
            "video_id": "vid1",
            "language": "vi",
            "voice": "v",
            "provider": "google",
            "version": "../../etc",
        },
    )
    assert r.status_code == 422, r.text


def test_translate_rejects_bad_profile_name(client):
    r = client.post(
        "/api/translate",
        json={"video_id": "vid1", "profile_name": "../config", "source_language": "zh"},
    )
    assert r.status_code == 422, r.text


def test_create_profile_rejects_bad_name(client):
    r = client.post(
        "/api/profiles",
        json={
            "name": "../config",
            "description": "x",
            "target_language": "vi",
            "style_guide": "s",
        },
    )
    assert r.status_code == 422, r.text


def test_create_profile_rejects_bad_target_language(client):
    # target_language is interpolated into the translated SRT filename;
    # a traversal value must be rejected (not stored to escape at translate).
    r = client.post(
        "/api/profiles",
        json={
            "name": "evil",
            "description": "x",
            "target_language": "x/../../../outside",
            "style_guide": "s",
        },
    )
    assert r.status_code == 422, r.text


def test_full_pipeline_rejects_bad_source_language(client):
    r = client.post(
        "/api/pipeline/full",
        json={"url": "https://v.douyin.com/x", "source_language": "../x"},
    )
    assert r.status_code == 422, r.text


def test_full_pipeline_rejects_bad_tts_language(client):
    r = client.post(
        "/api/pipeline/full",
        json={"url": "https://v.douyin.com/x", "source_language": "zh", "tts_language": "a/b"},
    )
    assert r.status_code == 422, r.text


def test_standalone_dub_delete_rejects_bad_uuid(client):
    r = client.delete("/api/standalone-dub/a.b")
    assert r.status_code == 422, r.text


def test_spa_fallback_does_not_serve_outside_ui_dir(tmp_path, monkeypatch):
    # Build a fake UI dist with an index, and plant a sentinel OUTSIDE it.
    ui_dist = tmp_path / "dist"
    ui_dist.mkdir(parents=True)
    (ui_dist / "index.html").write_text("INDEX", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")

    from src.api import deps
    import src.api as api_mod

    monkeypatch.setattr(api_mod, "UI_DIST", ui_dist)
    monkeypatch.setattr(deps, "_task_manager", None)
    deps.get_config.cache_clear()
    c = TestClient(api_mod.create_app())

    # Encoded traversal out of the UI dir must fall back to index, never the
    # sentinel one level up.
    r = c.get("/%2e%2e/secret.txt")
    assert "SECRET" not in r.text
    assert r.text == "INDEX"
    # A normal in-dir file is still served.
    (ui_dist / "app.js").write_text("JS", encoding="utf-8")
    r2 = c.get("/app.js")
    assert r2.text == "JS"


def test_valid_download_still_works(client, tmp_path):
    _write_srt(
        tmp_path,
        "vid1",
        "vi",
        "1\n00:00:00,000 --> 00:00:01,000\nXin chào\n",
    )
    r = client.get("/api/videos/vid1/srt/download", params={"language": "vi"})
    assert r.status_code == 200, r.text
    assert "Xin chào" in r.text
