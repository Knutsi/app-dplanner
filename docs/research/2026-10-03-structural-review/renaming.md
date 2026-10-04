# Renaming: where a package's name no longer says what it holds

**Summary.** Seven packages hold something their name does not say. The recommendation is to
rename or split only those seven, keep every on-disk `MODULE_ID` exactly as it is, and set a
file-role convention (what `activity.py`, `view.py`, `panel.py` mean). A full prefix pass
over all 57 packages costs far more churn than it buys. A docstring-only fix is the cheap
fallback.

**What never changes:** the `MODULE_ID` strings. They are keys in `module_data`, file names
under `modules/<id>.json` and format stamps, and FORMAT.md owns them. A package can move
freely, as `anthropic` (id `llm_anthropic`) already did.

## Per package

| Package today | What it holds | Proposed | Ids kept | Churn |
|---|---|---|---|---|
| `project_editor` (32 files, 12.8k lines) | The canvas: modes, items, graph scene, renderers, sorts and named layouts, stacks, clipboard, minimap, ruler, find, keymap; plus the `step duplicate` CLI verb | `canvas/` with sub-packages `stacks/` (stacks, stack_edits, stack_verbs), `layouts/` (sorts, named_layouts, layout_verbs, layout_button, placement, positions, ruler) and `clipboard/` (clipboard, clipboard_verbs) | `project_editor` | 32 test files, 14 mentions in rules files, 20 in ARCHITECTURE.md |
| `projects` (22 files, 7.4k) | The project *and step* CLI (1,659 lines), the Project dialog (1,416), locations, Open/Link/Browse/Repositories pages, Share, Move, Archive, checkouts, the index folder | `project_settings` (dialog, locations, settings page); `project_join` (open, link, browse, repositories, share, checkouts, code choice); `project_archive` (archive tab and index); the `step` noun moves to a headless `steps/cli.py` | `projects` stays with whichever keeps its data | large: the CLI tests |
| `progression` (4 files, 1.1k) | The Step statuses tab (`StatusBoard`) and the Control Centre | `status_board` | `progression` | small |
| `step_order` (6 files, 1.4k) | The Order tab, its export, and the token-spend Expenditure tab (`expenditure.py`) | Order stays; Expenditure goes to `agent_usage` | `step_order` | small |
| `step_agent_instruction` (12 files, 5.7k; Deps of 37 fields) | The briefing aspect (aspect, section, prompt, cli) and all of Run Agent (launcher, profiles, run and detect dialogs, settings page, checks, auto-launch) | the briefing stays; `agent_launch` takes launching; `agent_briefing` takes the root's ~800 lines of briefing text | `step_agent_instruction` | medium; `test_agent_run.py` mostly tests it |
| `step_agent_run` (8 files, 1.9k) | The run aspect, terminals, the Agents browser, and a second module id `agent_usage` (`usage.py:28`) | the run aspect stays; `agent_usage` becomes the package its id already names (usage, ledger views, Expenditure) | both | small |
| `time_estimates` (29 files, 8.6k) | The Time tab, staffing and budget, progress history and the recorder, half of the `schedule` CLI noun, and a 1.6k-line simulator with its debugger | `schedule` (tab, staffing, budget, progress, the whole `schedule` noun); `simulation/` and `debugger.py` go to a dev-tool package | `time_estimates` | medium |

Also: topology (`spec/cli.py:1`, "the project's prose beside the documents") is architecture
prose. It is the seed of the v2 *system* level and could become its own `topology` aspect
package when that work starts. No move now.

## The prefix rule

The prefixes no longer encode anything reliably:

- `step_*` covers 12 aspects, but not `estimation`, `testing`, `github`, `feature`,
  `branches` or `auto_progress`.
- Two packages carry `step_*` without being aspects: `step_properties` and `step_order`.

**Recommendation:** stop treating prefixes as meaning. A package is an aspect because it has
an `aspect.py`; `dplanner aspect list` and `aspect_specs()` already know that. Rename a
`step_*` package only when it moves anyway.

**The alternative** is a full pass that gives every aspect `step_` (`step_estimate`,
`step_tests`, `step_github`…). It churns about 15 packages and their tests for consistency
alone.

## File roles

| File | Means | Today it also means |
|---|---|---|
| `activity.py` | the tab | (the tab is also inside `module.py` in project_editor, progression, step_order) |
| `panel.py` | a side or dock panel | — |
| `*_dialog.py` | a modal | — |
| `status_widget.py` | a status-bar widget | `view.py` in sync, taskcenter, step_agent_run |
| `browser.py` | a modal list of things | `view.py` in library_watch, agent_at_work |
| `section.py` | a Step Details editor | `editor.py` in feature, notes |
| `settings_page.py` | a settings page | (already consistent; add it to the documented set) |
| `scene.py` | a QGraphicsScene | `graph.py` in project_editor |

`view.py` is retired as a name.
