# Autopilot learnings

Rules distilled from outcomes. The patrol rewrites this file after each run.
Each rule cites evidence (PR/issue). Max ~40 rules; merge or drop stale ones.
These rules can only make the patrol MORE conservative than AUTOPILOT.md, never less.

## Keep doing

## Avoid

## Maintainer instructions (verbatim from review comments)

## Notes
- mode: report has produced the same findings for 6 consecutive runs (2026-10-14 through 2026-10-19) with no code changes possible by design. See final-message history or ledger.jsonl for the standing list: #37/#38/#39/#40, README/docs.architecture.md MIT-vs-AGPL contradiction, PR #41/#42 orphaned by a main history rewrite around 2026-08-10, and CI stuck on an unregistered self-hosted runner (`haven`) since 2026-09-10. None of this needs a new rule - AUTOPILOT.md's `mode: report` is presumably deliberate - but it means the backlog will only move if the maintainer flips to `pr` mode or acts directly.
