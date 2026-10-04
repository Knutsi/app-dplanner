# Remediation, offered as waves

**Summary.** Six waves, each made of PR-sized items. Wave 1 needs no decision. Waves 2–3 are
the `planning/` tier plus the hybrid; the tier with kinds and status is the pilot. Wave 4 is renaming. Wave 5 is
docs. Wave 6 is groundwork for the daemon and the server. Nothing here is committed to yet.

| Wave | What | Size | Depends on |
|---|---|---|---|
| 1 Hygiene and bugs | Delete the ghost directories. Fix `write_atomic` and `set_checkout` (with two-writer tests). Replace copied literals with constants. Add `is_milestone()`. One `spawn_detached()` with the Windows flags. Fix stale docstrings and drop two dead `HEADLESS_FILES` names. | ~7 small PRs | — |
| 2 The `planning/` tier (the pilot) | Create `planning/` with `kinds.py` (one ordered list replaces `_step_key`, `_step_kind`, `_primary_glyph`, the body tone and the `_scope_kinds` order) and `status.py` (a state machine, plus the three named meanings of "done"). Move the kind aspects' `aspect.py` down. Add the layer rule and the admission test. | 3–4 PRs | 1 |
| 3 Narrow the root | Move estimation, waits and the review workflow into `planning/`, with `schedule`, `progression` and `scope` moving up out of `domain/`. Then adopt the headless-import rule and its test. Move the clusters: `agent_briefing`, `branches/plan.py`, `coverage/trace.py`, milestone colours to the schedule, ledger helpers to `agent_usage`, `due_now` to `agent_launch`. Split `default_modules()` per cluster. Ratchet a line ceiling on the root. | ~6 PRs | 2 |
| 4 Names | The seven renames in renaming.md, the file-role names, test folders per package, `HEADLESS_FILES` per package. | ~8 PRs | 3 (moves first) |
| 5 Docs | NOTES-FOR-APPFRAME per framework file (current divergence only). ARCHITECTURE.md split per rule area, with a dated `decisions.md` for history. *Mechanical facts* into the rules files. | 3 PRs | any |
| 6 Groundwork for the daemon and the server | A per-project flush lock. A headless claim lease. Auto-launch's decision out of Qt. No migration writes on load, plus a minimum-reader stamp. Store slots that don't swallow. Finer conflict entries. Commands into operations (design doc first). | design doc, then ~6 PRs | 1; the operations work before v2 step 6 |

## Reconciled order (4 October, after the second opinion)

The waves above were the first review's proposal. After Codex's second opinion and Claude's
response ([response-claude.md](response-claude.md)), the order both reviews support is:

1. **Correctness.**
   - `write_atomic` and `set_checkout`.
   - An atomic composite.
   - An unknown status is never due.
   - `touch` no longer revives ended claims.
   - A stale undo is refused.
2. **Pilot *set status* end to end.**
   - `planning/` owns the status vocabulary, readers and readiness.
   - `step_status/actions.py` serves both surfaces.
   - The first architecture tests land with it.
3. **Planning facts, and a narrower root.**
   - Kind predicates and one key ranking, with the policies kept separate.
   - Cross-module imports go only through `aspect.py` and `actions.py`.
4. **Launch as an external effect.** Durable run intent and reconciliation, before the daemon.
5. **Decide the multiplayer authority.** Then design operations and versions.
6. **Renames and docs**, as responsibilities settle.

