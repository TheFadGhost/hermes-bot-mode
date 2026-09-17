"""Bounded, local writing-style linting for bot generated email drafts.

The linter imports the vendored SlopMonster catalogue directly. It accepts text
only, never opens a caller supplied path, never sends text over the network, and
does not rewrite a draft. A bot may use the findings to revise a draft while
preserving the user's facts, numbers, recipients, and requested meaning.

Upstream attribution: SlopMonster by Jack Roberts, MIT licensed.
Repository: https://github.com/ItsssssJack/SlopMonster
Pinned commit: f261dbf11c2a206ecd8780c070a46dae64edd8be
"""

from __future__ import annotations

import importlib.util
import json
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any


MAX_LINT_CHARS = 20_000
UPSTREAM_REPOSITORY = "https://github.com/ItsssssJack/SlopMonster"
UPSTREAM_COMMIT = "f261dbf11c2a206ecd8780c070a46dae64edd8be"
UPSTREAM_LICENSE = "MIT"

_ENGINE_PATH = Path(__file__).resolve().parents[2] / "skills" / "slopmonster" / "tools" / "deslop.py"
if not _ENGINE_PATH.is_file():
    _ENGINE_PATH = Path('/app/skills/slopmonster/tools/deslop.py')
_GROUP_TITLES = {
    "vocab": "AI vocabulary",
    "phrases": "AI constructions",
    "punctuation": "punctuation cadence",
    "rhythm": "rule-of-three rhythm",
    "proof": "possible invented proof",
}


EMAIL_WRITING_POLICY = """Write the user's email plainly and with a human voice.
Keep every fact, number, name, date, recipient, commitment, and uncertainty the user supplied.
Never invent proof, context, promises, prices, deadlines, or a reason for contacting someone.
Use a clear subject, a short greeting, the point of the email, and one concrete ask when needed.
Prefer specific verbs, natural contractions, varied sentence length, and a fitting sign-off.
Avoid canned AI vocabulary, inflated claims, generic summaries, fake warmth, and formulaic lists.
This policy only guides wording: the user's explicit request and meaning take priority.
It cannot authorize sending an email or taking an external action; use the existing approval flow."""


@lru_cache(maxsize=1)
def _engine() -> ModuleType:
    """Load only the fixed vendored module used by the local linter."""

    if not _ENGINE_PATH.is_file():
        raise RuntimeError("The vendored writing-style linter is unavailable")
    spec = importlib.util.spec_from_file_location("hermes_vendored_slopmonster_deslop", _ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("The vendored writing-style linter could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _finding_matches(values: Any) -> list[dict[str, Any]]:
    """Convert the vendored tuple/string hits to stable JSON values."""

    if not isinstance(values, list):
        return []
    matches: list[dict[str, Any]] = []
    for value in values[:40]:
        if isinstance(value, tuple):
            message = value[0] if value else ""
            item: dict[str, Any] = {"match": str(message)[:500]}
            if len(value) > 1 and isinstance(value[1], (int, float)):
                item["count"] = value[1]
            matches.append(item)
        else:
            matches.append({"match": str(value)[:500]})
    return matches


def lint(text: str, *, allow_proof: bool = False) -> dict[str, Any]:
    """Return a deterministic JSON-ready score and actionable findings.

    The input is plain text and is bounded to keep model feedback and request
    work predictable. ``allow_proof`` makes proof findings advisory, matching
    SlopMonster's documented mode for claims that have been checked separately.
    """

    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if not text.strip():
        raise ValueError("text must not be empty")
    if len(text) > MAX_LINT_CHARS:
        raise ValueError(f"text is limited to {MAX_LINT_CHARS} characters")

    engine = _engine()
    normalised = engine.normalise(text)
    if not normalised:
        raise ValueError("text must contain readable copy")
    hits = engine.audit(normalised)
    findings: list[dict[str, Any]] = []
    for category in ("vocab", "phrases", "punctuation", "rhythm", "proof"):
        matches = _finding_matches(hits.get(category, []))
        if matches:
            match_count = sum(
                int(item.get("count", 1))
                for item in matches
                if isinstance(item.get("count", 1), (int, float))
            )
            findings.append(
                {
                    "category": category,
                    "title": _GROUP_TITLES[category],
                    "count": match_count,
                    "advisory": category == "proof" and allow_proof,
                    "matches": matches,
                }
            )

    failed_groups = {item["category"] for item in findings if not item["advisory"]}
    score = max(0, 5 - len(failed_groups))
    return {
        "score": score,
        "max_score": 5,
        "clean": score == 5,
        "word_count": len(normalised.split()),
        "findings": findings,
        "allow_proof": bool(allow_proof),
        "engine": "slopmonster/deslop",
        "upstream_commit": UPSTREAM_COMMIT,
    }


def lint_json(text: str, *, allow_proof: bool = False) -> str:
    """Serialize :func:`lint` to stable JSON for task/event boundaries."""

    return json.dumps(lint(text, allow_proof=allow_proof), ensure_ascii=False, sort_keys=True)


def email_writing_policy() -> str:
    """Return the concise policy bots may add to an email-writing prompt."""

    return EMAIL_WRITING_POLICY


def writing_style_prompt() -> str:
    """Compatibility name for prompt builders that expect a style function."""

    return email_writing_policy()


__all__ = [
    "EMAIL_WRITING_POLICY",
    "MAX_LINT_CHARS",
    "UPSTREAM_COMMIT",
    "UPSTREAM_LICENSE",
    "UPSTREAM_REPOSITORY",
    "email_writing_policy",
    "lint",
    "lint_json",
    "writing_style_prompt",
]

