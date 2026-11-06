"""The release notes come from CHANGELOG.md through scripts/changelog_section.py."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "changelog_section", ROOT / "scripts" / "changelog_section.py"
)
changelog_section = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(changelog_section)
section = changelog_section.section

SAMPLE = """# Changelog

## [Unreleased]

## [1.1.0] - 2026-01-02

### Security

First line.

- item

## [1.1.0a1] - 2026-01-01

Alpha.

## [1.0.0]

Old.
"""


def test_section_stops_at_the_next_version_and_skips_its_own_heading():
    assert section(SAMPLE, "1.1.0") == "### Security\n\nFirst line.\n\n- item"


def test_a_prerelease_heading_is_not_taken_for_the_stable_one():
    assert section(SAMPLE, "1.1.0a1") == "Alpha."
    assert "Alpha." not in section(SAMPLE, "1.1.0")


def test_unknown_or_empty_sections_give_nothing():
    assert section(SAMPLE, "9.9.9") == ""
    assert section(SAMPLE, "Unreleased") == ""


def test_the_current_version_has_a_section_that_opens_with_security():
    from mcp_blender import __version__

    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = section(text, __version__)
    assert notes.startswith("### Security")
    assert "## [" not in notes
