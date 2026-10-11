# 2026-10-11: Parallel branches joining at one Test step, in one repository and across two

**The question.** Two lines of work run in parallel, each on its own feature branch, and come
together in one final Test step. Does DPlanner plan and run that? We tried it in one
repository and then across two repositories, with real agents and real GitHub PRs.

**The short answer.**
- **In one repository, yes.** It works in two shapes, and both reached the end:
  - **Land, then test:** each branch lands on `main`, and Test runs after both landings.
  - **Integration branch:** both branches are cut off an outer `feature/int`, land into it,
    Test runs there, and then `feature/int` lands on `main`.
  - Four things needed a person or a workaround (list below).
- **Across two repositories, no — not without a person watching every PR.**
  - DPlanner looks up every step's PR number in the project's *primary* repository. PR numbers
    collide across repositories (both start at #1), so the second repository's PRs were read
    as the first repository's.
  - The worst case happened in this run: the second repository's landing was marked **done**
    while its own PR was still **open**.

The HTML report, `report.html`, is the version to read. Its *Evidence* section maps each
claim to a file in `evidence/`.

## Setup
- **Code:** four throwaway private repositories (`Knutsi/temp-dplanner-test-{mainland,integration,lib,app}`).
- **Plan:** one plan repository with a local bare remote, and an isolated DPlanner (its own
  config directory and library), built by `evidence/setup.sh`, `build.sh` and `probes.sh`.
  Each step's brief is in `evidence/steps/`.
- **Agents:** Claude Code (Opus 5.5) did every work stage and Codex reviewed the landings.
  Playbooks:
  - members: `plan-execute-progress`;
  - landings: `land`;
  - Test on the mainline: `execute`.
- **Me:** I played the person at every mainline gate and merged with `gh`.
- **Cost:** 47 runs, about $10 of Claude turns plus nine Codex reviews, in roughly 90 minutes of wall-clock.

| Project | Shape | Outcome |
|---|---|---|
| LandThenTest | A1→A2 on `feature/a`, B1→B2 on `feature/b`, each landing on `main`; Test after both landings | Reached the end. The second landing conflicted and was sent back. Test was started early on purpose and resumed on a stale worktree. |
| Integration | The same two branches cut off `feature/int`, landing into it; Test on `feature/int`; then `feature/int` lands on `main` | Reached the end once I had cut `feature/int` by hand. |
| TwoRepos | L1→L2 in `lib` on `feature/a`; P1→P2 in `app` on `feature/b`; Test in `app` after both landings | Every `app` PR was misread. I settled four steps by hand, and one step was falsely marked done. |

## Findings, most severe first

1. **A step's PR is looked up in the primary repository, whatever its workplace.**
   - **Where:**
     - `modules/github/cli.py:391` `_step_repo` → `repository_facts(...).code_remote`;
     - the window does the same at `modules/__init__.py:2160` `repository_for`;
     - `progress` goes through `accept_by_merge` at `github/cli.py:309`.
   - **What we saw, in four shapes:**
     - **Wrong PR written onto the step:** S4's `progress` read lib's PR #1, wrote lib's title
       and URL onto the step, and blocked.
     - **Wrong merge narrowly avoided:** S5's `progress` found lib's PR #2 open and was stopped
       only by the head-branch check.
     - **False done:** `github refresh` marked app's landing S9 *done* because lib's PR #3 had
       merged. App's PR #3 was still open (`evidence/ev/tworepos-s9-false-done.txt`).
     - **Merged PR never noticed:** app's PR #4 merged, and the refresh said "1 checked,
       0 updated", silently (`tworepos-s10-refresh.txt`).
   - **Already stored wrongly:** `github set --pr` resolves the same way, so the record
     already carried the wrong URL.
   - **Fix:** one `repo_of(step)` built from the step's workplace location (as
     `agent_briefing/worktree.py`'s `code_placement` already does), used by `github set`,
     `refresh`, `progress`, the window's refresher and the PR chip.
2. **A nested branch's first run fails while its outer branch is not yet cut.**
   - **Error:** "src refspec origin/feature/int does not match any"
     (`evidence/ev/probe3-nested-first-run.txt`).
   - **Cause:** `branches/plan.py` `branch_plan` cuts only the innermost stretch, and
     `worktree._cut` pushes from `origin/<outer>`.
   - **Workaround:** push the outer branch by hand.
   - **Fix:** cut every missing enclosing stretch, from the outside in.
3. **On a weekend a branch cut stays *waiting*, and every first step on a branch is refused.**
   - **Cause:** `planning/schedule.py:497` `spent_since` returns `working_days_between(d, d) − ½`.
     That is `−0.5` on a Sunday, which is below a cut's 0-day wait.
   - **Effect:** "'A1 add' waits on work not done yet: B6 'feature/a'". `--anyway` gets past it.
   - **Fix:** clamp at 0, or read a cut as done when its predecessors are, without `waited`.
4. **A detached `playbook advance` can be lost** (plausible cause, not proven).
   - **What we saw:** two passes in one project finished `progress` 2 s apart. One PR merged
     on GitHub, but its pass sat at *Merging* with no record and no card. Running
     `playbook advance` by hand finished it.
   - **Plausible cause:** a "changed on disk" refusal that nothing retries.
   - **Fix:** `supervisor.advance_detached` discards the process's output, so there is nothing
     to read afterwards. Write it to the run directory, and retry the advance on a
     concurrent-write refusal.
5. **Simultaneous `agent run`s in one project: all but one are refused.**
   - **Message:** "changed on disk … run this again".
   - **When:** after the cut was pushed and the worktree made. Both side effects are
     idempotent, so a retry worked.
   - **Risk:** a coordinator or script launching in parallel must retry.
6. **When parallel landings into one base conflict, nothing notices.**
   - **What happens:** after the first landing merges, the second PR conflicts, yet GitHub
     still showed *MERGEABLE* (stale) and the step sat at *ready to merge*.
   - **What worked:** *Send Back* fixed it well (the landing merged its base and kept both
     sides).
   - **The catches:**
     - no review gate re-ran on the resolution;
     - after the merge the step stayed *ready for review* until a person's Accept.
   - **The opening:** DPlanner knows when two open landings share a base, so it could say so
     when one of them merges.
7. **A worktree made early is reused unchanged.**
   - **What happened:** Test, launched with `--anyway` before `feature/b` landed, resumed on
     the old `main`. The *agent* brought its branch up to date; DPlanner did not.
   - **Fix:** the briefing, or `prepare`, could merge or fast-forward when a prerequisite has
     landed since the worktree was cut.
8. **A step outside the primary repository is told it works in the primary one.**
   - **Where:** `agent_briefing/protocol.py:161` `plan_whereabouts` uses `facts.code_label`.
   - **Also affected:** the coordinator's briefing.
9. **An honest "cannot proceed" is shown as a permission denial.**
   - **Cause:** the execute schema offers `done | asked | denied`. The Test agent stopped
     because mul and div were missing, picked `denied`, and the card read "The agent was
     denied a permission it needed", with no choices.
10. **One branch across two repositories:**
    - lint says nothing;
    - the launch fails with "there is no origin/feature/mix … a branch deleted after it
      landed", which is the wrong explanation.
11. **Coordinator, read from its briefing:**
    - `gh pr view/merge <n>` has no `-R`;
    - it runs "checks on the integrated branch in your own worktree", singular;
    - neither holds with two repositories.
12. **Smaller points:**
    - **Overlap advice:** the refusal for Test linked straight to A2 and B2 suggests "`branch
      remove` one of them", not the two shapes that work.
    - **Partial join:** Test after one landing and the other branch's last step is caught by
      lint but not refused.
    - **Readiness waits on a refresh:** a merged landing waits for `github refresh`, and
      headless, nothing runs one.
    - **Canvas:** the cards do not say which repository a step works in.
    - **Codex reviewer:** it could not reach the network, so it reviewed landings without
      checking the remote.
    - **Plan never committed:** the headless CLI never commits the plan; 64 changes were left
      uncommitted.

## What held up
- **Graph and canvas:**
  - `branch put` nests (an outer branch over two existing stretches), and the canvas draws it
    clearly (`evidence/shots/canvas-Integration.png`).
  - A second branch with a name already in use is refused.
  - Test linked straight to both branches' last steps is refused at launch and named by lint.
- **Repositories:**
  - Worktrees opened in the right repository for every workplace.
  - Each repository's cut was pushed to that repository.
- **Merging:**
  - In one repository, `progress` merged members into their feature branches.
  - An inner landing merged into `feature/int` counted as accepted on the merge.
- **The agents:**
  - They stopped rather than inventing missing code.
  - They foresaw the conflict (note N6).
  - They resolved it when sent back.

## Blind spots beyond what we ran
- **Branch names across repositories:** a coordinated change across two repositories usually
  uses the *same* branch name in both. DPlanner refuses a second stretch with the same name in
  one project, whatever the repository, so the common convention cannot be planned. The
  refusal message is from our probe; that it hits this convention is inferred.
- **Three or more branches into one base:** the conflicts come in sequence, each landing sent
  back after the one before it merges.
- **Squash-only or rebase-only repositories:** the landing instructions require merge commits,
  so branch protection that forbids them stops every landing.
- **Auto-deleted head branches:** a landed stretch's branch disappears, and any later run of
  one of its members reads "deleted after it landed". That is correct, but nothing says so in
  advance.
- **Two projects, one repository:** branch names are checked per project, so two projects can
  both cut `feature/a` in the same repository.
- **Dependencies between repositories:** the app's Test depended on lib's `main` through a
  `git+ssh` URL, the agent's own choice. DPlanner models no released artifact or version pin,
  so "lib landed" does not mean "app can install it".
- **A window open during a two-repository run:** its PR refresher would mark false *done*s
  unattended, and finding 1 would happen without anyone running a verb.
