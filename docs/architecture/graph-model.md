# Graph model — edges, step numbers and isolation

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
that names a step in several projects the way it refuses a shared title), the run name,
and the briefing's verbs, which address the step by key because a key is unambiguous
where a title may not be. The one cost is that a branch named after `s7` is not renamed
when the step becomes `F7`; the next launch reuses the worktree by its recorded name only
if the name matches, so a kind change after work has started earns a second branch. That
is rare, visible in `git branch`, and cheaper than a branch that lies.

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
counts only while the cut is upstream — a stored id read through the graph, which no verb
that rewrites edges learns about — because the alternative, pairing each landing with the nearest open cut, silently
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
