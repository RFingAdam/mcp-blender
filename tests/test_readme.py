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
