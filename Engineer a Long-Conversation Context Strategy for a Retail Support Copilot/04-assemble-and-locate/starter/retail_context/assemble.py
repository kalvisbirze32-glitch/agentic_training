"""Position-aware context assembly.

Layout (top → bottom):
  # Case Facts                       — top boundary, structured (≤ 600 tokens)
  # Resolved: Refund inquiry         — middle, compressible zone (≤ 500 tokens)
  # Resolved: Subscription cancellation — middle, compressible zone (≤ 500 tokens)
  # Active issue: Payment-method update — bottom boundary, byte-exact verbatim

This places key findings at both context boundaries (Case Facts at top, the
active turn-by-turn at bottom against the new user turn) and lets the resolved
narrative occupy the lower-attention middle. Sections are exclusive — no
interleaving.
"""
from __future__ import annotations

from dataclasses import dataclass

from retail_context.case_facts import CaseFacts
from retail_context.compressor import Compressed
from retail_context.tokens import count

RESOLVED_TITLES: dict[str, str] = {
    "refund": "# Resolved: Refund inquiry",
    "subscription": "# Resolved: Subscription cancellation",
}
ACTIVE_TITLES: dict[str, str] = {
    "payment_update": "# Active issue: Payment-method update",
}


@dataclass
class AssembledContext:
    markdown: str
    case_facts_block: str
    resolved_blocks: dict[str, str]
    active_block: str
    active_raw_text: str  # byte-exact verbatim source for the active segment

    def section_tokens(self) -> dict[str, int]:
        sections = {"case_facts": count(self.case_facts_block)}
        for issue_id, block in self.resolved_blocks.items():
            sections[f"resolved_{issue_id}"] = count(block)
        sections["active"] = count(self.active_block)
        return sections

    def total_tokens(self) -> int:
        return count(self.markdown)


_RESOLVED_ORDER = ("refund", "subscription")


def build(case_facts: CaseFacts, compressed: Compressed) -> AssembledContext:
    # Top boundary: structured case facts, normalised to one trailing newline.
    facts_block = case_facts.to_markdown().rstrip("\n") + "\n"

    # Middle: resolved summaries in the fixed refund -> subscription order.
    resolved_blocks: dict[str, str] = {}
    for issue_id in _RESOLVED_ORDER:
        summary = compressed.summaries.get(issue_id)
        if summary is None:
            raise KeyError(f"compressed context has no summary for resolved issue '{issue_id}'")
        resolved_blocks[issue_id] = f"{RESOLVED_TITLES[issue_id]}\n\n{summary.text.strip()}\n"

    # Bottom boundary: the active text goes in untouched (no strip / re-render).
    active_title = ACTIVE_TITLES.get(
        compressed.active_issue_id, f"# Active issue: {compressed.active_issue_id}"
    )
    active_block = f"{active_title}\n\n{compressed.active_text}\n"

    markdown = "\n".join([facts_block, *resolved_blocks.values(), active_block])

    return AssembledContext(
        markdown=markdown,
        case_facts_block=facts_block,
        resolved_blocks=resolved_blocks,
        active_block=active_block,
        active_raw_text=compressed.active_text,
    )
