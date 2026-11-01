"""Classify a case outcome from the in-Blender runner."""

from __future__ import annotations

NETWORK_SENTINEL = "harness: network disabled"
CODE_BUG_TYPES = {"ImportError", "AttributeError", "TypeError", "NameError"}


def _soft_fail(result) -> bool:
    return isinstance(result, dict) and ("error" in result or result.get("success") is False)


def classify(case_pass: str, outcome: dict | None) -> str:
    if outcome is None:
        return "CRASH"
    status = outcome.get("status")
    if status == "hang":
        return "HANG"
    if status == "ok":
        if case_pass == "invalid":
            return "BUG"
        return "SOFT_FAIL" if _soft_fail(outcome.get("result")) else "PASS"
    if NETWORK_SENTINEL in str(outcome.get("message", "")):
        return "EXPECTED"
    exc = outcome.get("type")
    if case_pass == "invalid":
        return "EXPECTED" if exc == "ValidationError" else "BUG"
    return "BUG"
