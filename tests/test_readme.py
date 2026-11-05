"""PyPI shows the README away from the repo, so these failures would ship permanently."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"


def test_readme_links_work_outside_the_repo():
    targets = re.findall(r"\]\(([^)]+)\)", README.read_text(encoding="utf-8"))
    relative = [t for t in targets if not t.startswith(("https://", "http://", "#", "mailto:"))]
    assert relative == []


def _tool_status():
    spec = importlib.util.spec_from_file_location(
        "tool_status", ROOT / "scripts" / "tool_status.py"
    )
    tool_status = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool_status)
    return tool_status


def test_readme_tool_counts_match_the_baselines():
    text = README.read_text(encoding="utf-8")
    assert _tool_status().render(text) == text, (
        "README.md is stale: run python scripts/tool_status.py"
    )


def test_a_tool_that_only_reached_the_disabled_network_does_not_count_as_working():
    # A valid call classed EXPECTED stopped at the harness network block, so it never ran.
    states = _tool_status().tool_states(
        {
            "offline#minimal": "EXPECTED",
            "offline#invalid": "EXPECTED",
            "ran#minimal": "PASS",
            "ran#enum:mode=B": "EXPECTED",
            "ran#invalid": "EXPECTED",
        }
    )
    assert states == {"offline": "offline", "ran": "pass"}


LANE = {
    "4.2": {"a": "PASS", "sculpt_x": "FAIL"},
    "4.5": {"a": "PASS", "reply_16mb_complete": "FAIL"},
    "5.2": {"a": "PASS", "reply_16mb_complete": "FAIL"},
}


def test_lane_failures_list_every_series_they_were_recorded_on():
    assert _tool_status().lane_failures(LANE) == {
        "reply_16mb_complete": ["4.5", "5.2"],
        "sculpt_x": ["4.2"],
    }


def test_a_nightly_only_lane_failure_reaches_the_readme_text():
    ts = _tool_status()
    known = ts.lane_sentence(ts.lane_failures(LANE), LANE)
    assert "`sculpt_x` (on 4.2)" in known
    assert "`reply_16mb_complete` (on 4.5, 5.2)" in known


def test_a_check_failing_on_every_lane_series_says_so():
    ts = _tool_status()
    lane = {"4.5": {"x": "FAIL"}, "5.2": {"x": "FAIL"}}
    assert ts.lane_sentence(ts.lane_failures(lane), lane) == (
        "Socket checks that still fail: `x` (on every series)."
    )


def test_the_lane_note_names_the_gated_and_the_nightly_series():
    ts = _tool_status()
    lane = {s: {} for s in ("4.2", "4.3", "4.4", "4.5", "5.0", "5.1", "5.2")}
    assert ts.lane_note(lane) == (
        "Where a reason names the socket lane, it runs on Blender 4.5 and 5.2 on every pull"
        " request, and on 4.2, 4.3, 4.4, 5.0 and 5.1 nightly, best effort."
    )


def test_the_lane_note_follows_the_series_the_lane_really_ran_on():
    ts = _tool_status()
    note = ts.lane_note({"4.5": {}, "5.2": {}})
    assert "nightly" not in note
    assert "4.5 and 5.2 on every pull request" in note


def test_the_readme_names_the_lane_series_wherever_a_row_leans_on_the_lane():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    if any("socket" in line.lower() and line.startswith("| `") for line in text.splitlines()):
        assert "Where a reason names the socket lane, it runs on Blender" in text
