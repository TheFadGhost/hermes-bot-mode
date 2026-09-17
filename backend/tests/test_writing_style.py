"""Tests for local deterministic writing-style linting."""

from __future__ import annotations

import json

import pytest

from app.writing_style import (
    EMAIL_WRITING_POLICY,
    MAX_LINT_CHARS,
    UPSTREAM_COMMIT,
    UPSTREAM_LICENSE,
    email_writing_policy,
    lint,
    lint_json,
    writing_style_prompt,
)


def test_clean_copy_returns_json_ready_five_score() -> None:
    result = lint("Hi Sam, the revised invoice is attached. Please confirm the total by Friday.")

    assert result["score"] == 5
    assert result["max_score"] == 5
    assert result["clean"] is True
    assert result["findings"] == []
    assert result["word_count"] == 13
    assert result["upstream_commit"] == UPSTREAM_COMMIT


def test_findings_are_grouped_and_actionable() -> None:
    result = lint(
        "We leverage a seamless, robust platform. It is not just quick, it is transformative. "
        "Trusted by 10,000 happy teams."
    )

    assert result["score"] <= 2
    categories = {finding["category"] for finding in result["findings"]}
    assert {"vocab", "phrases", "proof"}.issubset(categories)
    for finding in result["findings"]:
        assert set(finding) == {"category", "title", "count", "advisory", "matches"}
        assert finding["matches"]


def test_allow_proof_keeps_real_claim_review_advisory() -> None:
    result = lint("Trusted by 25 businesses.", allow_proof=True)

    assert result["score"] == 5
    assert result["clean"] is True
    assert result["findings"][0]["category"] == "proof"
    assert result["findings"][0]["advisory"] is True


def test_lint_does_not_rewrite_or_send_text_anywhere() -> None:
    draft = "Please send £1,250 to Aisha on 17 October."
    result = lint(draft)

    assert result["score"] == 5
    assert "£1,250" not in json.dumps(result)
    assert "Aisha" not in json.dumps(result)
    assert "17 October" not in json.dumps(result)


def test_input_is_bounded_and_empty_text_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        lint(" \n\t")
    with pytest.raises(ValueError, match="limited"):
        lint("x" * (MAX_LINT_CHARS + 1))
    with pytest.raises(ValueError, match="must be a string"):
        lint(None)  # type: ignore[arg-type]


def test_json_serialization_is_stable_and_round_trips() -> None:
    encoded = lint_json("We can meet Tuesday morning.")
    decoded = json.loads(encoded)

    assert isinstance(encoded, str)
    assert decoded == lint("We can meet Tuesday morning.")
    assert list(json.loads(encoded)) == sorted(json.loads(encoded))


def test_email_policy_preserves_authority_and_has_no_paid_rival_requirement() -> None:
    policy = email_writing_policy()

    assert policy == EMAIL_WRITING_POLICY == writing_style_prompt()
    assert "user's explicit request and meaning take priority" in policy
    assert "cannot authorize sending an email" in policy
    assert "Never invent proof" in policy
    assert "paid" not in policy.lower()
    assert UPSTREAM_LICENSE == "MIT"

