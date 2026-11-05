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


def test_readme_tool_counts_match_the_baselines():
    spec = importlib.util.spec_from_file_location(
        "tool_status", ROOT / "scripts" / "tool_status.py"
    )
    tool_status = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool_status)
    text = README.read_text(encoding="utf-8")
    assert tool_status.render(text) == text, "README.md is stale: run python scripts/tool_status.py"
