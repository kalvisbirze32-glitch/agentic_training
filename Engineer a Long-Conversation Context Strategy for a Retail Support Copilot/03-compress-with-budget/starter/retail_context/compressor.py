"""Tiered compression: summarize resolved segments; preserve active verbatim.

Resolved segments are condensed by a single Claude call per segment using the
prompt template at `retail_context/prompts/compression_prompt.md`. The active
segment is **never** summarized — it is preserved byte-exact.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

from retail_context.client import complete_with_system
from retail_context.transcript import Segment, Transcript


@dataclass
class Summary:
    issue_id: str
    text: str
    input_tokens: int
    output_tokens: int


@dataclass
class Compressed:
    summaries: dict[str, Summary]
    active_text: str
    active_issue_id: str


def _load_prompt() -> str:
    return resources.files("retail_context.prompts").joinpath(
        "compression_prompt.md"
    ).read_text()


def summarize_segment(segment: Segment, *, model: str | None = None) -> Summary:
    if segment.status != "resolved":
        raise ValueError(
            f"Cannot summarize segment `{segment.issue_id}` (status={segment.status!r}): "
            "only resolved segments are compressed; an active segment must be "
            "kept byte-exact."
        )

    first_turn, last_turn = segment.turn_range
    user_message = (
        f"Source segment — issue_id `{segment.issue_id}`, "
        f"turns {first_turn}-{last_turn}:\n\n{segment.text}"
    )
    text, tokens_in, tokens_out = complete_with_system(
        _load_prompt(), user_message, model=model, max_tokens=1024
    )
    return Summary(
        issue_id=segment.issue_id,
        text=text,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
    )


def compress(transcript: Transcript, *, model: str | None = None) -> Compressed:
    summaries: dict[str, Summary] = {}
    active_text: str | None = None
    active_issue_id: str | None = None

    for seg in transcript.segments:
        if seg.status == "resolved":
            summaries[seg.issue_id] = summarize_segment(seg, model=model)
        elif seg.status == "active":
            # Rendered, never summarized: this text must stay byte-exact.
            active_text = "\n\n".join(turn.render() for turn in seg.turns)
            active_issue_id = seg.issue_id

    if active_text is None or active_issue_id is None:
        raise RuntimeError(
            "Transcript has no active segment; the assembled context needs "
            "exactly one active segment to place at the bottom boundary."
        )

    return Compressed(
        summaries=summaries,
        active_text=active_text,
        active_issue_id=active_issue_id,
    )
