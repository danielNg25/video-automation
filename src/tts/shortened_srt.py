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

    # Allocate word counts using the largest-remainder method so the total
    # always matches len(words) exactly. Ties in remainder are broken by
    # earlier index so words fill from the front (trailing segments get ''
    # before leading ones when there are fewer words than segments).
    total_words = len(words)
    raw = [share * total_words for share in shares]
    floors = [int(x) for x in raw]
    remainders = sorted(
        enumerate(raw[i] - floors[i] for i in range(n)),
        key=lambda x: (-x[1], x[0]),
    )
    counts = floors[:]
    deficit = total_words - sum(counts)
    for j in range(deficit):
        counts[remainders[j][0]] += 1

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
