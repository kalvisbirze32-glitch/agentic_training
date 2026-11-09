"""Anti-pattern audit.

Verifies, by static AST analysis, that the agentic loop does NOT:
- use string-membership tests against text content to drive control flow
- use an integer-literal iteration cap as its primary stopping mechanism
- omit reference to `stop_reason` as the loop-breaking signal

And that the package broadly does not branch on `claim_type` equality
outside of the tool-schema definitions and the cost-estimate module.

Each test parses the relevant file with `ast` and walks the tree. There are
no runtime imports of claims_intake here — the audit is static, so it works
even if loop.py / tools.py do not run end-to-end.
"""

from __future__ import annotations

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "claims_intake"
LOOP_PY = PKG / "loop.py"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


# ---------------------------------------------------------------------------
# Anti-pattern 1 — no string-membership tests against assistant text in the loop
# ---------------------------------------------------------------------------
def test_no_string_membership_against_text_in_loop() -> None:
    """No `"some_token" in <something>` expressions in loop.py.

    Heuristic: any `ast.Compare` node using `ast.In` whose `left` operand is a
    string `ast.Constant` is flagged. The loop has no legitimate reason to test
    for the presence of a magic string inside the model's output — that would be
    natural-language-driven control flow.
    """
    tree = _parse(LOOP_PY)
    offenders = [
        f"line {node.lineno}: {ast.unparse(node)}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(isinstance(op, ast.In) for op in node.ops)
        and isinstance(node.left, ast.Constant)
        and isinstance(node.left.value, str)
    ]
    assert not offenders, (
        "String-membership tests found in loop.py (natural-language control flow): "
        + "; ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Anti-pattern 2 — no integer-literal iteration cap as the primary stop mechanism
# ---------------------------------------------------------------------------
def test_no_integer_literal_iteration_cap_in_loop() -> None:
    """No `for _ in range(<int literal>)` and no `while <var> < <int literal>` in loop.py.

    Token/wall-clock/config-sourced budgets are explicitly allowed because they
    read their cap from a `Budget` instance (an attribute access or a function
    arg), not from a literal. If you need a cap, pass it in.
    """
    def _is_int_literal(node: ast.expr) -> bool:
        return (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int)
            and not isinstance(node.value, bool)
        )

    tree = _parse(LOOP_PY)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.For)
            and isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Name)
            and node.iter.func.id == "range"
            and any(_is_int_literal(arg) for arg in node.iter.args)
        ):
            offenders.append(f"line {node.lineno}: for ... in {ast.unparse(node.iter)}")
        elif (
            isinstance(node, ast.While)
            and isinstance(node.test, ast.Compare)
            and any(_is_int_literal(c) for c in node.test.comparators)
        ):
            offenders.append(f"line {node.lineno}: while {ast.unparse(node.test)}")
    assert not offenders, (
        "Integer-literal iteration caps found in loop.py; use a Budget instead: "
        + "; ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Positive evidence — stop_reason is the value that breaks the while loop
# ---------------------------------------------------------------------------
def test_stop_reason_is_loop_control() -> None:
    """loop.py references `stop_reason` AND a `while` loop exits via return/raise on it."""
    tree = _parse(LOOP_PY)
    refs_stop_reason = any(
        (isinstance(n, ast.Attribute) and n.attr == "stop_reason")
        or (isinstance(n, ast.Name) and n.id == "stop_reason")
        for n in ast.walk(tree)
    )
    assert refs_stop_reason, "loop.py never references stop_reason"

    def _exits_on_stop_reason(loop: ast.While) -> bool:
        body = "\n".join(ast.unparse(stmt) for stmt in loop.body)
        has_exit = any(isinstance(n, (ast.Return, ast.Raise)) for stmt in loop.body for n in ast.walk(stmt))
        return "stop_reason" in body and has_exit

    whiles = [n for n in ast.walk(tree) if isinstance(n, ast.While)]
    assert any(_exits_on_stop_reason(w) for w in whiles), (
        "No `while` loop in loop.py both references stop_reason and exits via return/raise"
    )


# ---------------------------------------------------------------------------
# Decision-tree-in-Python — no `if claim_type == "..."` branches in the package
# ---------------------------------------------------------------------------
def test_no_claim_type_equality_branching_in_package() -> None:
    """Decision logic about claim type lives in the model, not in Python.

    tools.py is exempt (it defines the enum in input_schema).
    pricing.py is exempt (it may map claim_type to per-queue cost weights).
    """
    def _is_claim_type(node: ast.expr) -> bool:
        return (isinstance(node, ast.Name) and node.id == "claim_type") or (
            isinstance(node, ast.Attribute) and node.attr == "claim_type"
        )

    def _is_str_const(node: ast.expr) -> bool:
        return isinstance(node, ast.Constant) and isinstance(node.value, str)

    exempt = {"tools.py", "pricing.py", "__init__.py"}
    offenders: list[str] = []
    for path in sorted(PKG.rglob("*.py")):
        if path.name in exempt:
            continue
        for node in ast.walk(_parse(path)):
            if not isinstance(node, ast.Compare) or not any(isinstance(op, ast.Eq) for op in node.ops):
                continue
            operands = [node.left, *node.comparators]
            if any(_is_claim_type(o) for o in operands) and any(_is_str_const(o) for o in operands):
                offenders.append(f"{path.name}:{node.lineno}: {ast.unparse(node)}")
    assert not offenders, (
        "claim_type equality branching found; move the decision into the model via tool calls: "
        + "; ".join(offenders)
    )
