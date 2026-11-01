"""PyPI shows the README away from the repo, so these failures would ship permanently."""

import re
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"


def test_readme_links_work_outside_the_repo():
    targets = re.findall(r"\]\(([^)]+)\)", README.read_text(encoding="utf-8"))
    relative = [t for t in targets if not t.startswith(("https://", "http://", "#", "mailto:"))]
    assert relative == []
