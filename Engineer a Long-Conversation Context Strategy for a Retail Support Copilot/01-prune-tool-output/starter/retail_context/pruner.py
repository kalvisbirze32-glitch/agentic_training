"""Deterministic tool-output pruning for the verbose `lookup_order` response.

The "Tool Context Pruning" pattern: application-side filtering
of a verbose tool result so only the fields needed for the immediate decision survive
into context. For return/refund reasoning, exactly five fields matter — order identity,
when it was placed, what it cost, whether it shipped, and the return-window deadline.

Why each kept field earns its place in the return/refund decision:
  - `order_id`: names the order being discussed, so every follow-up action
    (refund call, note to the customer) targets the right record.
  - `order_date`: the starting point for any "within N days" return policy.
  - `order_total_usd`: the ceiling on what can be refunded; a refund above the
    amount paid is never valid.
  - `fulfillment_status`: decides the path — a delivered order needs a return,
    an order still in flight can simply be cancelled.
  - `return_eligible_until`: the precomputed cutoff the agent compares with
    today's date to answer "is this still returnable?" directly.

Implementation: deterministic field selection (no LLM call). The pruner has no
`anthropic` import — enforced by an AST audit.
"""
from __future__ import annotations

KEPT_FIELDS: tuple[str, ...] = (
    "order_id",
    "order_date",
    "order_total_usd",
    "fulfillment_status",
    "return_eligible_until",
)


class PrunerMissingFieldError(KeyError):
    """Raised when the raw tool response is missing one of the required kept fields."""


def prune_lookup_order(raw: dict) -> dict:
    absent = [name for name in KEPT_FIELDS if name not in raw]
    if absent:
        raise PrunerMissingFieldError(
            f"lookup_order payload lacks required field(s): {', '.join(absent)}"
        )
    # Building from KEPT_FIELDS (not iterating raw) fixes the output key order.
    return {name: raw[name] for name in KEPT_FIELDS}
