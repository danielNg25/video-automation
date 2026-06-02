# Auto-save shortened SRT as a version snapshot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After every successful dub generation (full pipeline or DubTab), auto-save the post-shortening SRT as a new immutable version snapshot the editor's version dropdown can pick up.

**Architecture:** Both pipeline and manual TTS funnel through `src/tts/runner.py::run_tts_track`, which already receives the source `segments` and gets back `sentence_plan` from the assembler. A pair of pure functions in `src/tts/shortened_srt.py` redistributes each merged sentence's text back across its original segments (proportional by char length); a thin wrapper around the existing `import_as_version` in `src/api/versions.py` writes the result as a new version snapshot. Failure of the snapshot save never fails the dub.

**Tech Stack:** Python 3.11, pytest with `pytest-asyncio` (auto mode), `unittest.mock` for stubbing. No new dependencies.

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `src/tts/shortened_srt.py` | Pure functions: `split_sentence_to_segments`, `build_shortened_srt`. No I/O. | **Create** |
| `tests/test_shortened_srt.py` | Unit tests for the two helpers (`TestSplitSentence`, `TestBuildShortenedSrt`). | **Create** |
| `src/api/versions.py` | Add `import_segments_as_version` — wraps `import_as_version`'s file-write half with a pre-parsed-segments entry point so the runner doesn't have to round-trip through bytes. | **Modify** |
| `tests/test_versions.py` | Add `TestImportSegmentsAsVersion` (2 tests: creates entry + handles ensure_migrated). | **Modify** |
| `src/tts/runner.py` | Add a try-block after the existing `.plan.json` write: build shortened SRT from `sentence_plan`, save as new version. | **Modify** |
| `tests/test_tts_versioned.py` | Add `TestRunTtsTrackAutoSavesShortenedVersion` (2 tests: happy path + error swallowing). | **Modify** |
| `CHANGELOG.md` | `Added` entry under `[Unreleased]`. | **Modify** |
| `README.md` | New sub-section in Implementation Progress. | **Modify** |

---

### Task 1: `src/tts/shortened_srt.py` — pure helpers + unit tests

**Files:**
- Create: `src/tts/shortened_srt.py`
- Create: `tests/test_shortened_srt.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_shortened_srt.py`:

```python
"""Unit tests for the per-sentence-to-per-segment text redistribution
that powers the post-dub shortened-SRT auto-snapshot."""

from __future__ import annotations

from src.tts.shortened_srt import (
    build_shortened_srt,
    split_sentence_to_segments,
)


class TestSplitSentence:
    def test_single_segment_passthrough(self):
        """N=1 returns the input unchanged in a one-element list."""
        result = split_sentence_to_segments("Hello world.", ["original text"])
        assert result == ["Hello world."]

    def test_two_segments_proportional(self):
        """Two equally-sized originals get the two words 1:1."""
        result = split_sentence_to_segments("hello world", ["foo", "bar"])
        # 3-char + 3-char originals → 50/50 split → one word each.
        assert result == ["hello", "world"]

    def test_unbalanced_segments(self):
        """A tiny first segment + a huge second gets most of the words in
        the second slot."""
        result = split_sentence_to_segments(
            "the quick brown fox jumps",
            ["a", "the quick brown fox jumps over a lazy dog"],
        )
        # First original is 1 char of 41 total ≈ 2.4%. Round-half-up of
        # 5 words * 0.024 = 0 → first slot gets 0 words; all 5 land in
        # the second slot.
        assert result[0] == ""
        assert result[1] == "the quick brown fox jumps"

    def test_more_segments_than_words(self):
        """Trailing segments get '' once we run out of words."""
        result = split_sentence_to_segments("hi", ["a", "b", "c"])
        assert result == ["hi", "", ""]

    def test_empty_merged_text(self):
        """Empty input → empty string for every segment."""
        result = split_sentence_to_segments("", ["a", "b", "c"])
        assert result == ["", "", ""]

    def test_empty_segments_list(self):
        """No originals → empty list out. (Defensive; shouldn't fire.)"""
        result = split_sentence_to_segments("anything", [])
        assert result == []

    def test_originals_with_zero_total_length(self):
        """If every original is empty, split evenly by segment count."""
        result = split_sentence_to_segments("one two three", ["", "", ""])
        # No proportional signal → 3 words across 3 slots → 1 each.
        assert result == ["one", "two", "three"]


class TestBuildShortenedSrt:
    def _orig(self) -> list[dict]:
        """Five-segment fixture in the parse_srt() shape."""
        return [
            {"index": 1, "start": 0.0, "end": 1.0, "text": "alpha"},
            {"index": 2, "start": 1.0, "end": 2.0, "text": "beta"},
            {"index": 3, "start": 2.0, "end": 3.0, "text": "gamma"},
            {"index": 4, "start": 3.0, "end": 4.0, "text": "delta"},
            {"index": 5, "start": 4.0, "end": 5.0, "text": "epsilon"},
        ]

    def test_preserves_original_timings(self):
        """Output rows count + timings match the originals exactly."""
        original = self._orig()
        plan = [
            {"segment_indices": [0, 1, 2], "text": "first sentence here"},
            {"segment_indices": [3, 4], "text": "second sentence"},
        ]
        result = build_shortened_srt(plan, original)
        assert len(result) == 5
        for i, seg in enumerate(result):
            assert seg["start"] == original[i]["start"]
            assert seg["end"] == original[i]["end"]

    def test_text_redistributed_per_plan_entry(self):
        """Plan entry [0,1,2] gets its 3 words distributed across rows 0-2."""
        original = self._orig()
        plan = [
            {"segment_indices": [0, 1, 2], "text": "alpha beta gamma"},
            {"segment_indices": [3, 4], "text": "delta epsilon"},
        ]
        result = build_shortened_srt(plan, original)
        # alpha/beta/gamma are equal-length (5/4/5 ≈ third each) → one word
        # per slot; delta/epsilon are equal too.
        assert result[0]["text"] == "alpha"
        assert result[1]["text"] == "beta"
        assert result[2]["text"] == "gamma"
        assert result[3]["text"] == "delta"
        assert result[4]["text"] == "epsilon"

    def test_segment_not_referenced_keeps_original_text(self):
        """If the plan doesn't cover segment N, that row's text is copied
        from the original unchanged. (Defensive; doesn't happen for
        successful dubs.)"""
        original = self._orig()
        plan = [
            {"segment_indices": [0, 1], "text": "alpha beta"},
            # segments 2, 3, 4 are NOT referenced
        ]
        result = build_shortened_srt(plan, original)
        assert result[2]["text"] == "gamma"
        assert result[3]["text"] == "delta"
        assert result[4]["text"] == "epsilon"

    def test_plan_entry_missing_text_field_skipped(self):
        """A plan entry without a 'text' key (malformed) is skipped without
        crashing; the segments it claimed keep their original text."""
        original = self._orig()
        plan = [
            {"segment_indices": [0, 1]},  # no 'text'
            {"segment_indices": [2, 3, 4], "text": "gamma delta epsilon"},
        ]
        result = build_shortened_srt(plan, original)
        assert result[0]["text"] == "alpha"
        assert result[1]["text"] == "beta"
        # The second entry still applies.
        assert result[2]["text"] == "gamma"
        assert result[3]["text"] == "delta"
        assert result[4]["text"] == "epsilon"
```

- [ ] **Step 1.2: Run tests to confirm they fail**

Run: `python -m pytest tests/test_shortened_srt.py -v 2>&1 | tail -10`
Expected: collection error — `ModuleNotFoundError: No module named 'src.tts.shortened_srt'`.

- [ ] **Step 1.3: Create the module**

Create `src/tts/shortened_srt.py`:

```python
"""Per-sentence text redistribution for auto-saving the dub's shortened
SRT as a version snapshot.

The TTS assembler merges consecutive source segments into sentences and
optionally LLM-shortens the merged text. We want to surface that final
text in the editor without losing the user's per-segment timeline.
Each saved row uses the original segment's start/end timings; the
merged sentence's text is split back across its source segments
proportionally to each segment's original char length.
"""

from __future__ import annotations


def split_sentence_to_segments(
    merged_text: str, original_texts: list[str]
) -> list[str]:
    """Distribute a shortened sentence back across its original N segments.

    Proportional by char length of the original texts. Words from
    ``merged_text`` are split at whitespace and allocated to segments in
    order; each segment gets a number of words such that its share of
    the total approximates its original char-length share.

    Edge cases:
      - ``len(original_texts) == 0`` → returns ``[]``.
      - ``len(original_texts) == 1`` → returns ``[merged_text]`` verbatim.
      - ``merged_text`` is empty/whitespace → returns ``['', '', ...]``
        matching segment count.
      - More segments than words → trailing segments get ``''``.
      - All originals are empty → splits evenly by segment count.
    """
    n = len(original_texts)
    if n == 0:
        return []
    if n == 1:
        return [merged_text]

    words = merged_text.split()
    if not words:
        return [""] * n

    lengths = [len(t) for t in original_texts]
    total_len = sum(lengths)
    if total_len == 0:
        shares = [1.0 / n] * n
    else:
        shares = [length / total_len for length in lengths]

    # Allocate word counts to each segment with cumulative rounding so the
    # total matches len(words) exactly (no off-by-one drift).
    total_words = len(words)
    counts = [0] * n
    cumulative_target = 0.0
    cumulative_allocated = 0
    for i, share in enumerate(shares):
        cumulative_target += share * total_words
        if i == n - 1:
            counts[i] = total_words - cumulative_allocated
        else:
            target = round(cumulative_target)
            counts[i] = max(0, target - cumulative_allocated)
            cumulative_allocated += counts[i]

    # Clamp in case rounding gave the last slot more than we have.
    if counts[-1] < 0:
        counts[-1] = 0

    result: list[str] = []
    cursor = 0
    for c in counts:
        chunk = words[cursor : cursor + c]
        result.append(" ".join(chunk))
        cursor += c
    return result


def build_shortened_srt(
    sentence_plan: list[dict],
    original_segments: list[dict],
) -> list[dict]:
    """Reassemble a per-segment SRT from sentence_plan + original timings.

    Returns a list of segment dicts in the ``parse_srt`` shape
    (``{'index', 'start', 'end', 'text'}``) suitable for ``write_srt``.

    For each entry in ``sentence_plan``:
      - Look up the indices in ``segment_indices``.
      - Call ``split_sentence_to_segments`` with the merged 'text' and
        the originals' texts.
      - Overwrite each referenced segment's ``text`` with its split.

    Original ``start``/``end`` timings are preserved verbatim.
    Segments not referenced by any plan entry keep their original text
    (defensive — doesn't happen for a successful dub).

    Malformed plan entries (missing 'text' or 'segment_indices', or with
    out-of-range indices) are skipped silently so a partial plan doesn't
    crash the snapshot.
    """
    # Start with a shallow copy of each original so we can mutate the
    # text without touching the caller's list.
    output = [dict(seg) for seg in original_segments]

    for entry in sentence_plan:
        indices = entry.get("segment_indices")
        text = entry.get("text")
        if indices is None or text is None:
            continue
        valid_indices = [i for i in indices if 0 <= i < len(output)]
        if not valid_indices:
            continue
        originals = [output[i].get("text", "") for i in valid_indices]
        parts = split_sentence_to_segments(text, originals)
        for i, part in zip(valid_indices, parts):
            output[i]["text"] = part

    return output
```

- [ ] **Step 1.4: Run tests to confirm they pass**

Run: `python -m pytest tests/test_shortened_srt.py -v 2>&1 | tail -15`
Expected: 11 passed.

- [ ] **Step 1.5: Lint clean**

Run: `ruff check src/tts/shortened_srt.py tests/test_shortened_srt.py 2>&1 | tail -3`
Expected: `All checks passed!`

- [ ] **Step 1.6: Commit**

```bash
git add src/tts/shortened_srt.py tests/test_shortened_srt.py
git commit -m "feat(tts): per-sentence text redistribution helpers

Two pure functions for surfacing the dub's post-shortening text in the
editor as a per-segment SRT.

split_sentence_to_segments distributes one merged sentence back across
its N source segments, allocating words proportionally to each
original's char length with cumulative rounding so the word total
always lines up. Edge cases (N=0, N=1, empty input, empty originals,
more segments than words) are explicit and tested.

build_shortened_srt walks a sentence_plan (from the TTS assembler)
and produces a list of segments in the parse_srt shape with original
timings preserved and text replaced by the split. Malformed plan
entries (missing 'text', out-of-range indices) are skipped — a partial
plan can't crash the snapshot path.

11 unit tests. No I/O — both helpers are pure."
```

---

### Task 2: `import_segments_as_version` helper + tests

**Files:**
- Modify: `src/api/versions.py`
- Modify: `tests/test_versions.py`

- [ ] **Step 2.1: Write the failing tests**

Append to `tests/test_versions.py` (anywhere after the existing imports + fixtures). If the file uses a `tmp_path` + `monkeypatch.setattr("src.api.versions.SRT_DIR", ...)` pattern, mirror it:

```python
class TestImportSegmentsAsVersion:
    """import_segments_as_version skips the bytes round-trip — useful for
    in-process callers (like the TTS runner) that already have parsed
    segments in hand."""

    def test_creates_next_version_from_segments(self, tmp_path, monkeypatch):
        """A 2-segment list lands as v1 with the expected file content + entry."""
        srt_dir = tmp_path / "srt"
        srt_dir.mkdir()
        monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
        # Seed an already-migrated versions.json so ensure_migrated is no-op.
        (srt_dir / "vidA_vi.versions.json").write_text("[]")

        from src.api.versions import import_segments_as_version, load_versions

        segments = [
            {"index": 1, "start": 0.0, "end": 1.5, "text": "first"},
            {"index": 2, "start": 1.5, "end": 3.0, "text": "second"},
        ]
        entry = import_segments_as_version(
            "vidA", "vi", segments, name="dub: google/voiceA"
        )

        assert entry.id == "v1"
        assert entry.name == "dub: google/voiceA"

        # File exists with the expected SRT content.
        v1_path = srt_dir / "vidA_vi.v1.srt"
        assert v1_path.exists()
        body = v1_path.read_text(encoding="utf-8")
        assert "first" in body
        assert "second" in body
        assert "00:00:00,000 --> 00:00:01,500" in body
        assert "00:00:01,500 --> 00:00:03,000" in body

        # versions.json has the entry.
        loaded = load_versions("vidA", "vi")
        assert len(loaded) == 1
        assert loaded[0].id == "v1"

    def test_increments_when_versions_already_exist(self, tmp_path, monkeypatch):
        """Existing v1/v2 → new entry is v3."""
        srt_dir = tmp_path / "srt"
        srt_dir.mkdir()
        monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
        import json
        (srt_dir / "vidB_en.versions.json").write_text(json.dumps([
            {"id": "v1", "name": None, "created_at": "2026-05-30T00:00:00+00:00"},
            {"id": "v2", "name": "edit-1", "created_at": "2026-05-30T01:00:00+00:00"},
        ]))

        from src.api.versions import import_segments_as_version

        entry = import_segments_as_version(
            "vidB", "en",
            [{"index": 1, "start": 0.0, "end": 1.0, "text": "hi"}],
            name=None,
        )
        assert entry.id == "v3"
        assert entry.name is None

    def test_calls_ensure_migrated_if_versions_json_missing(
        self, tmp_path, monkeypatch
    ):
        """With no versions.json and no legacy SRTs, ensure_migrated writes
        an empty versions.json — then the new entry lands as v1."""
        srt_dir = tmp_path / "srt"
        srt_dir.mkdir()
        tts_dir = tmp_path / "tts"
        tts_dir.mkdir()
        monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
        monkeypatch.setattr("src.api.versions.TTS_DIR", tts_dir)

        from src.api.versions import import_segments_as_version

        entry = import_segments_as_version(
            "vidC", "vi",
            [{"index": 1, "start": 0.0, "end": 1.0, "text": "ok"}],
            name="dub: x/y",
        )
        assert entry.id == "v1"
        assert (srt_dir / "vidC_vi.versions.json").exists()
        assert (srt_dir / "vidC_vi.v1.srt").exists()
```

- [ ] **Step 2.2: Run tests to confirm they fail**

Run: `python -m pytest tests/test_versions.py::TestImportSegmentsAsVersion -v 2>&1 | tail -10`
Expected: `ImportError: cannot import name 'import_segments_as_version' from 'src.api.versions'`.

- [ ] **Step 2.3: Add the helper to `src/api/versions.py`**

Open `src/api/versions.py`. Find `import_as_version` (around line 106). Add this new function **immediately after** `import_as_version`'s `return entry` (around line 158):

```python
def import_segments_as_version(
    video_id: str,
    language: str,
    segments: list[dict],
    name: str | None = None,
) -> VersionEntry:
    """Write pre-parsed segment dicts as the next snapshot.

    Like ``import_as_version`` but accepts segments directly (skipping
    the bytes → temp-file → parse_srt round-trip). Calls
    ``processor.subtitle.write_srt`` to produce the SRT file. Calls
    ``ensure_migrated`` first so the snapshot lands cleanly even if no
    versions.json exists yet.

    For in-process callers (the TTS runner's auto-snapshot) that
    already hold parsed segments. The HTTP upload path stays on
    ``import_as_version``.

    Raises ValueError if ``segments`` is empty.
    """
    from src.processor.subtitle import write_srt

    if not segments:
        raise ValueError("Cannot write a version snapshot with zero segments")

    ensure_migrated(video_id, language)
    entries = load_versions(video_id, language)
    new_id = next_version_id(entries)
    snap_path = SRT_DIR / f"{video_id}_{language}.{new_id}.srt"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    write_srt(segments, snap_path)
    entry = VersionEntry(
        id=new_id, name=name, created_at=datetime.now(timezone.utc)
    )
    entries.append(entry)
    save_versions(video_id, language, entries)
    return entry
```

- [ ] **Step 2.4: Run tests to confirm they pass**

Run: `python -m pytest tests/test_versions.py::TestImportSegmentsAsVersion -v 2>&1 | tail -10`
Expected: 3 passed.

- [ ] **Step 2.5: Run the full versions test file**

Run: `python -m pytest tests/test_versions.py -v 2>&1 | tail -10`
Expected: all green (existing + 3 new).

- [ ] **Step 2.6: Lint clean**

Run: `ruff check src/api/versions.py tests/test_versions.py 2>&1 | tail -3`
Expected: `All checks passed!`

- [ ] **Step 2.7: Commit**

```bash
git add src/api/versions.py tests/test_versions.py
git commit -m "feat(versions): import_segments_as_version — bytes-free entry point

Adds a sibling to import_as_version that accepts pre-parsed segment
dicts directly, skipping the bytes → NamedTemporaryFile → parse_srt
validation round-trip. Useful for in-process callers (next commit:
the TTS runner) that already hold parsed segments in hand.

Reuses the same SRT_DIR + versions.json layout, the same VersionEntry
shape, and the same next_version_id allocator — so a snapshot
produced this way is indistinguishable from one made via the HTTP
upload path. ensure_migrated runs first so callers don't need to
worry about whether versions.json exists yet.

3 new tests in TestImportSegmentsAsVersion: creates v1 from segments,
increments to v3 when v1+v2 already exist, handles a missing
versions.json via the migration call."
```

---

### Task 3: Wire auto-save into `run_tts_track` + integration tests

**Files:**
- Modify: `src/tts/runner.py`
- Modify: `tests/test_tts_versioned.py`

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/test_tts_versioned.py`. The file already uses `monkeypatch.chdir(tmp_path)` to confine SRT writes. Mirror that.

```python
class TestRunTtsTrackAutoSavesShortenedVersion:
    """After a successful dub, run_tts_track should auto-save a per-segment
    version snapshot whose text is the dub's post-shortening output."""

    def _seed_srt(self, srt_dir: Path) -> None:
        """A 3-segment working-draft SRT that the runner will load."""
        (srt_dir / "vid1_vi.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,500\nfirst\n\n"
            "2\n00:00:01,500 --> 00:00:03,000\nsecond\n\n"
            "3\n00:00:03,000 --> 00:00:04,500\nthird\n\n",
            encoding="utf-8",
        )

    def test_creates_dub_named_version_after_successful_run(
        self, tmp_path, monkeypatch
    ):
        """A 1-entry sentence_plan covering all 3 segments → v1 SRT with
        the redistributed text, named 'dub: <provider>/<voice>'."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        monkeypatch.chdir(tmp_path)
        srt_dir = tmp_path / "data" / "srt"
        srt_dir.mkdir(parents=True)
        tts_dir = tmp_path / "data" / "tts"
        tts_dir.mkdir(parents=True)
        # ensure_migrated needs SRT_DIR + TTS_DIR pointed at tmp_path.
        monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
        monkeypatch.setattr("src.api.versions.TTS_DIR", tts_dir)
        self._seed_srt(srt_dir)

        # The assembler writes the dub WAV; we stub it to drop a tiny
        # placeholder and return a known sentence_plan.
        fake_plan = [
            {
                "index": 0,
                "segment_indices": [0, 1, 2],
                "text": "shortened final text",
            }
        ]

        async def fake_generate(*args, **kwargs):
            kwargs["output_path"].write_bytes(b"RIFFfake")
            return (kwargs["output_path"], fake_plan)

        with patch(
            "src.tts.assembler.TTSAssembler.generate_full_track",
            new=AsyncMock(side_effect=fake_generate),
        ), patch(
            "src.tts.runner.get_tts_provider",
            return_value=object(),
        ), patch(
            "src.tts.runner._build_llm_translator",
            return_value=None,
        ):
            from src.tts.runner import run_tts_track

            asyncio.run(run_tts_track(
                video_id="vid1",
                video_path=tmp_path / "data" / "raw" / "vid1.mp4",
                language="vi",
                voice="vi-VN-Wavenet-A",
                provider="google",
                config={},
                canonical_duration=4.5,
                version="draft",
            ))

        # The auto-saved snapshot exists and has the redistributed text.
        v1_path = srt_dir / "vid1_vi.v1.srt"
        assert v1_path.exists()
        body = v1_path.read_text(encoding="utf-8")
        assert "shortened" in body  # at least one of the words landed
        assert "00:00:00,000 --> 00:00:01,500" in body  # original timings

        # The versions index records it with the expected name.
        from src.api.versions import load_versions
        entries = load_versions("vid1", "vi")
        assert len(entries) == 1
        assert entries[0].id == "v1"
        assert entries[0].name == "dub: google/vi-VN-Wavenet-A"

    def test_run_completes_even_if_snapshot_save_raises(
        self, tmp_path, monkeypatch, caplog
    ):
        """A failure in build_shortened_srt must not bubble out of
        run_tts_track. The dub is still considered successful."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        monkeypatch.chdir(tmp_path)
        srt_dir = tmp_path / "data" / "srt"
        srt_dir.mkdir(parents=True)
        tts_dir = tmp_path / "data" / "tts"
        tts_dir.mkdir(parents=True)
        monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
        monkeypatch.setattr("src.api.versions.TTS_DIR", tts_dir)
        self._seed_srt(srt_dir)

        async def fake_generate(*args, **kwargs):
            kwargs["output_path"].write_bytes(b"RIFFfake")
            return (kwargs["output_path"], [{"segment_indices": [0], "text": "x"}])

        with patch(
            "src.tts.assembler.TTSAssembler.generate_full_track",
            new=AsyncMock(side_effect=fake_generate),
        ), patch(
            "src.tts.runner.get_tts_provider",
            return_value=object(),
        ), patch(
            "src.tts.runner._build_llm_translator",
            return_value=None,
        ), patch(
            "src.tts.shortened_srt.build_shortened_srt",
            side_effect=RuntimeError("boom"),
        ):
            from src.tts.runner import run_tts_track

            result = asyncio.run(run_tts_track(
                video_id="vid1",
                video_path=tmp_path / "data" / "raw" / "vid1.mp4",
                language="vi",
                voice="vi-VN-Wavenet-A",
                provider="google",
                config={},
                canonical_duration=4.5,
                version="draft",
            ))

        # The dub still returns successfully.
        assert result["audio_path"]
        # No snapshot was written.
        assert not (srt_dir / "vid1_vi.v1.srt").exists()
        # The failure was logged.
        assert any("Could not save shortened version" in r.message for r in caplog.records)

    def test_no_snapshot_when_sentence_plan_is_empty(
        self, tmp_path, monkeypatch
    ):
        """Empty sentence_plan → skip the snapshot save entirely (no v1.srt,
        no versions.json entry). This is the synth-failed-completely path."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        monkeypatch.chdir(tmp_path)
        srt_dir = tmp_path / "data" / "srt"
        srt_dir.mkdir(parents=True)
        tts_dir = tmp_path / "data" / "tts"
        tts_dir.mkdir(parents=True)
        monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
        monkeypatch.setattr("src.api.versions.TTS_DIR", tts_dir)
        self._seed_srt(srt_dir)

        async def fake_generate(*args, **kwargs):
            kwargs["output_path"].write_bytes(b"RIFFfake")
            return (kwargs["output_path"], [])

        with patch(
            "src.tts.assembler.TTSAssembler.generate_full_track",
            new=AsyncMock(side_effect=fake_generate),
        ), patch(
            "src.tts.runner.get_tts_provider",
            return_value=object(),
        ), patch(
            "src.tts.runner._build_llm_translator",
            return_value=None,
        ):
            from src.tts.runner import run_tts_track

            asyncio.run(run_tts_track(
                video_id="vid1",
                video_path=tmp_path / "data" / "raw" / "vid1.mp4",
                language="vi",
                voice="vi-VN-Wavenet-A",
                provider="google",
                config={},
                canonical_duration=4.5,
                version="draft",
            ))

        assert not (srt_dir / "vid1_vi.v1.srt").exists()
```

- [ ] **Step 3.2: Run tests to confirm they fail**

Run: `python -m pytest tests/test_tts_versioned.py::TestRunTtsTrackAutoSavesShortenedVersion -v 2>&1 | tail -15`
Expected: 3 FAIL. The first asserts that `vid1_vi.v1.srt` exists — it won't because the wire-up isn't in place.

- [ ] **Step 3.3: Wire the auto-save into `run_tts_track`**

Open `src/tts/runner.py`. Find the closing of the `.plan.json` / `.plan.tsv` block — the `except Exception as e:` at around line 324 that logs "Could not write dub plan log". Immediately after that except's body (before `return {...}` at around line 327), insert this block:

```python
    # Auto-save the post-shortening text as a new version snapshot so the
    # user can see what the dub actually said from the editor's version
    # dropdown. Failure here is logged but never fails the dub — the WAV
    # is the primary deliverable; the snapshot is convenience.
    try:
        from src.api.versions import import_segments_as_version
        from src.tts.shortened_srt import build_shortened_srt

        if sentence_plan:
            shortened_segments = build_shortened_srt(sentence_plan, segments)
            entry = import_segments_as_version(
                video_id=video_id,
                language=language,
                segments=shortened_segments,
                name=f"dub: {provider}/{voice}",
            )
            logger.info(
                f"Saved shortened version {entry.id} as '{entry.name}'"
            )
    except Exception as e:  # noqa: BLE001 — snapshot save is convenience
        logger.warning(f"Could not save shortened version: {e}")
```

The block uses `provider` (the function parameter, in scope) and `voice` (also a function parameter). `sentence_plan` and `segments` are the existing locals from the assembler call and the SRT load respectively.

- [ ] **Step 3.4: Run the new tests to confirm they pass**

Run: `python -m pytest tests/test_tts_versioned.py::TestRunTtsTrackAutoSavesShortenedVersion -v 2>&1 | tail -15`
Expected: 3 passed.

- [ ] **Step 3.5: Run the full TTS test surface**

```bash
python -m pytest tests/test_tts_versioned.py tests/test_shortened_srt.py tests/test_versions.py -v 2>&1 | tail -10
```
Expected: all green.

- [ ] **Step 3.6: Run the full BE suite**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -5`
Expected: green. Roughly 6 more tests than the baseline (3 helper + 3 runner-integration + the versions tests already counted).

- [ ] **Step 3.7: Lint clean**

Run: `ruff check src/tts/runner.py tests/test_tts_versioned.py 2>&1 | tail -3`
Expected: `All checks passed!`

- [ ] **Step 3.8: Commit**

```bash
git add src/tts/runner.py tests/test_tts_versioned.py
git commit -m "feat(tts): auto-save shortened SRT as a version snapshot

After every successful dub generation (full pipeline + DubTab), the
runner now writes a per-segment SRT capturing what the dub actually
said and registers it as a new version snapshot. The user sees it in
the editor's version dropdown as 'v{N+1} — dub: {provider}/{voice}'.

Inserted as a try-block in run_tts_track right after the existing
.plan.json/.plan.tsv write so both entry points (pipeline + manual
TTS) benefit from one wire-up. The block uses build_shortened_srt to
redistribute each merged sentence's post-shortening text back across
its source segments, preserving the user's editable timeline, then
calls the new import_segments_as_version to write the snapshot.

Failure of the snapshot is logged at WARNING and swallowed — the WAV
is the primary deliverable. An empty sentence_plan (full synth
failure) also skips the snapshot cleanly.

3 new integration tests: happy path, snapshot-failure swallowed,
empty-plan no-op."
```

---

### Task 4: CHANGELOG + README rollup

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 4.1: CHANGELOG entry**

Open `CHANGELOG.md`. Find `## [Unreleased]` → `### Added`. Add this entry at the top of `Added`:

```markdown
- **Auto-saved shortened-dub version snapshot.** Every successful dub generation (full pipeline or DubTab "Generate TTS Audio") now writes a new immutable version snapshot capturing what the dub actually said. The editor's version dropdown shows it as `v{N+1} — dub: {provider}/{voice}` and the segment list previews the post-shortening text on the original per-segment timeline. Implementation: two pure helpers in `src/tts/shortened_srt.py` redistribute each merged sentence's text back across its source segments proportionally to original char length; a new `import_segments_as_version` in `src/api/versions.py` writes the result through the existing version-snapshot machinery; the wire-up sits in `src/tts/runner.py::run_tts_track` after the existing `.plan.json` write so both entry points benefit. Snapshot failures are logged but never fail the dub — the WAV is the primary deliverable. 11 unit tests for the split + 3 new helper tests + 3 integration tests on the runner path.
```

- [ ] **Step 4.2: README progress section**

Open `README.md`. Find the most recent dated subsection under Implementation Progress (currently "Standalone SRT → Dub Studio (2026-05-30)"). Insert this new subsection immediately after its `---` separator:

```markdown
### Auto-save shortened-dub SRT (2026-05-31)

> Closes the loop on the dub-shortening pipeline. See [`docs/superpowers/specs/2026-05-31-auto-save-shortened-srt-design.md`](docs/superpowers/specs/2026-05-31-auto-save-shortened-srt-design.md) and [`docs/superpowers/plans/2026-05-31-auto-save-shortened-srt.md`](docs/superpowers/plans/2026-05-31-auto-save-shortened-srt.md).

- [x] **Task 1** — `src/tts/shortened_srt.py`: `split_sentence_to_segments` + `build_shortened_srt` pure helpers. 11 unit tests covering single-segment passthrough, proportional split, unbalanced segments, more-segments-than-words, empty input, empty originals, and the build-srt assembly.
- [x] **Task 2** — `src/api/versions.py::import_segments_as_version`: bytes-free entry point that writes pre-parsed segments through the existing version-snapshot machinery. Calls `ensure_migrated` so callers don't need to. 3 new tests.
- [x] **Task 3** — Wire the auto-save into `run_tts_track`: try-block after the existing `.plan.json` write, builds the shortened SRT from `sentence_plan`, saves as `dub: {provider}/{voice}`. Snapshot failures are warning-logged and swallowed. 3 integration tests.
- [x] **Task 4** — CHANGELOG + README updates.

---
```

- [ ] **Step 4.3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(auto-save-shortened-srt): CHANGELOG + README rollup"
```

---

## Final verification (run before reporting DONE)

- [ ] **Step F.1: Full BE suite**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -5`
Expected: green. Roughly +17 tests over the baseline (11 split + 3 versions + 3 runner).

- [ ] **Step F.2: BE lint on every touched file**

```bash
ruff check src/tts/shortened_srt.py src/api/versions.py src/tts/runner.py \
  tests/test_shortened_srt.py tests/test_versions.py tests/test_tts_versioned.py \
  2>&1 | tail -3
```
Expected: `All checks passed!`

- [ ] **Step F.3: Manual smoke (after merge)**

1. Pipeline a short Douyin clip end-to-end.
2. Open the per-video editor. Confirm the version dropdown contains `Working draft` and a new `v{N} — dub: {provider}/{voice}` entry.
3. Pick the new entry. Confirm the segment list shows the post-shortening text on the original timeline.
4. Compare against `data/tts/{video_id}_*_*.plan.json` — the `text` field of each plan entry should match the concatenation of the corresponding rows in the new version.
5. Re-dub with a different voice. Confirm a second auto-snapshot lands (e.g. `v{N+1}`), no overwrite.

---

## Self-review checklist (for the implementer)

- [ ] Spec coverage: every section of the spec maps to a task — pure helpers (T1), version-snapshot helper (T2), runner wire-up (T3), docs (T4).
- [ ] No "TBD" / "implement later" / "similar to Task N" anywhere.
- [ ] Type/name consistency: `split_sentence_to_segments`, `build_shortened_srt`, `import_segments_as_version` used identically across plan tasks and the spec.
- [ ] Snapshot name format `f"dub: {provider}/{voice}"` is the same string in T3 step 3.3 and T3 test step 3.1.
- [ ] No new branches created mid-plan; all work lands on `feature/auto-save-shortened-srt`.
- [ ] No AI-attribution strings in any commit message.
- [ ] CHANGELOG entry is in the `Added` subsection of `[Unreleased]`.
- [ ] README entry lives next to the other dated implementation-progress subsections, not at the bottom of the file.
