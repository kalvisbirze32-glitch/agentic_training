"""Case-facts extraction into a persistent block at the top of context.

Extraction is LLM-driven: one Claude call against the full transcript that returns
strict JSON for the 12 required fields. This is commonly called a *scratchpad* — same
concept, different word: a dense structured block that survives compression and is
placed at the top boundary of context so the model can recover transactional facts
without scanning thousands of tokens of narrative.

Missing-field behavior raises `CaseFactExtractionError` listing the gaps — silent
null-fill is forbidden.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from retail_context.client import complete_with_system, get_model
from retail_context.transcript import Transcript

REQUIRED_FIELDS: tuple[str, ...] = (
    "customer_id",
    "refund_order_id",
    "refund_amount_usd",
    "refund_status",
    "subscription_id",
    "subscription_plan",
    "subscription_cancel_reason",
    "subscription_status",
    "active_payment_method_last4",
    "new_payment_method_last4",
    "payment_update_failure_code",
    "payment_update_status",
)


@dataclass
class CaseFacts:
    customer_id: str
    refund_order_id: str
    refund_amount_usd: float
    refund_status: str
    subscription_id: str
    subscription_plan: str
    subscription_cancel_reason: str
    subscription_status: str
    active_payment_method_last4: str
    new_payment_method_last4: str
    payment_update_failure_code: str
    payment_update_status: str

    def to_markdown(self) -> str:
        sections = [
            ("Customer", [("customer_id", self.customer_id)]),
            (
                "Refund (resolved)",
                [
                    ("refund_order_id", self.refund_order_id),
                    ("refund_amount_usd", f"${self.refund_amount_usd:.2f}"),
                    ("refund_status", self.refund_status),
                ],
            ),
            (
                "Subscription (resolved)",
                [
                    ("subscription_id", self.subscription_id),
                    ("subscription_plan", self.subscription_plan),
                    ("subscription_cancel_reason", self.subscription_cancel_reason),
                    ("subscription_status", self.subscription_status),
                ],
            ),
            (
                "Payment update (active)",
                [
                    ("active_payment_method_last4", self.active_payment_method_last4),
                    ("new_payment_method_last4", self.new_payment_method_last4),
                    ("payment_update_failure_code", self.payment_update_failure_code),
                    ("payment_update_status", self.payment_update_status),
                ],
            ),
        ]
        blocks = ["# Case Facts"]
        for label, rows in sections:
            lines = [f"**{label}**"] + [f"- `{k}`: {v}" for k, v in rows]
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks) + "\n"


class CaseFactExtractionError(ValueError):
    def __init__(self, missing: list[str], raw: dict[str, Any]):
        super().__init__(f"case-facts extraction missing required fields: {missing}")
        self.missing = missing
        self.raw = raw


_SYSTEM_PROMPT = """Your job is to read a customer-support transcript and pull out a fixed set of
facts as machine-readable JSON. The customer talks to the retailer "Pantry Plus" about
three separate matters: a refund (finished), a subscription cancellation (finished),
and a payment-method update that is still open.

Reply with a single JSON object that has precisely the twelve keys below, each with the
stated type. No other keys.

  customer_id                  string  - the customer account ID
  refund_order_id              string  - the order the refund was issued for
  refund_amount_usd            number  - refunded amount as a plain number, e.g. 48.99
  refund_status                string  - final state of the refund
  subscription_id              string  - the subscription that was cancelled
  subscription_plan            string  - plan name of that subscription
  subscription_cancel_reason   string  - the reason recorded for the cancellation
  subscription_status          string  - final state of the subscription
  active_payment_method_last4  string  - last 4 digits of the card currently on file
  new_payment_method_last4     string  - last 4 digits of the card being added
  payment_update_failure_code  string  - the error code the payment update hit
  payment_update_status        string  - current state of the payment update

Requirements:
1. All twelve keys must be present. When the transcript does not state a value, use
   JSON null for it. Never guess, infer or make up a value.
2. Copy IDs, plan names and error codes exactly as written in the transcript.
3. Status and reason values that look like snake_case tokens must stay in that exact
   form; do not rephrase them in plain English.
4. Card digits are strings, so keep any leading zero (e.g. "0421").
5. refund_amount_usd must be numeric: drop the "$" sign and any quotes.
6. Your entire reply is the JSON object - no explanation, no Markdown, no code fence."""


def _parse_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.rstrip().endswith("```"):
            raw = raw.rsplit("```", 1)[0]
    return json.loads(raw)


def extract(
    transcript: Transcript,
    *,
    model: str | None = None,
    log_path: Path | None = None,
) -> CaseFacts:
    user_message = f"Transcript:\n\n{transcript.full_text}"
    reply, tokens_in, tokens_out = complete_with_system(
        _SYSTEM_PROMPT, user_message, model=model, max_tokens=2048
    )
    parsed = _parse_json(reply)

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        audit = {
            "model": model or get_model(),
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "raw_output": parsed,
        }
        log_path.write_text(json.dumps(audit, indent=2))

    # Absent, null and empty-string values all count as missing; never null-fill.
    missing = [name for name in REQUIRED_FIELDS if parsed.get(name) in (None, "")]
    if missing:
        raise CaseFactExtractionError(missing=missing, raw=parsed)

    values: dict[str, Any] = {name: str(parsed[name]) for name in REQUIRED_FIELDS}
    values["refund_amount_usd"] = float(parsed["refund_amount_usd"])
    return CaseFacts(**values)


def to_dict(facts: CaseFacts) -> dict[str, Any]:
    return asdict(facts)
