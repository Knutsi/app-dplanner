# Playbooks dogfood: every preset, a coordinator and the Control Centre on a toy plan

*2026-10-08, S21 of "Playbooks and autonomous work", by Kettle Twenty-One. Everything below
was run on `feature/playbooks` (44ff352 plus this step's fixes), with real Claude Code
2.1.280 on Opus 5.5 and Codex CLI 0.160.0 on its default model. It used a throwaway plan in
the scratchpad and a throwaway private GitHub repo for the code. It follows the
[headless-agents](../2026-10-07-headless-agents/README.md) reality check, the
[playbooks](../2026-10-03-playbooks/README.md) research and the
[autonomous run](../2026-10-04-autonomous-run/README.md) that the engine was built to replace.*

**Read [report.html](report.html) for the walk-through with the screenshots.**

## The question

Does the engine built in S1–S20 hold up end to end with real agents?

- Every preset, run headless.
- A coordinator over three steps.
- A question answered and a plan approved from the Control Centre.
- A forced usage hold released by *Retry now*.
- A killed supervisor resumed.

And how does a running playbook *feel* to the person watching it? Knut asked for that one.

## Summary

**It works.** Thirteen agent steps ran, and every pass reached its end. A few needed a
person, as designed. The toy code grew eleven modules: seven PRs into `main`, left for a
person to merge, and four into `feature/toy`, merged by `progress` and the coordinator.
Nothing hung and no run was lost.

- **All nine presets ran** on Claude, Codex or both (table below).
- **Cross-vendor review** worked in both directions: Codex code reviewed by Claude, and the
  landing reviewed by Codex.
- **`progress` merged its own PR** into `feature/toy` and set the step done.
- **The coordinator** chose the squad word **teapot**. It claimed S9–S11, checked that their
  files did not overlap, and ran S9 and S11 side by side. For each gate it read the diff and
  ran the tests on the combined branch before passing it. It merged, released the steps and
  ended its claim. It put `DPLANNER_CALLSIGN=teapot-actual` on every call, as the S20
  briefing asks.
- **From the Control Centre's cards** I:
  - answered an agent's own question (S4 chose `mean_word_length`), and its session resumed
    with the answer;
  - approved two plans (S5, S6);
  - sent work back in my own words (S4's execute resumed and fixed it, then passed round 2);
  - stopped a pass.
- **A usage hold** forced through the fake API showed its card within 3 s and held the account
  (five-hour 100 %). *Retry now* resumed the same run, which finished 46 s later, and the hold
  lifted. Separately, a run whose hold could not be released turned into a `blocked` card
  after its retries; *Retry now* there ran it to done.
- **A supervisor killed with SIGKILL mid-turn** was revived when the window started. The lost
  turn was ended `failed/lost`, the retry went on through execute and `progress`, and the step
  ended done.
- **The spend:**
  - Claude: worker turns came to about **$6.50** at list price, and the coordinator to
    **$0.74**. Both were on the subscription.
  - Codex: about 7 % of its five-hour window.
  - Expenditure shows all of it per step: 644k fresh input, 5.0M cached, 61k output.

**What a person feels is the weak part.** The engine does the right thing, but almost
everything a person needs to know lives on the Control Centre's cards and nowhere else. These
are the places the run left me guessing:

1. **During the run, the canvas did not say a step waits for you.** A step at a person gate,
   at a coordinator gate, or merely Ready for review with nobody asked all looked the same:
   gold, with a PR chip. S27's strip under the card, merged into `feature/playbooks` while
   this run went on, now says it: *Waits for you · plan approval*, *Stopped*, *Done*. One
   catch is left: *Done* on a gold card whose PR into `main` nobody has merged reads as
   finished (N186).
2. **Every gate card read "An agent".** You could not tell your own gate from the
   coordinator's. **Fixed here:** the card now says *Waits for you* or *Waits for the
   coordinator — or you, when none drives the run*.
3. **Nothing shows a run that is dying or dead.**
   - A killed supervisor left the step "in progress" with no card until something revived it
     (N182).
   - A run failing transiently retried for 25 minutes before its `blocked` card appeared
     (N183).
4. **The status bar speaks in run ids**: "run 20261008T085057Z-95593154 resumes with it"
   (N187).
5. **Stop leaves the step in progress** with nobody on it (N181).

**Fixed on this branch:**
- Codex runs read model **unknown** in Expenditure, because `--json` never names the model.
  A `Headless.model` hook now reads it from the rollout (N177).
- The gate card's words (N178).
- `fake_api.py --release`, which turns the fake into a pass-through so a forced hold can be
  released for real (N179).

**Filed as `later`:** N180–N187. The one that needs Knut is **N180**: on a landing that has
not been run yet, *Review only* reviews the branch and skips the landing's own work.

## The presets

| Step | Preset | Agents | What happened |
|---|---|---|---|
| S1 Word count | `execute` | Codex | One turn, PR #1, Ready for review. Later `review-only` on it: Claude passed it, a person passed it. |
| S2 Line count | `plan-execute-review-self` | Claude | Plan → execute → a fresh Claude review: pass. 1 min 26 s. |
| S3 Unique words | `plan-execute-review-other` | Codex, Claude reviews | Pass. |
| S4 Average word length | `plan-execute-person` | Claude | Asked its own question (answered on the card). The person gate sent it back with my words, execute attempt 2 fixed it, then Pass. |
| S5 Longest word | `plan-person-execute` | Claude | Plan approved on the card, then execute. |
| S6 Split words how | `spike` | Codex | Plan approved on the card; the step was set done. |
| S8 A CLI entry point | `plan-execute-progress` | Claude | Supervisor killed mid-plan, revived, then `progress` merged PR #6 into `feature/toy`. |
| S9–S11 | `plan-execute-coordinator` | Claude, under teapot | Gates passed by Teapot Actual after verification. Merged and released. |
| S12, S14 | `execute` | Claude through the fake API | Forced usage holds (the report's *Usage hold*). |
| S13 Land feature/toy | `review-only` (landing default) | Codex reviews | Reviewed the branch, not a landing PR (N180). Stopped at the person gate. |

## Files

- [report.html](report.html): the walk-through, with the "how it feels" section and the
  screenshots.
- [evidence/log.md](evidence/log.md): the run as it happened.
- [evidence/setup.sh](evidence/setup.sh) and [evidence/steps/](evidence/steps/): the toy plan,
  rebuilt.
- [evidence/control_centre.py](evidence/control_centre.py): the real window, offscreen,
  pressing the real card buttons, with a screenshot before and after each press.
- [evidence/runs.py](evidence/runs.py): one line per run from the ledger.
- [evidence/coordinator-briefing.md](evidence/coordinator-briefing.md): what
  `agent coordinate S9 S10 S11` printed.
- [shots/](shots/): the Control Centre and the canvas at each moment the report names.

Raw streams and transcripts stayed in the scratchpad, because they carry the account's
identity.

## What was not tested

- **opencode.** No step ran on it.
- **A real exhausted account**, and a Codex usage hold. Only Claude's hold was forced through
  the fake API; Codex's real one was seen on 2026-10-04.
- **The window's own Autonomous Work ▸ Local menu.** The coordinator ran as `claude -p` on the
  same briefing, and a person had to wake it each round (N185).
- **A round cap.** No gate said *changes* twice.
- **Two coordinators**, or a second machine.
- **The sleep inhibitor (N111).** It stays filed. The run was short enough not to need it.
