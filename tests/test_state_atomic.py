"""Tests for atomic state writes + transactional registry/run-log."""

from __future__ import annotations

import json
import threading

import pytest

import src.utils.state as st


def test_save_load_roundtrip_leaves_no_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "LOGS_DIR", tmp_path)
    s = st.PipelineState(video_id="vid1", url="u")
    s.mark_stage_complete("download", {"file_path": "x"})
    loaded = st.PipelineState.load("vid1")
    assert loaded.video_id == "vid1"
    assert "download" in loaded.completed_stages
    assert loaded.stage_results["download"]["file_path"] == "x"
    assert not list(tmp_path.glob("*.tmp"))  # no stray temp files


def test_load_tolerates_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "LOGS_DIR", tmp_path)
    (tmp_path / "bad_state.json").write_text("{ not json")
    s = st.PipelineState.load("bad")
    assert s.video_id == "bad"  # falls back to fresh state


def test_registry_concurrent_no_lost_updates(tmp_path, monkeypatch):
    reg = tmp_path / "processed.json"
    monkeypatch.setattr(st, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(st, "REGISTRY_PATH", reg)
    n = 30

    def reg_one(i):
        st.register_processed(f"v{i}", {"url": f"http://x/{i}"})

    threads = [threading.Thread(target=reg_one, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = json.loads(reg.read_text())
    assert len(data) == n  # every update survived (no lost updates)
    assert not list(tmp_path.glob("*.tmp"))


def test_register_unregister_concurrent(tmp_path, monkeypatch):
    reg = tmp_path / "processed.json"
    monkeypatch.setattr(st, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(st, "REGISTRY_PATH", reg)
    for i in range(10):
        st.register_processed(f"keep{i}", {"url": f"k{i}"})

    def reg_new(i):
        st.register_processed(f"new{i}", {"url": f"n{i}"})

    def unreg(i):
        st.unregister_processed(f"keep{i}")

    threads = [threading.Thread(target=reg_new, args=(i,)) for i in range(20)]
    threads += [threading.Thread(target=unreg, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = json.loads(reg.read_text())
    for i in range(20):
        assert f"new{i}" in data  # new registrations survived
    for i in range(5):
        assert f"keep{i}" not in data  # targeted removals applied
    for i in range(5, 10):
        assert f"keep{i}" in data  # untouched keepers preserved


def test_corrupt_registry_backed_up_not_lost(tmp_path, monkeypatch):
    reg = tmp_path / "processed.json"
    monkeypatch.setattr(st, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(st, "REGISTRY_PATH", reg)
    reg.write_text("CORRUPT-A")
    st.register_processed("v1", {"url": "u"})
    data = json.loads(reg.read_text())
    assert "v1" in data  # reinitialised with the new entry
    backups = list(tmp_path.glob("processed.json.corrupt.*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "CORRUPT-A"  # exact bytes preserved


def test_corrupt_backup_names_are_unique(tmp_path, monkeypatch):
    """A second corruption in the same process must not overwrite the first
    backup."""
    reg = tmp_path / "processed.json"
    monkeypatch.setattr(st, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(st, "REGISTRY_PATH", reg)
    reg.write_text("CORRUPT-A")
    st.register_processed("v1", {"url": "u"})
    reg.write_text("CORRUPT-B")  # corrupt again
    st.register_processed("v2", {"url": "u2"})
    backups = sorted(tmp_path.glob("processed.json.corrupt.*"))
    assert len(backups) == 2  # distinct names, neither overwritten
    assert {b.read_text() for b in backups} == {"CORRUPT-A", "CORRUPT-B"}


def test_corrupt_backup_failure_aborts_without_overwrite(tmp_path, monkeypatch):
    """If the corrupt file can't be preserved, the transaction aborts and
    leaves the original untouched (no silent data loss)."""
    import pathlib

    reg = tmp_path / "processed.json"
    monkeypatch.setattr(st, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(st, "REGISTRY_PATH", reg)
    reg.write_text("CORRUPT")

    orig_replace = pathlib.Path.replace

    def fake_replace(self, target):
        if ".corrupt." in str(target):
            raise OSError("cannot preserve backup")
        return orig_replace(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", fake_replace)
    with pytest.raises(OSError):
        st.register_processed("v1", {"url": "u"})
    assert reg.read_text() == "CORRUPT"  # original NOT overwritten


def test_runs_concurrent_no_lost_updates(tmp_path, monkeypatch):
    runs = tmp_path / "pipeline_runs.json"
    monkeypatch.setattr(st, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(st, "RUNS_PATH", runs)
    n = 30

    def create_one(i):
        st.create_pipeline_run(f"run{i}", "single", [f"u{i}"], [])

    threads = [threading.Thread(target=create_one, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = json.loads(runs.read_text())
    assert len(data) == n


def test_update_pipeline_run_concurrent(tmp_path, monkeypatch):
    runs = tmp_path / "pipeline_runs.json"
    monkeypatch.setattr(st, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(st, "RUNS_PATH", runs)
    st.create_pipeline_run("r1", "single", ["u"], [])
    n = 30

    def upd(i):
        st.update_pipeline_run("r1", {f"k{i}": i})

    threads = [threading.Thread(target=upd, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = json.loads(runs.read_text())
    assert len(data) == 1
    run = data[0]
    for i in range(n):
        assert run.get(f"k{i}") == i  # every concurrent field update survived
