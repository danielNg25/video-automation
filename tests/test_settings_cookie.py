"""Tests for the cookie splice helpers in src/api/routers/settings.py.

The helpers keep config/douyin_web_config.yaml in sync with the FE-managed
cookie so a fresh-machine setup is "paste once in the UI" — no nano in WSL.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def helper_config(tmp_path, monkeypatch):
    """Point the helper splice at a temp file and yield its path."""
    cfg = tmp_path / "douyin_web_config.yaml"
    monkeypatch.setattr(
        "src.api.routers.settings._helper_config_path",
        lambda: cfg,
    )
    return cfg


class TestSpliceCookie:
    def test_returns_false_when_file_missing(self, helper_config):
        from src.api.routers.settings import _splice_cookie_into_helper_config
        assert _splice_cookie_into_helper_config("abc=1") is False

    def test_returns_false_when_no_cookie_line(self, helper_config):
        from src.api.routers.settings import _splice_cookie_into_helper_config
        helper_config.write_text("TokenManager:\n  douyin:\n    headers: {}\n")
        assert _splice_cookie_into_helper_config("abc=1") is False

    def test_rewrites_placeholder(self, helper_config):
        from src.api.routers.settings import _splice_cookie_into_helper_config
        helper_config.write_text(
            "TokenManager:\n"
            "  douyin:\n"
            "    headers:\n"
            "      User-Agent: Mozilla/5.0\n"
            "      Cookie: PASTE_YOUR_DOUYIN_COOKIE_HERE\n"
            "      Referer: https://www.douyin.com/\n"
        )
        new_cookie = "sessionid=abc123; uid_tt=xyz; passport_csrf_token=def456"
        assert _splice_cookie_into_helper_config(new_cookie) is True
        text = helper_config.read_text()
        assert f"Cookie: {new_cookie}" in text
        assert "PASTE_YOUR_DOUYIN_COOKIE_HERE" not in text

    def test_preserves_comments_and_other_lines(self, helper_config):
        from src.api.routers.settings import _splice_cookie_into_helper_config
        original = (
            "TokenManager:\n"
            "  douyin:\n"
            "    headers:\n"
            "      # Do not modify User-Agent.\n"
            "      User-Agent: Mozilla/5.0\n"
            "      # Paste cookie below.\n"
            "      Cookie: OLD_COOKIE_VALUE\n"
            "      Referer: https://www.douyin.com/\n"
            "    proxies:\n"
            "      http:\n"
        )
        helper_config.write_text(original)
        assert _splice_cookie_into_helper_config("new=1; val=2") is True
        text = helper_config.read_text()
        assert "# Do not modify User-Agent." in text
        assert "# Paste cookie below." in text
        assert "Referer: https://www.douyin.com/" in text
        assert "proxies:" in text
        assert "Cookie: new=1; val=2" in text

    def test_only_rewrites_first_cookie_line(self, helper_config):
        """A second `Cookie:` further down (e.g. inside a comment block) is
        left alone. The splice targets the first match only."""
        from src.api.routers.settings import _splice_cookie_into_helper_config
        helper_config.write_text(
            "headers:\n"
            "  Cookie: OLD\n"
            "notes:\n"
            "  example: |\n"
            "    Cookie: example_only\n"
        )
        assert _splice_cookie_into_helper_config("new=1") is True
        text = helper_config.read_text()
        assert "Cookie: new=1" in text
        # The second `Cookie:` inside the example string must survive.
        assert "Cookie: example_only" in text


class TestHelperConfigHasRealCookie:
    def test_false_when_file_missing(self, helper_config):
        from src.api.routers.settings import _helper_config_has_real_cookie
        assert _helper_config_has_real_cookie() is False

    def test_false_when_placeholder(self, helper_config):
        from src.api.routers.settings import _helper_config_has_real_cookie
        helper_config.write_text("headers:\n  Cookie: PASTE_YOUR_DOUYIN_COOKIE_HERE\n")
        assert _helper_config_has_real_cookie() is False

    def test_true_when_real_value(self, helper_config):
        from src.api.routers.settings import _helper_config_has_real_cookie
        helper_config.write_text("headers:\n  Cookie: sessionid=abc; uid_tt=xyz\n")
        assert _helper_config_has_real_cookie() is True

    def test_false_when_empty_cookie(self, helper_config):
        from src.api.routers.settings import _helper_config_has_real_cookie
        helper_config.write_text("headers:\n  Cookie: \n")
        assert _helper_config_has_real_cookie() is False
