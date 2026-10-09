# Schedule — order, progression, time estimates, progress and milestone colour

The reasoning behind `.claude/rules/schedule.md`: the rules there are the short, imperative
form, and this file is why. `ARCHITECTURE.md` is the index of every area.

## Progression is the status-aware frontier

**The surface is named for the question; the derivation keeps the answer's name.** A person
opens this tab to find out what needs them, so it is called *Step statuses* — in the tab
title, the two menu entries and the index row — and the title counts the rows that need a
person, the one number worth reading from across the window, and the package that renders
it is `modules/status_board/`. Everything underneath stays `progression`: the walk, the module id, the activity kind, the action ids and `dplanner
progression show`. That split is deliberate three ways. The derivation puts every step into
one of eight partitions and the table shows only some of them, so *Step statuses* would be
the wrong name for the function. The kind and the ids are the contract the per-user store
remembers tabs by and the registry resolves verbs by, and renaming them would silently drop
somebody's open tabs. And the verb is in every agent's generated skill, so renaming it moves
the ground under an agent mid-plan for a word. (The tab was *Ready to start* until review
and merge arrived; that name now belongs to one of its groups.)

**The tab is a table of what needs a person, not a board of lanes.** It was three lanes
of cards under a percent and a bar — Running, Ready, Up next — and review and merge would
have made five, each a column too narrow for its titles, with the eye walking across all of
them to answer one question: *what needs me now?* The table answers it top to bottom, in
the order the work is closest to done — **Blocked, Ready to merge, Ready for review, Ready
to start** — then **Waiting**, what cannot start yet (temporary: a tab of what is going on
will take it). **Work in progress is not listed**: an agent at work needs nobody, and a
list of it is a report, not a queue. The percent and the bar went with the lanes; how far
along a project is lives in the Time tab and the report, and the terminal still prints it.
One `Segmented` over the table picks a group — one click, every group named at once, which
is the primitive for exclusive choices shown together; a group on its own drops its heading
because the lit segment already says it.

**The rows are ticked, and the tick is the selection.** A check column (`Column(check=True)`)
leads the table, and its box is drawn from the row's selection and toggles it — there is no
second *ticked* state. That is what lets the strip seat real registry verbs rather than a
host's copies: `agent.run` with its profiles under the arrow, `status.ready-to-merge` and
`status.done` (`StripVerb`, named by the composition root, so this module never learns the
agent or status modules exist), each restated on every context change from the published
selection and greyed with its own reason. The Step menu on a right-click reads the same
selection, so every presenter acts on exactly the ticked rows. The status verbs act on every
chosen step for the same reason (*Status is an aspect*, above).

`ordering.ready()` answers what the *graph* allows — wave one, nothing waited on. During
execution that is the wrong question: a step deep in the graph whose prerequisites have all
been finished is launchable today, and no wave number says so. `planning/progression.py`
answers the execution question — every step in exactly one of *done / running / asking /
review / merge / attention / ready / upcoming / waiting* — and it is deliberately a **second
derivation beside `ready()`, not a refactor of it**: the frontier is a per-step check ("every
`requires` target reads done"), not wave membership, and the two only coincide in a project
where nothing has been finished yet. A test pins that equivalence; shared code would have
pinned a coincidence.

The rules worth writing down, because each was a decision:

- **A stored claim beats the graph.** A step marked done whose prerequisites are not is
  honoured as done, and its dependents may become ready through it. The graph gates
  *launching*, not *recording* — an agent reporting `status set … done` out of order is
  reporting a fact, and a derivation that refused it would be arguing with reality.
- **An agent waiting on a person is on the board.** Running work is not listed — an agent
  at work needs nobody — but one that waits on a person, a plan to approve or a question to
  answer, does: it is stuck on somebody as surely as a blocked step. `asks_person`, handed
  in like `status_for`, splits it from `running` into `asking`, the *Waits for you* group
  under Blocked, with `progression show` saying the same. It reads the agent-run aspect: the
  states that ask, and a launch into plan mode that has said nothing since: a Claude
  launched in plan mode writes a plan and waits for somebody to approve it.
  The report keeps it in running — it publishes the plan, not a live session.
- **Blocked is attention, not waiting.** A blocked step is stuck on a person, so it leads
  the table rather than disappearing into the waited-on mass — it is the row that needs
  eyes, and the tab exists to route eyes.
- **Review and merge are on the board, and not done.** A step an agent finished is claimed
  out of the graph like a running one — it is one move away for the lookahead and in no
  percent — and **a plain `requires` is fulfilled by done alone**: nothing starts on work
  nobody has accepted, or on work not merged yet. The Run Agent gate asks the same
  question and so agrees, which a test pins.
- **Ready for review is a person's turn.** Whatever waits on a step under review, a person
  moves it next — to merge, or back to its agent — so it is on the boards' *Ready for review*
  and its card pulses (*A card pulses where a person moves next*): one answer, two surfaces.
  The rule that let a waiting agent take such a step over — a collector or a review step across
  a link that auto-progressed — left with auto-progress and review steps (`decisions.md`,
  2026-10-07).
- **A blocked or reviewed prerequisite still counts as "on the board"** for the one-move
  lookahead: its dependents stay in *upcoming*, pointing at it. The alternative — demoting
  them to waiting — would make the queue churn every time a prerequisite flips between
  in-progress, review and blocked, and would hide exactly the work that stalled.
- **The lookahead is one move, not a forecast.** A step whose prerequisite is merely
  *upcoming* stays in waiting. Anything deeper is the order table's job.
- **Every group a person acts on ranks by unlocks** — the count of transitive not-done
  dependents, which the walk keeps for every step of work not done — because all of a group
  is valid and the ranking is what makes some of it urgent: the review that frees three
  steps before the one that frees none. A done dependent is walked through but not counted:
  its own dependents still wait through it.

`status_for(step)` is handed in by the composition root — a wait's status depends on the
day, and the wait is still a module's aspect — and the estimate is read from the planning
tier; the derivation is tested with dict-backed functions in their place. Nothing
is persisted, for the ordering's reason — `dplanner status set` changes the answer with no
window running to notice. The tab (`modules/status_board/`), `dplanner progression show` and
`--json` are three readers of the one function, so no surface can recommend a launch
another surface would dispute.

**A launch of ready-to-start rows never raises the prerequisite confirmation, and that is
the two rules agreeing rather than a gap.** `agent.run` asks before launching a step whose
`requires` do not all read done; a step is in *Ready to start* precisely because they do.
The group and the gate are asking one question — "is anything this waits on unfinished?" —
so the box can only appear where the question can still be answered yes: a ticked row in
another group, the canvas, the order table, the palette. A test pins the silence, because a
confirmation that never fires in the place people launch from is the kind of thing a later
change removes by accident.

**The Control Centre is the same board over every project** — what needs a person
anywhere, rather than in the project whose tab is open. Six decisions shaped it:

- **The same groups, and still no running work.** The Control Centre is the five groups
  above, not lanes, and a later group is one row in `GROUPS`, on both tabs at once.
- **Each project is walked on its own and the board is their merge.** Edges never cross a
  project, so `progression()` per project is already right, and `merge()` only has to rank
  what a person acts on again by `unlocks` over the whole — a stable sort over the walks
  handed in library order, so ties go to the earlier project and then to that project's
  own rank, and one walk merged is itself. `across()` is the two in one call for the
  terminal. The tab keeps the walks and re-merges the picked ones, so the *Projects*
  filter never walks a graph: a filter change is a merge and a table fill.
- **Two tabs on one base, not one tab with a scope.** `StatusBoard` holds the strip, the
  table, the row's ⋮ and the refresh; *Step statuses* and the Control Centre are siblings on
  it. One class with a *None-means-every-project* scope would be closed by
  `follow_project_tabs` on the first structure change: it closes any instance of the type
  whose entity the library no longer has. The Control Centre also
  publishes no project edge, which is the other thing that differs.
- **A verb about one project reads the picked step's own when the view names none.**
  *Show in ▸ Order* and *Step Statuses* ask the context for a project, and a board of every
  project names none — so without this they would be greyed, with no reason, on every
  Control Centre row. `framework/step_selection.py`'s `focused_project` is the rule, where
  every module finds it.
- **Nothing was added to launch across projects.** Run Agent's gate already resolves each
  chosen step's project and asks for its checkout once per project; *Run 2 Agents…* over
  two projects' ticks is the strip's existing seat, and a test pins that it opens each
  shell in its own repository.
- **The day turning is a change.** A dated wait is over on a day, and `status_for` reads
  today when asked, so a window left open overnight would show yesterday's board until
  somebody edited something. Both tabs re-run on `clock.day_changed`, as the Time tab does.

`dplanner progression show --all [PROJECT …]` is the Control Centre in the terminal: every
row names its project and says whether an agent works it, in the text and the JSON. The
projects narrowing it are positionals because `--project` is already every verb's own
option (`cli/main.py`), naming where a verb *acts* — a second definition would not even
parse. The one-project JSON only gained fields, so an agent reading it before `--all`
existed reads it still.

## The order says what order, and how much — never when

The Order tab ran the plan out as a calendar once: an *Accumulated* column, a *Since
milestone* column and a *Date* per row, from a start date set on that page, one step after
another with a single worker and weekends skipped. Every number in it was true and none of
it was useful. Nobody works that way, and the application itself does not believe it —
`modules/schedule` simulates two pools of workers against milestone dates, and that is what
the plan is scheduled on. Two surfaces answering *when* with different arithmetic is one
surface too many, and the one to drop is the one nobody schedules on.

What an order *can* say without claiming to know who does the work is how much work it
holds. That is `planning/schedule.py`'s `volume_words` — *62 days over 24 steps, 2
unestimated* — beside `format_days` and `format_day_count` for their reason: it has four
readers (the tab, `dplanner order show`, `dplanner estimate rollup` and the Estimates tab's
strip) and a total read in one place must not disagree with the same total read in another.
The unestimated steps are named rather than folded in, because a total that counted them as
nothing would read as a smaller project.

Three consequences worth writing down:

- **The start-date bar left with the columns.** It was the estimation module's widget lent
  to this tab through a consumer-owned `StartBar` protocol, and this tab was its only
  caller. The value it wrote is still the project's, still read by `schedule show` and the
  report, and still set — from the Time tab's *Milestones ▸ Begin…*, which is where the
  dates that matter are chosen. A protocol with no implementor and a widget with no host
  are entropy, so both went.
- **Wave 1 is called *Wave 1*.** It was *Ready to start*, on the argument that "wave 1" makes
  the reader work out what it means. But the execution board then carried those words (a
  group of the Step statuses tab does now), and
  they would name two different things: the graph's first wave (nothing before it) and the
  status-aware frontier (nothing it waits on is left undone). Those coincide only in a
  project where nothing has been finished — the very coincidence this document warns against
  reading as sameness one section up. One phrase, one meaning.
- **The CSV export and the published report keep the day counts and the dates.** A
  spreadsheet is opened to sort, sum and chart, and a column of ISO dates is data rather
  than a claim the window makes. The tab and its own Export button therefore disagree about
  three columns, which is recorded as a `later` note rather than settled by making the
  export worse.

## Today is handed in

A forecast is dated from today, so whatever reads the date decides what the Time tab says.
Read where it was needed — `date.today()` in the tab, the recorder, the calendar, the CLI
verbs and the report — the day could not be pinned by a test (two test files asserted
against the machine's date, and any test that reads a forecast becomes weekend- and
midnight-dependent the moment the model reads today), could not be set to a simulated day
by the time simulator, and could not be noticed turning: a window left open overnight showed
yesterday's forecast and recorded nothing for the new day until somebody edited something.

So the day is a `Clock` (`core/clock.py`), one per window and one per CLI run: `today()`,
`pin(day)` and `day_changed`. It is Qt-free because the CLI and the report need it; the
window's `DayWatch` (`framework/day_watch.py`) asks it to check at midnight and when the
application becomes active, since a timer sleeps with the machine. A report is built *for*
a day and every source is handed that day, rather than each source asking a clock of its
own — one report, one day. The rule is `.claude/rules/schedule.md`'s *Today is the
clock's*.

## Time estimates: two worker pools, one greedy simulation

`schedule()` and `critical_path()` print the honest brackets — one worker, unlimited
workers. `dplanner schedule matrix` answers what lands between them:
`planning/schedule.py`'s `parallel_finish` simulates the graph under a stated cap of
*humans* and *coding agents*, and a small grid of those simulations is its report; the
Time tab runs the one the project is staffed for. The decisions worth writing down:

- **Two pools, pure.** An agent step waits for an agent slot, every other step for a human
  one, and neither pool takes the other's work — even an idle human never picks up an agent
  step. That is a modelling choice, not a scheduling inevitability: mixing pools would need
  a claim about who *may* do what that the model does not carry, and the clean partition is
  what makes the matrix's axes mean something. Which steps are agent work arrives as a
  predicate (`is_agent`), the same seam as `days_for` — the domain learns "two kinds of
  workers", never what marks a step.
- **Greedy list scheduling, not an optimum.** A free slot takes the ready step with the
  longest remaining `requires` chain, ties by project step order. Deterministic, honest
  ("the team picks the longest pole first"), and pinned at both ends: with ample workers it
  meets the critical path exactly, with one human on all-human work it meets the serial
  total. An ILP would be tighter in contrived graphs and impossible to explain in a cell.
- **Calendar time is the same walk over stretched estimates.** The focus factor — how much
  of a person's working day this project actually gets — divides human steps' days via a
  wrapped `days_for` (`schedule/assumptions.py`'s `stretched`), so the domain never
  learns an efficiency exists. Agent steps are not stretched: their human-in-the-loop cost
  is already inside the quarter-day estimate convention, and the factor prices the person's
  divided week, not the agent's.
- **The factor is the only thing stored; the matrix never is.** Twelve cells are recomputed
  on every change for the ordering's reason — `dplanner estimate set` changes the answer
  with no window running to notice. The factor is an assumption a person chose, so it
  persists like the start date does: project-node module data, written through one command
  (the tab's Budget and `dplanner schedule focus` push the same write).
- **The tab asks one question, so it runs one staffing.** The tab once drew the whole
  grid — a heatmap of twelve simulations under a lens between calendar and project days —
  and a tile click chose the team. Twelve answers made the one a person came for, *when
  does this team land it*, a tile among many, and every refresh paid for eleven nobody
  read. The tab now runs the stored team (`Readers.snapshot`, the recorder's own call), and
  trying another team is choosing it in the Budget, one undo away; `schedule matrix` keeps
  the grid for the terminal, where comparing teams is the point.
- **Milestones run in sequence, and a stretch is a cone.** A plan with milestones is not
  one simulation but one per milestone: its stretch is `scope.cone` truncated at the
  milestones before it — what is new since the last one — plus itself, and a step two
  milestones both reach belongs to the earlier. Each stretch is `parallel_finish` over its
  own steps (the `among` parameter; an edge out of the subset counts as met, because the
  sequence already put that work before), beginning where the previous lands — with what
  is left of that day (*Stretches pass part-days on*, below). Work no milestone gathers runs last, with no milestone; a project with none is
  that one stretch, which is the plain simulation it always was. The alternative — one
  simulation over the whole graph with per-milestone release dates — was rejected because
  it lets a later milestone's independent work run *during* an earlier one whenever a slot
  is free, which is what a team can do but not what "milestones in sequence" says, and it
  makes the calendar impossible to read as bands. One exception was measured in since and
  adopted: work a team has already *started* in a later stretch runs now (*Milestones
  worked in parallel*, below) — the sequence plans the work, but it does not stop anybody.
- **A milestone's own date is an assumption, so it is stored — and it is a floor, not a
  fact.** `schedule milestone --start` says when a stretch *begins*, not when it lands
  (the aspect that names a milestone is explicit that a landing date is the schedule's to
  answer, never stored). A date later than the previous landing opens a gap, which the
  calendar shows as one; a date earlier than it is **pushed** to the sequence's own day
  and reported (`Phase.pushed`, the report's milestone table, the sentence in the CLI) rather
  than honoured by overlapping — overlap would make the sequence a lie one milestone at a
  time. The first milestone is the exception: nothing lands before it, so its date wins
  over the project's start, which is only the default. Both writes — the date and the
  colour — live under this module's id on the *milestone's* step, `estimation`'s
  project-plus-step precedent; `FORMAT.md` has the shape.
- **Colour is a place on one map, unless somebody chose.** The first cut dealt eight
  distinct hues in order, and the first real project showed why that reads as chaos: a
  roadmap is a *sequence*, and eight unrelated hues say nothing about order. So the
  project picks a **colour map** — the legible interior of a published perceptual map
  (viridis, mako, rocket, …; `schedule.py`'s `PALETTES`), stored under the module's id
  on the project node beside the focus factor, absent for the default — and `shades`
  deals the milestones evenly along it, centred, so two milestones sit a quarter and
  three quarters in and eight fill it. Dealing by count means adding a milestone
  re-shades the others; that is accepted, because the shade's meaning is *place in the
  sequence*, which is exactly what changed. An override still pins one milestone without
  renumbering the rest, and the swatch's menu offers the map's own shades first so an
  override usually stays in the family. A project without milestones is one stretch in
  the report's own blue (`WHOLE_COLOR`), as it always was. The calendar and the
  Milestones page share the hex through `schedule.py` and never store a `QColor`, for the
  palette-snapshot reason in *The palette a painter is handed is a snapshot*.
- **And the map is the project's, which is what let the shade leave this tab.** For a
  while the shades lived only here: the calendar said *this is milestone 2 of 4* and the
  graph beside it said only *this is a milestone*, in the one violet every milestone wore.
  Joining them needed an answer to "what colour is this milestone" that any surface could
  ask, so `milestone_colors(library, project, is_milestone)` is the deal — `placed`'s
  sequence, an override over a dealt shade — and `phase_colors` is a lookup into it rather
  than a second deal beside it. The maps moved to `theme/palettes.py`, Qt-free and a leaf,
  because the appearance module lists them and modules never import each other; the
  composition root walks each project once and hands every consumer a typed callback, the
  `milestone_stats` shape. `theme/tones.py`'s `toned(name, hex)` recolours a tone at its
  own alphas, so ten painters never re-derive one and a recoloured card is exactly as loud
  as the purple it replaced.

  **The choice stayed the project's rather than becoming the user's, and that decided the
  menu.** A per-user map was the obvious reading of "pick it in the theme menu", and it is
  wrong twice: Save publishes `reports/` into the plan repository, so two developers would
  churn the committed report's colours between them; and the Time tab's picker names the
  project's map, so a window painting a user's override would have a control that lied
  about what it was showing. So *View ▸ Milestone Colours* writes the same stored entry
  `dplanner schedule palette` and that picker write, through the same undoable command —
  one choice, three ways in, the *Two surfaces, one vocabulary* rule applied to a third.
  It sits **beside** Theme rather than inside it, because it is not a theme and an entry
  nested under one would read as a theme; and being a project fact in a window menu, it is
  greyed with its reason when no project is open rather than hidden. The tick follows a
  map changed from a terminal, from the Time tab or by an undo, because the module
  subscribes to `module_data_changed` for that one id — a state callback must never read a
  file (*The context is announced once per turn*).
- **A page at a time, under four figures.** The page was split at a seam — what you set
  on the left, the calendar, the milestone list and the plots on the right — and each
  redesign added to both halves until neither fitted a laptop. The v5 prototype settled
  it: four figures lead — where the plan lands (✓ and the day, once it is done), how far
  that moved against the plan compared with, how much is done, how many steps nobody
  sized (a click opens the Estimates tab on them) — and one strip holds everything that is
  set: the pages (*Milestones*, *Work*, *Calendar*; a `Segmented`), what the plan is
  compared with, the Budget, *Save Snapshot…*, ⋯ for the colour map and Export. **A
  milestone's own start date and colour left the page for its Details tab** (`section.py`'s
  *Schedule* block, `shown_for` milestones): they are assumptions about one milestone,
  edited where the milestone is, and the list that carried them was the page's widest
  control. The calendar is the one drawing that is not fixed-size — months across follow
  the width, cells grow with it, a landing day names its milestone once the cell has room.
  Picking a milestone on the Milestones page emphasises its stretch in the calendar and
  fades the rest, which is how "the work leading up to it" is shown without a word; a pick
  hides nothing. Every number's meaning is in its tooltip.
- **A plan that cannot be dated says so.** The model refuses to create a cycle, but every
  walk here guards against one a hand-edited file carries — and guarding *silently* would
  place the looped steps at depth zero and date a plan that has no order.
  `ordering.cyclic()` names them (Kahn's peeling: whatever cannot be shed sits on or behind
  a loop), `time_report` returns a report with `cycle` set and empty grids,
  `Readers.snapshot` returns nothing, the tab shows the names in place of the pages, and
  `schedule matrix` exits non-zero with them.
  A view that computes on every change has to be robust to every state the file can be
  in, or it is a view that sometimes shows a picture of nothing.
- **The team is an assumption, so it is stored — and the Budget is the write.** As view
  state that resets on every open, the calendar, the landing list and `schedule matrix`
  could each be dating the plan for a different team. So it is the project's —
  `{"team": [2, 3]}` beside the focus factor
  and the palette, one `Assumptions` record read and written whole so no control has to
  juggle the other two — pushed by the Budget popover as *Set Budget* (people, agents when
  the plan has agent steps, and the focus: a pick writes only what it changed, and applies
  from today on, because `write_project` keeps the focus work in flight ran at) and by
  `dplanner schedule team`, and the team every stretch and every recorded day are
  computed for.

### The plan re-dates itself from what has happened

A forecast dated from the plan alone says the same thing whatever the team does, and one
re-simulated from today every morning draws a saw-tooth: each day the unfinished work slides
to "from now", so a plan followed to the letter reads as slipping half a day a day. The v5
prototype (`docs/exploration/time-estimation-2` on its own branch, never merged) measured
both over twelve simulated teams and adopted a third: **the plan's own dates stand while
reality matches them; otherwise the rest resumes from tomorrow, with work in flight
credited.** `phases(…, facts=ScheduleFacts)` is that model, and
`tests/modules/schedule/test_time_parity.py` holds it to the prototype's forecast on every day of
every scenario, three seeds each — the prototype's fixture replayed through the real aspect
writers (`schedule/simulation/frames.py`), so the stored `since` the model reads is the
one the status aspect stamped. The rule is `.claude/rules/schedule.md`'s *The plan re-dates
itself*.

- **Holding is a check, not a tolerance.** `_holds` asks whether every step is done exactly
  when the plan lands it — none early, on the very day where its status says when, none
  still open once its day is over — whether nothing in flight started after the day the plan
  started it, and whether nothing was planned to start before it existed. One mismatch and
  the plan resumes; a match holds the dates to the day, which is what makes a plan followed
  exactly read its true landing from the first day to the last (the parity file pins it).
- **Resuming keeps what is known.** A done step is a fact dated by its `since`; one with no
  `since` — a status older than its days — is taken as done by its planned landing or today,
  whichever is earlier, never later than it could have been. Work in flight **keeps its
  worker**: it goes first in `parallel_finish` (`running`), because the person on it does
  not drop it for a longer chain. It is credited with the working days since it started,
  from the middle of that day, and at least half a day is always left. The credit is
  `ScheduleFacts.worked`, built in `schedule/assumptions.py`, because a day worked under
  an earlier focus is worth what that focus made it (`efficiency_was`) and the domain never
  learns a focus exists.
- **Facts beat the sequence.** A stretch whose work is all done is dated by when it was
  done and holds nothing back, even when its milestone's own step was never marked. **Marker
  steps** — estimate off: a milestone's own step, a feature, a check — carry no schedule
  facts at all, because people rarely mark one done the day its work lands, and one left
  unmarked would otherwise hold every later stretch at "tomorrow" for good. Stretches are
  still planned in sequence, but work done out of it counts where it happened: a later
  milestone whose own work is done lands before an earlier one still under way, so **the
  whole lands with its latest stretch, not its last** — `max` over the stretches in the
  matrix, the snapshot and the tab.
- **A day is read at its end, or while it is still going.** The prototype's world is a
  frame at the end of each day, where a step due today and not done is late. A window is
  read in the morning: under that rule a plan made this morning starts tomorrow (its first
  short step "should" already be done) and every landing slips until somebody marks the
  step done that afternoon. `ScheduleFacts.day_over` says which reading is meant, so the
  two stay one model: the window, the CLI and the report read a day still going, where a
  step due today has until tonight; the parity harness and the simulator read days that
  are over. A step stamped later than today — a clock running ahead on another machine —
  was made today.
- **Stretches pass part-days on.** A stretch ending part-way through a day hands the rest of
  it to the next (`Phase.lead`), and one ending exactly as a day ends is picked up the
  moment it lands — its start is that day, used up — because a team starts the next step
  when it finishes one. `working_days_after` rounds up past a `GUARD` of 1e-9, so float
  noise in a sum of fractions never adds a working day to a date. A stretch's `start` is
  where its remaining work begins, `began` when its work first began; the calendar, the
  Begins column, a snapshot and `schedule matrix --json` show `began`.
- **Ahead and behind went with it.** The progress plot printed *ahead 5 %* beside today's
  dot. Re-dated from what is done, the plan now always agrees with what has landed by
  today, so the word could only ever say *on plan*; a slip shows as the plan now moving
  against the plan then, which the scope and milestone plots draw.
- **Adjusting for efficiency is the reader's, and off by default.** Resuming prices every
  step not yet started at its estimate, so when every step takes half again as long the
  forecast slips one late step at a time and never learns the pattern (the prototype's
  ISSUES F6). *Adjust for Efficiency* re-dates people's remaining work at the pace so far
  (`schedule.pace_so_far`): the stretched days people's finished steps were given over the
  working days they took, middle of the start day to middle of the done day — the focus
  measured, so people's alone, as the focus is. Two cheaper measures were tried there and
  rejected: the work done against the plan's schedule jumps with every long step that
  lands late, and a first cut that mixed in agents and floored a step at half a day read
  every plan slow, moving the dates of plans whose estimates were right. It waits for five
  working days and three finished steps, treats a pace within a tenth of the plan as the
  plan's, and believes one only between ¼ and 4×. It enters the model as nothing new:
  `ScheduleFacts.resume_days` is `stretched` at the measured focus (planned × pace), and
  it applies only once the plan no longer holds, so a plan followed to the day never moves.
  **Why a toggle, off by default:** on the prototype's accuracy table it helps the plans
  whose estimates are systematically short (Optimistic 10.5 → 6.5 days of error) and costs
  the ones where they are not (Blocked 1.8 → 4.2) — a judgement about the team, which only
  the reader can make. So it is a per-user way of looking (`user_config`), never stored
  with the plan: the recorder, a saved snapshot and the report keep the plan as its stored
  focus dates it, and History, reading a record, greys it.

### A wait is a step that holds

A plan has days nothing can be done about: hardware arriving on the 4th, a review that takes
three days whoever is free. Before waits, a planner priced them as work — an estimate on a
step nobody works — which put a worker on it, counted it in every tally and made its days
depend on the focus. The prototype's Delay step (`delay_test.ts`) is the answer, ported to
the day:

- **A step, not a node kind.** *Status is an aspect, and step types are emergent* rules out
  a type field, and a wait needs none: as a step it works unchanged in cones, ordering,
  cycles, copy and paste and numbering, and it is `step_wait`'s aspect — `{"until": …}` or
  `{"days": n}` — read as `planning/wait.py`'s `Wait` by every walk in the schedule, with
  `wait_of` left as a keyword for the simulator's world.
- **It takes no worker and is no work.** `parallel_finish` releases a ready wait straight
  into the running set with the moment it is over (`waits`), and frees no worker when it
  lands; the walk's cost of an `until` wait is nothing, since only the calendar knows when
  its day is. `phases` knows: an `until` wait ends at the first moment of its day, counted
  from where the stretch began, so what requires it starts that morning and not before.
  No tally counts a wait — a snapshot's, the effort, the unsized count — because a plan
  with a three-day review in it is not three days more work.
- **Re-dated, a wait keeps what it has waited.** A `days` wait whose steps before it are
  done has waited since the last of them was done, from the middle of that day — or since
  the day it was made, when it was made after them — and only the rest is left; `_holds`
  asks a wait nothing but when it was made, since it has no status to be late by.
- **Everywhere else, a wait is done when it is over.** With no status of its own a wait
  read *pending* forever, and the board and the Run Agent gate — which ask whether a
  prerequisite reads done — held whatever followed one for good. So they read
  `schedule.wait_status` instead of the stored status alone: a wait is done once what it
  waits on is done and its day has come, or its days have been waited (the model's own
  `waited`), and `Waiting` until then. Derived on every read, like the rest of progression,
  so a wait releases its steps the morning it may with nobody marking anything.
- **A wait looks like one, and only as the plan dates it now.** Its key's letter is `W`,
  its key block wears the clock in the attention amber, its stat is how long it holds. On the Time tab the days it holds are
  hatched through both work plots and named, hatched on the calendar and named in its
  milestone's words; the report draws them as pale named bands, since QtSvg honours no
  pattern. What the page draws them from is `Snapshot.waits`, a field the snapshot carries
  but never records and never compares: a wait is no work, and the day it lets go is in the
  landings already, so a recorded day read by History shows none, as the prototype's does.
  *Insert Wait Before* puts a wait of a day in front of a step — taking what the step
  waited on, the step then waiting on it — as one undo, born through the graph editor's
  `create_step` like a feature step from the Specs tab, a column to the step's left.
- **One predicate says what is work.** A wait is on no lane of the board, in no volume and
  never unestimated — `_counts_as_work`, one function in the root, handed to progression,
  the Estimates tab, the Order tab, `estimate rollup`, `schedule show`, `order show` and
  lint, and `schedule.volume` is the one place a volume is counted, so no two surfaces
  count a wait differently. What a wait cannot carry — a status, an agent, tests — is
  refused with the reason in the verb's words (`aspect_toggle`'s `refusal`), never hidden.

### The Time tab has a simulator, and it is the prototype's

A forecast model is judged over days, not in a screenshot: whether it holds still while a
plan is followed and moves the day it is not. The prototype was built around a simulator
for that — a team working a synthetic plan while something happens to it, one scenario per
broken assumption — and `schedule/simulation/` is that simulator in Python, Qt-free
and held to it: the seeded luck and the sample plan to the bit, the world frame for frame
(`test_time_simulation.py` replays every exported run), and the model on top by the parity
file. `scripts/time_accuracy.py` prints the prototype's accuracy table — its `resume`
column exactly, and its *pace so far* as the column with *Adjust for Efficiency* on — which
is what makes a model change there a measured one here.

- **A simulated day reaches the library through the owners' own writers.** A frame is a
  day's changes in the terms DPlanner stores (`frames.py`); its `Writers` are each aspect's
  own writer beside the `Readers` it reads with, so a status is dated by the status aspect
  exactly as a person's edit that day would have been. Every aspect either touches is a
  `planning/` one, so both default to the tier's functions and import no other module.
- **Debug ▸ Time Simulation embeds the real Time tab, over a world of its own.** The tab's
  deps come from the root's one recipe (`time_deps` in the root's `_project_tabs`), called once for
  the window and once per simulation with a scratch library, undo stack, context, clock and
  debounce service — never a copy of the window's deps with fields swapped, which is how a
  shared service slips through unnoticed (a test holds the two apart). The verbs are shared:
  every one runs against the scratch context, and the steps it names are not the window's.
  The embedded tab reads each day at its end (`day_over`), as the simulator's days are.
- **Scrubbing restores a day in place.** Rebuilding the tab per day would lose what the
  reader had picked and cost a tab's construction per step of the slider, so the simulation
  keeps what the project held at each day's end (`replay.keep`) and `replay.restore`
  writes back only what differs — in either direction, into the one library the tab
  follows, without knowing what any entry means. The scratch debounce service is the
  tab's own because the slider flushes it after every restore: played at a few days a
  second, a tab waiting out its 500 ms settle would never draw one.
- **The embedded tab's writers are the simulator's.** A Budget change in the embedded tab
  would write the scratch library and be undone by the next day restored, so the tab is
  told why nothing there may write (`set_read_only`) and greys its writers saying so —
  the mechanism History uses, with the host's reason — and the re-budget on the
  debugger's own strip is the one that changes the world.
- **The axes can hold the whole run.** Played a day at a time, a plan that slips widens
  its axis every day, and a line that moves is lost in a scale that does. *Hold the Axes
  Still* hands the embedded tab every row the run recorded as more plans its reach must
  hold (`hold_reach`), so the days move only the lines; let go, the axes follow the day.
- **Nothing is simulated until the tab is first shown**, so a restored Debug tab costs
  nothing at startup.

### Milestones worked in parallel

Milestones run in sequence (*Time estimates: two worker pools*), and the prototype never
tested what happens when a team does not: its sample plan chains every milestone's work onto
the one before, so no later work can start early. Three scenarios were added to the
simulator to measure it — **Two tracks** (two chains of milestones that never wait on each
other, idle hands working ahead), **Multitasking** (each person keeps two steps going, their
focus split) and **Late marking** (a step is marked done the working morning after it lands)
— each sizing every step, as *By the book* does, so what it shows is its own. Every
candidate was run over all fifteen scenarios, six seeds each, and adopted only if *By the
book* stayed at 0.0 · 0 · 0 and nothing got worse (`scripts/time_accuracy.py`; error ·
movement · days moved, in working days).

- **A marker takes no worker.** Two tracks first read its milestones nine days early for
  weeks on end, and not because of the model: the world landed a milestone's own step only
  when a worker was free to take it, and the one person was ten days into a five-day step on
  the other track. Marking a milestone done is no work, so a marker lands the moment what it
  requires has, in the world and in `parallel_finish` (`is_marker`, from the facts, beside
  `wait_of`) alike. Neither moves a forecast of the prototype's twelve — there, a
  milestone's whole stretch is done when its marker is ready, so every worker is free — and
  Two tracks' milestones went from 3.3 days of error to 1.4.
- **Work already started runs now.** Re-dated, a later stretch's work in flight that waited
  for the stretches before it would credit a worker the team does not have: the person on it
  would be counted free for the stretch being worked. So it keeps its worker from tomorrow
  beside that stretch (`_resumed`'s `carried`, dated with `borrowed`), what is left of it
  when that stretch lands carries on into the next, and one that lands on the way is done,
  where it belongs, on the day it landed. The stretch being worked lands when its *own*
  work does. Two tracks' milestones 1.4 · 73 · 63 → 1.2 · 73 · 43, the whole plan 1.3 · 25
  · 22 → 1.2 · 27 · 17; the prototype's twelve cannot reach it, so the parity file is
  untouched. What error is left is later work nobody has started yet, which idle hands take
  ahead of the sequence — only stretches planned to overlap would see it coming, and that
  reverses the decision above, so it stays out.
- **The pace shares a day among the steps open in it.** *Adjust for Efficiency* measured a
  person keeping two steps going as working at half the speed, and re-dated everything left
  at it: Multitasking read 5.4 days of error with it on, against 1.7 off. `pace_so_far` now
  gives each of people's steps its share of every half day more of them were open than
  there are people — half days, because the pace is already counted middle to middle, so a
  step handed on at noon shares nothing with the one that follows it. With the toggle on,
  Multitasking 5.4 → 2.0, Late marking 3.5 → 0.4 (a step landed but not marked reads as a
  second one open, and now costs the first only its share), Blocked 4.2 → 3.5 (the stall
  counts as slowness only while nothing else was worked); nothing else moved.
- **Rejected: a day's grace before a step is late.** Taking a step as on plan until the day
  after its landing is over, and a done step's `since` a day late as on time, takes Late
  marking to 0.0 · 0 · 0 and moves most forecasts less — but it adds error to Supervision
  and Learning, it would change what *late* means for every plan, and it moves forecasts
  the parity file pins. One that helps some and costs others is at most the reader's
  toggle, never the model's, and a change to the prototype's scenarios goes there first.
- **Rejected: crediting work in flight by its share.** Crediting each of two steps one
  person keeps going with half their days took Multitasking 1.7 → 0.7, and Late marking
  0.3 · 50 · 46 → 0.5 · 163 · 67: the step landed but not yet marked halves the credit of
  the one after it, every night. The pace can afford the share because it reads finished
  steps; the credit reads a morning's statuses.
- **The views say it without a word.** Milestones landing on one day share one mark on the
  Work page and in the report — a wedge of each colour, each wedge picking its own step in
  the report — and one name, *M1 · M2* (`Presented.landings`, `Chart.landings`). On the
  calendar a day two stretches are both being worked is a stripe of each, side by side in
  sequence; a landing fills its day with every milestone landing on it and names them all,
  since the next stretch beginning that afternoon is the sequence, not news.

### Progress against the plan: the promise is derived, the past is recorded

The calendar says when each milestone lands; a person working the plan wants the other
half — how far it has come, and whether it is on the curve it promised. The plots under
the calendar answer with the shape a trip planner's energy graph has: the plan's curve,
what actually landed, and the plan as it stood on the day you compare against. The
decisions that carry it:

- **One measure: estimated days.** The days of done steps over the days of all of them,
  `schedule/progress.py` over `status_for` — the status aspect's reader handed in
  like `days_for`, so this module never learns where a status lives — and "toward a
  milestone" is **cumulative through its stretch**, because a milestone lands when
  everything before it has, not only what is new since the last one. A share by count
  of steps was offered beside it for a while, as a toggle; it was dropped because
  nobody reading the plots wants it and it calls a two-hour step and a two-week one the
  same thing, which is the one comparison a plan priced in days must not make. The
  count is still tallied and printed in words (*2d of 7d estimated · 1 of 4 steps
  done*), never offered as the share.
- **The expected curve is the simulation's own.** A straight line from start to landing
  would be a guess wearing the plan's colour. `parallel_finish` already knows the
  working day each step lands on; it now says so (`ParallelFinish.landings`, carried on
  each `Phase`), and the curve is the cumulative share landed by date — exact for the
  stored team and focus, and free, because the simulation ran anyway.
- **The past is recorded, because it is the one thing that cannot be derived.** What the
  plan looked like last Tuesday — how many steps, how much done, when it said it would
  land — is gone the moment the plan changes, and a chart of expected against actual is
  nothing without it. So a snapshot is written: one row per day, the stretches in
  sequence with their tallies, starts and landings, under a module id of its own
  (`progress_history`) so the assumptions file stays byte-stable. Three rules keep it
  from being the stored-answer mistake `ordering.py` warns about. It is written **only
  on a day something in it changed** — a window open on an untouched plan writes
  nothing — and last-wins within the day. It is written **directly, with its own
  origin, never onto the undo stack** (`recorder.py`; the PR refresher's rule): a record
  of what the plan looked like is not a user decision, and Ctrl+Z after marking a step
  done must undo the status, after which the next settle simply re-records the day.
  And it is written by whoever is there: the window's recorder after every settled
  change to any project, `dplanner progress record` for a plan driven from the
  terminal — the skill says when. Each row also carries the stretch's **landing knots**
  — what the simulation landed on each date — so the plan as it stood on any recorded
  day is drawn *exactly*, never reconstructed from what the graph looks like now.
- **One baseline, and the delta is the band between it and the plan now.** The first
  cut drew every earlier promise as its own dashed segment; the walk that redesigned it
  wanted one question answered clearly: *how has the plan moved since we started?* So
  there is one **baseline** — the plan as recorded on the **basis** day, the project's
  start unless another plan is picked in the strip (`progress show --basis`) — chosen as
  the last row on or before the basis, or the earliest row for a project older than its
  history. Neither answer is ever **today's own record** — the basis of a plan not yet
  begun is later than today, and a project whose history begins today has no earlier plan, and standing today's record in for one drew the plan now
  over itself and called the pair a comparison — two lines in one place under a heading
  saying *scope change*, which is a claim nobody recorded. `baseline()` takes `today` and
  all three surfaces pass it, so the window, the report and `progress show` agree on when
  there is nothing to compare with. A span the plan leaves empty (a milestone's own
  start date holding its work back past the previous landing) is flat in the expected
  line, with a knot at the day work resumes rather than a slope through days nothing is
  planned for; `progress.idle` derives it from the snapshot's stretches, and `progress
  show` prints it. The change
  list behind the delta needed a fact nobody kept: **an estimate now remembers what it
  was** — every write of the aspect carries the value it replaced with the day, one row
  per day (the value that stood when the day began), format 2 so an older build refuses
  to rewrite rather than drop it; `dplanner estimate show` prints it, the Estimate
  block's field wears it as a tooltip. Both the delta and the change list are measured
  **from the baseline's recorded day**, not from the basis: the record is what the
  delta compares against, so what the list names is what moved it, and a change on the
  record's own day is inside that day's record (last-wins). The basis is a way of
  looking — view state, never stored.
- **The Work page: the scope and the work done, on one scale in days.** The plots once
  answered in shares — the plan's curve against what landed, the plan then against the
  plan now with the band between filled by direction — and a share hides the question a
  growing plan raises first: a plan that doubled overnight and landed half of it reads
  *50 %* on both days. The v5 page (the prototype in `docs/exploration/time-estimation-2`)
  reads days instead, two plots on **one scale** (`Presented.scale`, in steps finer than
  1-2-5 because two stacked plots cannot afford half of each left empty), so a height in
  one is the same work in the other. *Scope* is the work the plan held on each recorded
  day against what the plan compared with held, the area between warm where it holds more
  and cool where less, with one ▲ or ▼ on each day it changed, by the day's sum
  (`scope_marks`: a day that added a step and took one away nets to nothing and says
  nothing). *Work done* is what was done by then, **dotted across a day no step changed
  status** (`Burnup.active`, from each row's `changed` count — or a moved done count, for
  a row written before the count was kept), so a day of work that finished nothing is told
  from a quiet one; beside it the plan's schedule from the day shown on, dashed, and each
  milestone where it ends — a check on the done line once its work is done, a dot on the
  schedule until then. Weekends are pale bands, because a flat week reads differently when
  two of its days were never working ones.
- **The Milestones page is a row per milestone.** Where the plan compared with landed it
  (hollow), where the plan now does (filled — a check once its work is done), an arrow between,
  each mark's date beside it — outside the pair where there is room, inside where there is not,
  left out rather than squeezed (`row_dates`'s rule, both surfaces) — and a hairline to the
  axis, so the day is read off the scale. The row's sentence is its tooltip (`milestone_words`),
  and the figure over the page says the whole plan's move in working days (`moved_words`: *▶
  +3d*).
- **The axes hold still.** Every plot is drawn against the reach of every record up to the
  day shown and the live plan (`reach_of`: the first day any starts, the last any lands,
  the most work any holds), so moving between days moves only the lines.
- **What a page draws is one `Presented`, and the report draws the same one.**
  `present.py` (Qt-free) is the prototype's `present.ts` and `brief.ts` less what the
  resume model made redundant: re-dated from what has happened, a plan is never behind
  itself, so there is no lag, no projection at today's pace and no verdict. The tab and
  `schedule/report.py` both read it, and `cli/report/parts.py`'s `Chart` of `Plot`s
  (`shift`, `scope`, `done`) and `Stretch`es is that page said as plain data, which
  `drawings.py` draws for the page and, through QtSvg, the PDF. Weekends and today's word
  are the renderer's own, facts of the calendar rather than of the plan. The report heads
  the chart with the plan it compares with — one heading for all three plots, as the tab's
  one picker is — and names the saved snapshots in its note, because paper has no tooltip.
- **One picker names the plan compared with; the page is the plan now.** The strip once
  carried *Compare [then] with [now]*, two pickers, because a review asks *1 November
  against 1 December* as often as *against now*. The v5 page keeps the then side — the plan
  at start, **the plan a week ago** (`A_WEEK_AGO`, the anchor of a weekly review), a saved
  snapshot, *Day…* — and the other side becomes History, a slider through the recorded
  days, rather than a second picker to explain. `resolve` finds the record a pick names —
  the last on or before the day, else the earliest, **never today's own record**, which is
  the plan now — and `pick_words` words it once for the picker's tooltip, the report's
  heading and `progress show`. A snapshot saved earlier today *is* something to compare
  with: `Presented.compared` asks whether the then side is the plan now, not whether it
  carries today's date. A saved snapshot's day is a dashed hairline through every plot.
- **History reads a record, and nothing writes while it does.** The now side is a slider
  over the days the recorder wrote a row, and today (`history.py`). On an earlier day the
  page reads that day's record in the live plan's place — `present` over it, with only the
  records up to it (`progress.until`) — so it shows what the tab showed that day, from what
  is stored and nothing else; the unsized count leaves the page, since no record holds it.
  The live plan joins the reach (`reach_of_rows`), so the axes hold still while the slider
  moves. The page follows the slider as it moves, through a 0 ms `Debounced` — once per
  event-loop turn, however many values a drag passes — rather than waiting for it to be let
  go. **Every writer is greyed while it looks back, saying why** (`writers_refusal`: the
  Budget, ⋯, *Save Snapshot…*, a click in the calendar), and a ✕ on the strip goes back
  to today: a writer that stayed live would write today's plan while the page showed an
  older one, and *hidden means absent* — the controls are there, only not now.
- **Saved snapshots are a second list, kept whole; automatic days stay last-wins.** A
  snapshot a person saves — *"What we thought on 1 November"*, with a note on the
  occasion — is a record of a decision, and it must mean the plan *at that moment*:
  riding it on the day's automatic row would let an afternoon's ten new steps rewrite
  what the morning's review had looked at. So `progress_history.json` (format 2) holds
  `days`, the automatic rows the recorder replaces within a day, and `saved`, rows with
  a `title` that nothing replaces and nothing expires; `saved_with` refuses a title
  already taken because a saved snapshot is found by its name. The save is a user
  decision, so it goes **through the undo stack** (*Save Snapshot*, *Forget Snapshot*;
  `dplanner progress save|list|remove`), unlike the recorder's automatic write; and
  every write of the entry — the recorder's included — carries the saved list along as
  stored, so a settle never loses one. The format bump exists for the `saved` key: an
  older build refuses to rewrite the entry rather than dropping what somebody saved.
- **A snapshot records the plan as simulated that day, not the graph.** The tempting
  alternative — store the graph and the estimates, re-simulate every old snapshot under
  whatever team the reader picks now — was weighed and left: it makes every snapshot a
  copy of the project, and the comparison it enables ("what would last month's plan
  have said with two more agents") is not the one the plots exist for. What a snapshot
  keeps is what the plan *promised* that day, for the team and focus of that day, and
  that is what a comparison against it must hold still. The scope is the part of a
  snapshot the team never touches — a total of estimated days is the same under any
  staffing — which is why the Scope plot reads across every snapshot without a
  re-simulation, and why `progress.volume` and `remaining` (what `progress show` prints)
  are step curves over the rows and cost the file nothing.
- **A change re-runs the page after a quiet spell, and the strip says so meanwhile.**
  The refresh is the heaviest reaction on the tab — a simulation, the calendar and every
  plot — and it is coalesced (`REFRESH_DELAY_MS`, *A view refresh is coalesced*). For half
  a second after an edit the page shows a plan that has since changed, so the strip's
  `UpdatingIndicator` turns from the moment a change arrives until the page has re-run.
  Moving the derivation to a worker thread was considered and rejected for the reason that
  section gives — pure Python competing for the GIL, and a thread alive at teardown is the
  suite's SIGSEGV shape — so the answer to "the recalculation must not lag the UI" stays
  the debounce, and the answer to "the user must see it is recalculating" is the indicator.
