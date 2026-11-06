"""Print one version's section of CHANGELOG.md, for the GitHub release notes.

Usage: python3 scripts/changelog_section.py 0.5.0 < CHANGELOG.md

Prints the lines under "## [<version>]" up to the next "## [" heading, without the heading
and without leading or trailing blank lines. Prints nothing, and says so on stderr, when the
version has no section, so the release still gets its generated notes.
"""

import sys


def section(text: str, version: str) -> str:
    heading = f"## [{version}]"
    lines: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## ["):
            if inside:
                break
            inside = line.startswith(heading)
            continue
        if inside:
            lines.append(line)
    return "\n".join(lines).strip("\n")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    found = section(sys.stdin.read(), sys.argv[1])
    if not found:
        print(f"CHANGELOG.md has no section for {sys.argv[1]}", file=sys.stderr)
        return 0
    print(found)
    return 0


if __name__ == "__main__":
    sys.exit(main())
