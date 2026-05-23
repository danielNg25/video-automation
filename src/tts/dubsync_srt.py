"""Per-segment SRT writer for the dubsync output.

Given the original SRT segments and the post-emission sentence plans
(which include `final_start`, `final_duration`, `target_text`, and the
`segment_indices` they span), produce a per-segment SRT whose text is
proportionally redistributed at word boundaries and whose timings are
re-anchored to the actual dub positions.
"""
from __future__ import annotations

from pathlib import Path

from src.processor.subtitle import write_srt
from src.tts.base import _clean_text


def _split_text_proportional(target_text: str, weights: list[int]) -> list[str]:
    """Split `target_text` into len(weights) chunks at word boundaries with
    chunk lengths proportional to `weights`. Empty target_text returns empty
    chunks. When there are fewer words than chunks some trailing chunks will be
    empty. Each non-empty chunk gets at least one word."""
    if not weights:
        return []
    n = len(weights)
    if not target_text:
        return [""] * n
    if n == 1:
        return [target_text]
    total_w = sum(weights) or 1
    total_chars = len(target_text)
    words = target_text.split(" ")
    # Cumulative character positions (including preceding spaces)
    cum_lens: list[int] = []
    running = 0
    for i, w in enumerate(words):
        running += len(w) + (1 if i > 0 else 0)
        cum_lens.append(running)

    # Assign a minimum of 1 word to each chunk that can get one, leaving
    # remaining words distributed proportionally.
    chunks: list[str] = []
    word_cursor = 0
    cum_target = 0
    remaining_chunks = n
    for i in range(n):
        remaining_chunks -= 1
        cum_target += int(total_chars * weights[i] / total_w + 0.5)
        if i == n - 1:
            # Last chunk: take everything that's left
            chunks.append(" ".join(words[word_cursor:]))
            break
        # Words left for future chunks (must reserve at least 1 per remaining chunk)
        words_left = len(words) - word_cursor
        # We must leave at least `remaining_chunks` words for the remaining chunks
        max_words_this_chunk = max(1, words_left - remaining_chunks)
        boundary = word_cursor
        while (
            boundary < word_cursor + max_words_this_chunk - 1
            and cum_lens[boundary] < cum_target
        ):
            boundary += 1
        chunk_words = words[word_cursor:boundary + 1]
        chunks.append(" ".join(chunk_words))
        word_cursor = boundary + 1
        if word_cursor >= len(words):
            # Ran out of words — fill remaining chunks with empty strings
            while len(chunks) < n:
                chunks.append("")
            break
    while len(chunks) < n:
        chunks.append("")
    return chunks[:n]


def write_dubsync_srt(
    source_segments: list[dict],
    sentence_plans: list[dict],
    output_path: Path,
) -> Path:
    """Write `output_path` with one SRT entry per original source segment,
    text redistributed from the dub sentence plan, timings re-anchored to
    `final_start` + proportional share of `final_duration`."""
    out_segments: list[dict] = []
    used = set()

    for sp in sentence_plans:
        idxs = list(sp.get("segment_indices") or [])
        if not idxs:
            continue
        target_text = sp.get("target_text") or sp.get("text") or ""
        target_text = _clean_text(target_text)
        if not target_text:
            continue
        final_start = float(sp["final_start"])
        final_duration = float(sp["final_duration"])
        weights = [
            max(1, len(_clean_text(source_segments[k].get("text", ""))))
            for k in idxs
        ]
        chunks = _split_text_proportional(target_text, weights)
        orig_durations = [
            max(0.0, source_segments[k]["end"] - source_segments[k]["start"])
            for k in idxs
        ]
        total_orig = sum(orig_durations) or 1.0
        anchor = final_start
        for k, share_dur, chunk in zip(idxs, orig_durations, chunks):
            share = (share_dur / total_orig) * final_duration
            out_segments.append({
                "start": anchor,
                "end": anchor + share,
                "text": chunk,
            })
            anchor += share
            used.add(k)

    for k, seg in enumerate(source_segments):
        if k not in used:
            out_segments.append({
                "start": seg["start"], "end": seg["end"],
                "text": _clean_text(seg.get("text", "")),
            })

    out_segments.sort(key=lambda s: s["start"])
    return write_srt(out_segments, output_path)
