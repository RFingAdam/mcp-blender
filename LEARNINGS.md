# Autopilot learnings

Rules distilled from outcomes. The patrol rewrites this file after each run.
Each rule cites evidence (PR/issue). Max ~40 rules; merge or drop stale ones.
These rules can only make the patrol MORE conservative than AUTOPILOT.md, never less.

## Keep doing

## Avoid

## Maintainer instructions (verbatim from review comments)

## Notes
- mode: report has produced the same findings for 8 consecutive runs (2026-10-14 through 2026-10-21) with no code changes possible by design. See final-message history or ledger.jsonl for the standing list: #37/#38/#39/#40, README/docs.architecture.md MIT-vs-AGPL contradiction, PR #41/#42 orphaned by a main history rewrite around 2026-08-10, and CI stuck on an unregistered self-hosted runner (`haven`) from 2026-09-10 (resolved 2026-10-21 by #45, back on GitHub-hosted runners; main CI green). None of this needs a new rule - AUTOPILOT.md's `mode: report` is presumably deliberate - but it means the backlog will only move if the maintainer flips to `pr` mode or acts directly.
- 2026-10-21: #39 is worse than its title says. At the 20 swapped call sites in mesh_editing.py (AST count; earlier runs counted 25-26 by grep), `allowed` becomes a string such as "type". That iterates to single characters, so every valid input is rejected and those tools fail on every call. No test covers validate_enum call order. Count with an AST check, not grep.
- 2026-10-22: CI (.github/workflows/ci.yml) runs `ruff check` but not `ruff format --check`, so the 56-file format drift never shows red. AUTOPILOT.md lists format --check as a check: treat it as pre-existing baseline drift, not a regression, and don't try to fix it in one PR (far over max_diff_lines).
