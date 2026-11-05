"""Classify a case outcome from the in-Blender runner."""

from __future__ import annotations

import re

from .fixtures import EXPECTED_SOFT_FAILS

NETWORK_SENTINEL = "harness: network disabled"


def _soft_fail(result) -> bool:
    return isinstance(result, dict) and (result.get("error") or result.get("success") is False)


def _sentinel_error(result) -> bool:
    return (
        isinstance(result, dict)
        and bool(result.get("error"))
        and NETWORK_SENTINEL in str(result["error"])
    )


def _message(result) -> str:
    """The error text of a failed result, or its message when it names no error."""
    return str(result.get("error") or result.get("message") or "")


def _expected_soft_fail(tool: str | None, result) -> bool:
    """False only when the tool has a row and the failure is not the one the row names."""
    row = EXPECTED_SOFT_FAILS.get(tool)
    return row is None or re.search(row.pattern, _message(result)) is not None


def classify(case_pass: str, outcome: dict | None, tool: str | None = None) -> str:
    if outcome is None:
        return "CRASH"
    status = outcome.get("status")
    if status == "hang":
        return "HANG"
    if status == "ok":
        if _sentinel_error(outcome.get("result")):
            return "EXPECTED"
        if case_pass == "invalid":
            return "BUG"
        result = outcome.get("result")
        if not _soft_fail(result):
            return "PASS"
        return "SOFT_FAIL" if _expected_soft_fail(tool, result) else "BUG"
    if outcome.get("type") == "SystemExit":
        return "CRASH"
    if NETWORK_SENTINEL in str(outcome.get("message", "")):
        return "EXPECTED"
    exc = outcome.get("type")
    if case_pass == "invalid":
        return "EXPECTED" if exc == "ValidationError" else "BUG"
    return "BUG"
