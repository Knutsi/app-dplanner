# Graph model — edges, auto-progress links, step numbers and isolation

The reasoning behind `.claude/rules/graph-model.md`: the rules there are the short, imperative
form, and this file is why. `ARCHITECTURE.md` is the index of every area.

## The graph, and what it stores

A project is a graph, so the tab is a canvas: `QGraphicsView` gives selection, dragging,
hit-testing and zoom for free. Writer's corkboard is 2,200 hand-rolled lines because cards
flow in a grid; free positions are the case Qt already handles.

Two decisions keep it small. **Every item diffs by key** — nodes by step id, edges by
`(waiter, kind, source)` — because an item the user is holding on to has to keep its identity:
a node may be under the mouse mid-drag, and an edge may be selected, waiting for Delete. It is
one rule for both on purpose: an edge rebuilt wholesale cannot stay selected, so a second rule
for edges is exactly what would make them unselectable.
**The scene reports, the activity commands** — every gesture ends in a signal, and the activity
turns it into something on the undo stack, so a drag is undoable and the model stays the only
authority on what a legal graph is.

That last point is why `Library.link_refusal()` exists. A link drag needs to know *before* the
drop whether an edge would be a cycle, and the alternative — a second reachability check in the
view — is two implementations that will eventually disagree. So the refusal is a question the
model answers, `set_edges` asks it before writing, and the canvas asks it under the cursor.
There is no error dialog anywhere in the interaction because there is never anything to
apologise for.

**The refusal is about the edge being added, never about the list it joins.** `set_edges`
replaces a whole list, and an entry already in it is carried, never re-judged. Judging every
entry reads as thorough and is a trap: `remove_child` leaves the survivors' edges naming a
deleted step on purpose (undo has to restore the graph exactly, and `requires()` skips what
it cannot resolve), so after any delete of a step others waited on, every survivor's list
holds an id that cannot pass "no such step" — and Link, Unlink, Redirect and Isolate, which
all *replace* that list, would be dead on those steps for the life of the project. Keeping
an entry cannot make the graph worse, and carrying is the only way such a list can ever
change again. (*decisions.md* has the day it surfaced.) The tidying up is one layer up for
the same reason: `remove_steps_command` (Delete, Cut, `step
remove`, `clear-steps`) is one composite that drops the links *into* the doomed steps and then
the steps, and because a composite undoes in reverse the steps come back before the lists that
named them. Exact undo needed a composite, not an untouched list; the model's `remove_child`
still rewrites nobody, and lint's `graph.requires-dangling` only ever names a ghost that
arrived from an edit outside the window or a merge.

## A step has a number, and the letter in front of it is derived

A uuid is the right identity for files that link to each other across renames and
branches, and the wrong thing to say out loud, type into a verb, or put in a branch name.
So a step also carries a **number**, dealt per project and never reused: `Step.number`,
minted in the one place a step joins a project (`Library.add_child`) from the project's
`last_number` high-water mark. The mark is stored rather than derived from the steps
present, because a deleted step's number must stay retired — its branch `agent/s7-…` and
its PR titled `S7: …` may outlive it, and a new `S7` would inherit them. Undo restores a
step with its number; a paste and an import arrive numberless and are dealt the next ones
(an import keeps the document's numbers where they are whole and unique, so `S7` survives
a round trip). Format 2 of the project format is this: the first migration numbers an
old project's steps in the order its `children` list records — the order it always showed
them in — and sets the mark past the last.

**The letter is not stored.** `S7` becomes `F7` when the step is placed as a feature and
`M7` when it becomes a milestone, because the letter says what the step *is* and the
kind is a set of toggles (*A kind is what a node is*): a stored letter would go stale the
moment a toggle flipped, and renumbering on a kind change would break the branch. The
ranking in `planning/kinds.py` orders the kinds — milestone over feature over check over
wait, cut and review, then step — and every reader takes the answer from there: the key block, every
CLI row, `find_step` (which accepts `S7`, `s7` and bare `7`, and refuses a bare number
that names a step in several projects the way it refuses a shared title — see *A key is
the current project's, an id the library's* below), the run name,
and the briefing's verbs, which address the step by key because a key is unambiguous
where a title may not be. The one cost is that a branch named after `s7` is not renamed
when the step becomes `F7`; the next launch reuses the worktree by its recorded name only
if the name matches, so a kind change after work has started earns a second branch. That
is rare, visible in `git branch`, and cheaper than a branch that lies.

### A key is the current project's, an id the library's

Every project numbers from 1, and two projects may share a title, so `S26` and "review"
mean nothing until somebody says *in which project*. When the invocation has a current
project — `--project`, `$DPLANNER_PROJECT`, or found from the working directory, one rule
whichever — `find_step` answers a key, a folder name or a title from that project alone and
refuses one it does not have, naming the project. It used to fall back to the whole library
when the current project had no match, which is how `DPLANNER_PROJECT=A dplanner review set
R26` turned project B's S26 into a review in the 10-04 run, written into a plan nobody was
looking at. A key that is not here was never meant for there.

An id is the one thing that reaches past the current project, because it is unique across
the library by construction and a person or a coordinator addressing another project's step
has it in hand. It must be at least as long as the eight characters every listing prints,
so a bare `26` or a title word that happens to be hex can never resolve as the prefix of a
stranger's id. With no current project, the whole library is the scope, as before.

## An auto-progress link is an aspect on the step that waits

*A playbook's `progress` stage replaces the auto-progress link, and this section leaves with
it; `playbooks.md`'s *A playbook is a list of stages around one step* has the design.*

An agent stops at Ready for review, and a plain `requires` is fulfilled by done alone —
together, the right rules for one step, and a deadlock for the shape the plan runs on: three
agents in parallel, then one step that takes their branches, lands them and sets them done.
That step cannot start until they are done, and they are done only once it has landed them.
So a link may **auto-progress**: its waiter may start as soon as the source reads ready for
review or ready to merge, and the waiter's briefing makes landing that work its job. Three
places to keep the flag were weighed:

| Where | Cost |
|---|---|
| **Data on the edge** — edges become objects with fields | A project-format bump older builds refuse to open, for one boolean; and every writer of an edge list (Link, Unlink, Redirect, Isolate, paste, import) learns to carry a field it does not care about. |
| **A new edge kind** — `auto` beside `requires` and `relates` | Every reader of `requires` — ordering, the schedule, cones, cycles, lint, redirect, the report — has to learn that `auto` orders too, or silently miss it; an older build keeps the kind but stops ordering by it. |
| **An aspect on the step that waits** — `{"from": [source ids]}` | None of the above: no format bump, an older build ignores it, and the graph learns nothing. (Chosen, N2.) |

It follows *Status is an aspect*: the flag is a fact about the step that waits — *I take
these steps' work from review on* — so it lives on that step, and the derivation that wants
it is handed a function, `auto_progresses(waiter, source)`, exactly as it is handed
`status_for`. `planning/progression.py`'s `outstanding()` is the one answer — a source is
fulfilled when it is done, or under review or waiting on its merge across a flagged link —
and the Step statuses tab, `progression show`, the report and Run Agent's gate all read it.

**A listed id counts only while the link exists, and nothing repairs it.** `flagged(step)`
intersects the list with the step's own `requires`, which the waiter holds, so no verb that
rewrites edges learns the aspect exists. A removed, redirected or isolated link leaves its
id inert, which is exactly *a redirected link arrives plain*; and undoing the removal
restores the flag with the link, because the list was never touched. The cost is one
surprise worth writing down: remove a flagged link and make it again, and it remembers its
flag. A paste is the one place ids change, so `PastePolicy` is handed the old→new map (the
five other policies ignore it) and the copies keep their flags; `project import` makes new
ids without a policy, so an imported plan's flags go inert — the same gap named layouts
have.

**Only an agent collects.** The flag's whole promise is a briefing — *Work you collect*
names each source's status, branch, PR and worktree on this machine, the duty to land that
work and the right to `status set <source> done`, and each source's epilogue names who takes
its work — and only an agent reads one. So the Edge menu's toggle greys on a waiter that is
not an agent step, and lint `auto-progress.waiter` names one that arrived another way. The
CLI still writes it, saying so, because a plan reshaped in several calls passes through that
state. The right to finish a source needed no new rule: an agent may already set done a step
under review, which is where a collected source stands.

**It is drawn as work that moves on its own.** The canvas never learns the word: the root
translates the flag into an `EdgeAccent` (`doubled`, `flowing`), as it does a node's
`NodeAccent`. A doubled arrow is two rails with chevrons between them pointing at the step
that waits — read from across the graph, where a medallion at the middle would be a dot —
and its chevrons move while the source wears the live ring, on the ring's own clock: the
motion that says *somebody is at work on this*, carried along to the step that will take
the work. `project graph` draws the same link `==>`, and `step show` marks it.

Two measurements shaped the painter. Placing a chevron with `QPainterPath.percentAtLength`
costs about 40 µs a call, which would make a doubled arrow 1.5 ms to lay out — on every
sync, which runs once per keystroke. `follow()` flattens the curve once and walks the
polyline (0.2 ms), and it returns at once when the arrow's two ends have not moved, which is
nearly every sync: 17 µs → 4 µs for *every* arrow, plain ones included. A flowing arrow's
tick re-walks the cached polyline only, 0.13 ms per 80 ms.

*Collect* here is not a scope's collecting (*A check is a scope over the graph, and so is a
milestone*): a scope gathers a cone of steps for coverage and documentation, while this
takes a handful of branches and lands them. The aspect's readers say `sources` and
`collectors`, the briefing says *Work you collect*, and the scope code never meets either.
The rule is in `.claude/rules/graph-model.md`.

## A branch stretch is bracketed by a cut and a landing

Where an agent step's work lands is the plan's decision, not an accident of what the code
checkout has checked out. The plan says *this stretch of steps goes onto a feature branch for
a while — several PRs into it — and then the branch comes back as a PR of its own*, with the
quality review there, and the canvas shows which work goes on which branch. (*decisions.md*
has what it replaced.)

**What any answer had to keep.** A `requires` link already means *this step's worktree
must contain that step's work*. On one branch that holds once the work is merged; across
branches it holds only once the branch has landed. So work may enter a branch only where it
is cut and leave only where it lands — a stack's one way in and one way out, one level up,
around a subgraph instead of a line. Four shapes were weighed against that, drawn over one
plan in an exploration the developer kept:

| Shape | Why not |
|---|---|
| **The landing alone is the branch** — one aspect on a collector, the members its cone as `scope.py` walks it | No lower bound: main work the branch builds on falls into the cone and onto the branch, a branch off a branch lands in main (a cone excludes the inner landing), and no step orders *cut before work*. Its convenience came back as a verb. |
| **Each step stores its branch**, as it stores its `workplace` | Stored membership drifts on the most ordinary edits — a `step add --after` a member lands on main without its work — and lint would have to derive membership anyway: two answers to one question, the reason regions were retired. |
| **A stack that is a branch** | A stack is one line, so work on the branch could never run side by side; and git's meaning would ride on `project_editor`'s data, which an older build drops from a card it moves. |
| **Cut and Land** — two steps bracketing the stretch (chosen) | Two cards per branch, and a pairing to keep. |

**Two aspects on steps, not two node kinds.** *Status is an aspect, and step types are
emergent* rules out a type field, and the bracket did not need one: a cut is a step
carrying `branch_cut` (`{"branch": …}`), key `B`, nobody's work — no worker, no status of
its own, done once what it waits on is, which is a wait of no days composed in
`schedule.status_on` (never through the schedule's `wait_of`, or reports would name every cut a
wait) — and a landing is an agent step carrying `branch_land` (`{"cut": id}`). `planning.kinds`'s
`works_nobody` became the one predicate a wait and a cut share, and every module that
refuses such a step a status, an agent, a review or a test words its refusal from the name
it hands back, where each had a wait's sentence of its own.

**The pairing is stored; membership is derived.** A landing names its cut, and the name
counts only while the cut is upstream — auto-progress's rule, a stored id read through the
graph — because the alternative, pairing each landing with the nearest open cut, silently
re-paired two stretches running side by side the moment one link moved, and every member's
PR would have gone into the other branch. Membership is `domain/branches.py`'s, read
**forwards**: everything after the cut, until the landing. Read the other way — everything
the landing waits on — main work the landing needs would have been swept onto the branch;
read forwards, a step that builds on branch work is on the branch by construction, so
nothing leaks onto main unlanded, and one that never reaches the landing is *named*
(`branch.unlanded`) rather than quietly put back. The two shapes that break one way in and
one way out are lint, not refusals, since a plan reshaped in several calls passes through
both: `branch.late-entry` (a member waits on main work the cut came before — its worktree
will not have it) and `branch.unlanded`. Nesting falls out: a stretch whose cut and landing
are both another's members is a branch off it, and a step's base is the innermost *open*
stretch holding it — so a cut inside a stretch cuts from that branch, and its landing opens
its PR into it. Two stretches crossing without nesting is `branch.overlap`, and Run Agent
refuses a step on both.

**The plan decides the branches; the script carries them out; the agent is told the same.**
`planning.branches.BranchPlan`, decided once by the root's `_branch_plan`, names the branch a run works on,
where a new one starts, what the first run may cut and the PR's base, and the preamble, the
epilogue and the wrapper all read it. **Every worktree starts from the remote** — a
stretch's branch, else the code row's `Location.ref` as the mainline, else the remote's
default, looked up — because a checkout left on some other branch would silently become
every agent's base. A new branch
starts with no upstream, so a bare push from an agent's own branch reaches nothing shared; a
landing works on the feature branch itself, tracking it, so the fixes a review asks for
reach the PR it reviews. **The branch is cut lazily** by the first run in the stretch, as a
pushed ref and never a checkout (a plan kept inside its code must not be switched under the
window), and only while nothing on the stretch has recorded a branch or a PR: after that, a
missing branch is one somebody deleted — landed, most likely — and re-cutting it from the
mainline would put a member's work nowhere, so the script refuses with the recovery in
words.

**The review moves to the landing.** A member's PR merged into the branch of an open stretch
accepts the step, from ready-for-review too (`record_merged(accepted_by_merge=)`): the
branch's quality review is the ordinary Review step placed after the landing, which reads
the landing's PR — nothing new was built for it. An agent still never merges its own work.
A landing always opens a PR; landing directly would leave the review nothing to read, and a
merge commit rather than a squash keeps a branch cut from this one on shared history. The
GitHub aspect records the base a PR merges into (format 2), so `branch.pr-base` can name
a member whose PR was aimed at the mainline.

**Put on a Branch and Remove Branch are one rewire each.** The first moves every outside
input onto a new cut and every outside dependent onto a new landing — `stack make`'s own move
to the ends, refused by the same `ordering.left_between` walk — and the second closes the
links over the two again. Removing is never partial, so the window asks first. The canvas
says the rest (*A card on a branch names it*, and the lane under an arrow, in
`.claude/rules/canvas.md`). The rules are in `.claude/rules/graph-model.md` and
`.claude/rules/agents.md`.
