# Collectors — scopes, features, citations, tests, documentation and notes

The reasoning behind `.claude/rules/collectors.md`: the rules there are the short, imperative form, and this file is why. `ARCHITECTURE.md` is the index of every area.

## What reaches a step is derived at read time

A note (`modules/notes/`) stores only what was said: a label, a title, a body, the step it
was made on, the steps it is *for*, and — only as the exception — a reach. Who *sees* it
is never written down. `reach.reaching()` walks the cone behind a step and answers with
two sets — the notes addressed to it, and the rest that reach it — the same rule as
ordering, for the same reason: `dplanner step link` rewires the cone with no window running
to notice, and a stored answer would be wrong exactly when an agent is driving. The Agent
tab's Notes pane, `dplanner note index` and the assembled agent prompt are three readers of
that one function and one `briefing_blocks` rendering, so no surface can describe what a
step inherits another surface would dispute. *A note is a record with a label* below has
the shape, why the index is an index, and why the graph decides who a note is for.

**And the index has a ceiling, which the first version did not.** A briefing is read once,
from the top, and an index nobody finishes costs what a log costs: on a 74-step plan with
320 standing notes the index came to 33,131 chars of a 47,157-char briefing, and the step's
own instructions sat after it. So `index_lines` keeps at most `INDEX_LIMIT` (20) notes per
label, the most recent, and **says what it left out** — `Decisions standing (20 of 64):`
and a closing line naming the rest and the `note list --label` that reads them. Three
decisions in that one sentence. *Per label* rather than one budget, because a label is what
an agent scans by and a flood of deferred items must not starve the decisions. *The most
recent*, because a plan's newest decisions are the ones its current work was shaped by, and
a superseded one has already left the index. And *a verb, not a count*: a line that said
only "44 more" would tell an agent it is missing something and not how to look. The cap
lives in `index_lines` and not in the composition root because `briefing_blocks` is the one
function the briefing, `dplanner note index` and the Agent tab's Notes pane share — put it
in the root and the window would stop showing what the agent was actually handed, which is
the whole point of that pane. `note index --all` drops it, because *does this note reach
this step?* is a question the narrower reach makes somebody ask, and no other verb answers
it: `note list` is the log, not what reaches a step.

## A test belongs to a step, and a step carries several

A description says what a step *is*. An acceptance criterion says what would make it
finished — and is then consumed, because the step closes. A **test** is the third thing: it
says how you would prove the step works, and it *outlives* the step. That is the whole
reason it is an aspect of its own rather than a paragraph in the description, and the reason
the tab's note is the first thing a reader sees: *"How you would know this step works — kept
after the work is done."*

**A test is not a node.** It belongs to exactly one step, never appears on the canvas, and
the graph knows nothing about it. A step carries several, each with its own id, title,
markdown body and — the point of the whole feature — its own result in a run. Making tests
nodes would have been cheaper in code and wrong in the model: forty work steps with three
tests each is a hundred and sixty nodes in a graph that is meant to show *the plan*.

**The body is a markdown string inside the record, not a `.md` file.** `FORMAT.md` gives a
node exactly one prose document, and a step carries N tests, so the one-document rule does
not stretch to them; the nearest existing shape is `spec`'s requirement records, and this
follows it. The trade is real and worth stating: a body edit diffs as one changed JSON line
rather than line by line. Test bodies are a few lines, so the whole new body is legible in
the diff — and if that ever stops being true, storing the body as an array of lines is a
format-2 migration away. Images are the exception and go where a description's images go:
the step's file area, referenced as `![](assets/…)`.

**Ids are minted per project, not per step, and are meant to be read.** `T100, T101, …`
across the whole project (runs are `R100, R101, …`, so the two never look like one
vocabulary spelled two ways). Three digits from the start, so every id in a project is the
same width and nobody mistakes one for a count. That is what lets a run's results be a flat
map, lets a person say "T107 failed" out loud, and lets `dplanner test-run mark T107 failed`
name a test without naming its step. Renaming a test therefore never detaches its history,
which keying on the title would have done.

**The editor is master-detail, and the split follows the width.** A stack of equal cards
was the first attempt and it stops working at the third test: every body is cramped and
none is properly readable. So the tab is a line per test (id, name, how it last did) and an
editor for the one selected — side by side where there is room (the step dialog, a wide
panel), stacked in the 360 px dock, switching automatically on resize. Two columns is what
makes a step with a dozen tests usable: a tall list beside a tall editor, instead of either
starving the other. The list sizes itself to its rows until the user drags the splitter,
and a drag is respected until the orientation changes under it. The body editor is a plain
expanding text well with the framework's markdown highlighter over it — structure visible,
bytes untouched — and its expand is the sanctioned one: a second `TextBinding` over a
`TextField` implemented against the record (`testing/section.py`'s `TestBodyField`), never
text copied into a dialog and back.

## A test says who it is for

A plan's roster of tests is not one list. The tests somebody sits down and executes by hand
are a different reading from the ones an engineer writes to prove a mechanism, and the
useful artefact is usually one of the two rather than the union. So a test carries an
**audience**, and the feature is that word appearing as a label wherever a test is shown and
as a filter wherever a list of tests is produced.

**The list is closed, and testing owns it.** `AUDIENCES` in `modules/testing/aspect.py` —
`qa`, `technical`, `other` — each an id, a label and a line of meaning, the same shape
`modules/notes/aspect.py` gives its `LABELS`. Free-form tags were the obvious alternative and
were rejected for the reason free-form tags always lose: `QA` and `qa` become two audiences,
and a filter over a vocabulary nobody agreed on is a search box with extra steps. It is
**not** wired beside `planning.kinds.scope_kinds()`, and that is a deliberate
difference: the scope kinds are handed to testing because they name aspects testing does
not own — a check, a feature, a milestone. Nothing outside testing has an
opinion about who a test is for, so handing the vocabulary in would have bought three
injection points (`TestsDeps`, `commands()`, `report_source()`) for a three-line tuple, and
`aspect.py` could no longer check a value on the way in. Widening the list is a line in that
tuple; making it configurable, when somebody asks, is a change in one file.

**A test carries several.** One thing can be worth proving by hand *and* worth proving
mechanically, and forcing a choice would put the same test in the wrong list half the time.
The cost is that a filter is a set intersection rather than an equality, which is four
characters, and that a cell may name two — which is the one thing the published page's
picks had to be taught (see below).

### Absence reads as *other*, and the lint asks anyway

This is the part worth writing down, because the two halves look like they contradict each
other and do not.

`audiences_of(test)` returns what the test stored, or `("other",)` when it stored nothing.
Every view, filter and export reads it, so a plan written before audiences existed changed
meaning nowhere and needed no migration pass guessing at answers: its tests simply read as
*Other*, appear under the *Other* pick, and print as *Other*. Absence encoding a default is
the ordinary `FORMAT.md` rule, applied in the direction the fact points.

But *other* as a fallback is not a classification, and the point of the feature is that
somebody says. So `project lint` gained `test.audience`, and it is the **one** reader that
looks at the raw `test.audiences` instead — because its question is not *what does this test
count as* but *has anybody actually said*. The lint is the migration, applied a test at a
time by the person who knows the answer, which is the only place that answer exists.

The step panel's three checkboxes are the second raw reader, and the first attempt got this
wrong in a way worth recording. Driving them from `audiences_of` renders *Other* ticked on
an unclassified test — and then it cannot be unticked, because unticking stores `()` and
`()` reads back as `("other",)`. A checkbox that refuses to come off is a bug the model
caused, not the widget. So the boxes say what is **stored**, three empty boxes on a test
nobody has classified, and the line under them — the one already carrying *Archived* and the
last run — says *"No audience set — reads as Other"*. That line is also, word for word, what
the lint asks for, in the place you would fix it.

### Every writer of a record is a chance to lose a field

Adding a field to `Test` meant finding six places that rebuilt one positionally from its
four fields — `test set`, `test archive`, the panel's archive, the bulk archive, the title
commit, and `TestBodyField.command`, which runs on **every keystroke in a test body**. Each
would have silently dropped the new field. They are all `dataclasses.replace` now, and the
rule generalises past this change: *a record with more than two fields is amended, never
rebuilt* — `remint_for_paste` already knew, which is why a pasted test keeps its audience
and loses only its id.

The same shape decided the format bump. `FORMAT.md`'s rule is *bump when an older writer
would destroy the new key, not when it merely would not write it*, and `write()` rebuilding
every record is exactly the destroying case, so `testing` is format 2 with a pass-through
migration. What the stamp actually buys is narrower than the two existing pass-throughs
claim, and the migration's docstring says so: `migrated()` only makes the **migration pass**
leave newer data alone with a warning. `set_module_data` checks no version and `read()`
never looks at the stamp, so an older build still reads these tests and still rewrites them
without their audiences. The stamp records that the entry may carry keys an older build does
not know; it does not enforce it.

### The filter on a published page belongs to the column, not to the verb

`dplanner report html --audience qa` would have been the obvious way to hand somebody a
QA-only page, and it is the one thing this feature deliberately does not have: `cli/report/`
never imports a module, and a flag spelled `--audience` would put a testing word inside it
anyway. What the report layer *can* own is "this column is worth picking from", so
`parts.Column` gained `filter`, `page.py` renders a `<select>` per filterable column, and
`report.js` applies them per table. One published page any reader narrows for themselves
beats an edition per audience, and it is what `page.py` had already decided for the steps
table's status.

That existing status filter folded into the new mechanism rather than sitting beside it, and
folding it taught the one thing a generic version has to get right. The old predicate read
the *class* off the rendered cell, because `_cell` prettifies what it prints — a status
loses its hyphen, a date becomes "in three weeks" — and an audience cell names several at
once, `", "`-joined. So a filterable cell carries its values in `data-values`, apart from
its words, and a pick matches one value at a time. The options are built from the rows, so
a plan with nothing blocked no longer offers *Blocked* — which the hard-coded four always
did.

## A test is filed under a category, and its words are the key

The audience above is one axis and it is closed. The axis a roster of two hundred tests
actually needs is the other one — *what kind of thing is this test* — and it cannot be
closed, because *Import*, *Permissions*, *Print layout* and *Rate limiting* are this
project's words and the next project's are different ones. So a test carries a **category**:
one line of free text, catalogued beside the project.

**The words are the key.** There is no minted id. `dplanner test set T100 --category
'Import'` is the whole story; a diff says which group a test moved to; an agent that has
never seen this plan can file a test from the catalogue it just printed. The alternative —
a stable `c3` with a label beside it — buys exactly one thing, a free rename, and charges
for it in every other place: a CLI nobody can type, a JSON nobody can read, and a label that
drifts from its id the first time two agents disagree. The price of the choice is that a
rename **is** a rewrite of every test carrying the old words, and that price is paid where
it is visible: `test-category set --rename` and the editor's Save both do it in one undoable
step, and the editor's row says how many tests it is about to move before it moves them.

**The catalogue is stored; membership is derived.** `{"categories": [{"name": …, "icon": …}]}`
beside the project, in the order somebody wrote them. It is stored for one reason that
matters: an agent reading a spec can lay the groups out *before* the tests that will fill
them, which is what makes the tests arrive filed instead of arriving and then being sorted.
What is *in* a category is never stored — `counts()` walks the tests, the same rule the
topological order keeps. And a category a test names that the catalogue does not is still a
real category: `catalog()` appends it, unglyphed, after the ones that were written down. A
typo therefore shows up as a group of one rather than as a test that has quietly fallen out
of every list, and the editor is where it gets merged.

**Absence reads as *Uncategorised*, and the lint asks anyway** — the audience's rule, one
vocabulary over, with one difference: `test.category` stays quiet until the project has any
categories at all. A plan that has not started filing its tests is not behind on anything;
the check exists to catch the test added *after* the filing was laid out, which is the one
an agent's next `test add` forgets.

### Two writers, one project entry

`runs` and `categories` are both project-level keys under the module id `testing`, and
`SetModuleDataCommand` stores an entry **whole**. Each writer returning a dict built from
its own half would therefore have silently deleted the other's key — a run started after
the categories were laid out would have taken them with it. `aspect.project_entry()` is the
one composer, both writers go through it, and `runs.write()` grew a `project` parameter so
it could. The generalisation is worth stating, because the module system invites the bug:
*one module id may name several shapes, and every writer of a shared entry must compose it
from what is on disk.* `FORMAT.md`'s "one module id, two shapes" paragraph is the same fact
seen from the data's side.

### The sort key is an ergonomic, not a second layer of filing

The category answers *what kind of test is this*. The question left over is the one
somebody **executing** a roster has: within *Set up new customer*, which twenty of these
can I do without switching screens? That is not a second category — filing it twice would
double the headings and halve the page — it is an **order**. So a test carries a `sort_key`:
free text, no catalogue, no editor, and no meaning beyond *tests sharing one belong
together*.

Three decisions make it worth having rather than clever.

**It always sorts, inside whatever group is current.** *Ergonomic order* on the Tests strip
is on by default and the switch is there to turn it **off**, not on. A sort key that only
sometimes sorts is one nobody can rely on halfway down a list with a device in the other
hand — and a project that uses no sort keys is ordered identically either way, because the
sort is stable and a keyless test keeps its place. Unticking it gives back the plan's own
order, which is the reading somebody following the *work* wants.

**Alphabetical, keyless last.** Adjacency is the whole win, so any consistent order would
do; alphabetical is the one a reader can predict without opening anything, and it is what
somebody who numbers their keys (*1. Sign in*, *2. Import*) already expects to happen. The
alternative — first appearance in project order — is invisible, and an agent that wanted a
particular sequence would have no way to ask for one.

**It is a column, not a heading.** `Table` groups flat: rows belong to the heading above
them until the next one, so a second level would have needed nesting in the primitive and
would have made folding a category ambiguous. It is also the wrong shape for the fact — the
rows are *already adjacent* once they are sorted, which is what a reader sees, and the
column is there to say what the run of rows has in common. So the Sort key column follows
the ordinary blank-column rule and appears the day a project starts using one.

The CLI half is `test add|set --sort-key`, `test list --sort-key` and `--flat`, and — the
one an agent reorganising a roster actually runs — **`dplanner test file`**, which takes
many tests and both filing fields in one call. That verb replaced `test-category assign`:
`test set` is one test with many fields, `test file` is many tests with the two fields that
say where a test goes, and having one verb per axis would have been two verbs for one
gesture. In the window it is the step panel's field — an editable combo, offering the keys
already in use so one view is not spelled three ways, and typed into to mint a new one,
because with no catalogue there is no editor to send anybody to. (A `Step ▸ Test Sort Key`
child menu filed many picked tests at once until the menu bar was sorted by subject; `test
file` is that batch now.)

### Grouping is one selector, and the tests' own vocabulary leads it

The Tests tab already grouped by feature, milestone or check. Category could have been a
second control beside that one — and would have been wrong: *by feature*, *by milestone*,
*by check* and *by category* are four answers to one question, so they are four entries in
one box. Making that true meant generalising what grouped the rows, because the three that
existed are facts about a test's **step** and the new one is a fact about the **test** — a
step's three tests are often three different kinds of thing, which is most of why the
category exists at all. `_Grouping` is two functions, *where does this row sort* and *what
heading does it land under*, both taking `(step, test)`; the collector grouping ignores the
test and the category grouping ignores the step. One shape asked twice, rather than two
mechanisms that will one day disagree about what a heading is.

Category leads the list and is the default *while the project has one*, because filing by
what a test is beats a flat roster and a project with no categories would otherwise open on
a single heading saying *Uncategorised*. The default stands only until the reader picks a
grouping themselves; after that their answer is the answer.

### The category headings fold, and the table remembers by key

Grouping two hundred tests is only half the reading. The other half is folding twelve of
the thirteen groups shut, which is what turns the roster into a page. So `Table.add_heading`
takes a `key`, and a keyed heading wears a disclosure chevron and swallows the click that
toggles it — the **whole row** is the target, because a heading selects nothing and runs
nothing else, so there is no second thing a click there could have meant and a seven-pixel
triangle is not a target.

What is folded is remembered **by key, inside the table, across `clear_rows`**. That is the
part that had to be got right: a host rebuilds a grouped table wholesale on every refresh,
and a fold remembered by row number would spring every group open on the next keystroke
anywhere in the project. The key is the host's own word — a category's name — so folding
*Smoke* folds the same group after a rebuild, after a rename that kept the name, and after
the tab is reopened over the same rows. The collector groupings pass no key and so do not
fold: a feature's tests are already few, and a reader who asked to see them beside each
other did not ask to unfold them one at a time.

The rows under a heading are **indented**, and that is the half of the reading the fold
does not give you. Every row starting at the heading's own x leaves a collapsed group and
an expanded one differing by nothing but the direction of a triangle, so a reader part way
down a roster has to hold in their head which heading they are under. Inset the rows by the
chevron's slot and the answer is on the page: the names begin past the disclosure triangle
rather than under it, which is the shape of every tree anybody has read.
It is **the name's indent, not the row's** — only the first column moves, and the picked
row's accent edge and hover wash still run the full width. Indenting the row itself would
give half the table a second set of column positions, so a column's values would no longer
line up down the page, and the selection edge would step in and out between groups; the
whole reason a roster is a table is that a column can be read down.

### Export is what the tab is showing

"Narrow it to QA, then hand that to the QA team" is one gesture, so `File ▸ Export ▸ Tests`
writes what the project's Tests tab is *currently showing* — its scope, its audience filter,
whether the archived are in — rather than opening a second dialog asking the same three
questions the strip has already been answering. `TestsActivity.showing()` is the one reader
of that, and `New Test Run` uses it too: the old `_narrowed_to` was the same walk for the
scope alone, and generalising it was cheaper than a near-copy beside it. With no tab open
the verb exports the project's whole roster, which is the honest reading of "no narrowing".
The CLI takes the narrowing as flags, because a terminal has no tab to read.

The two formats are deliberate and neither is the report. `cli/report/` publishes *the plan*
and names each test in one line; this writes *the tests*, filed under their categories, with
every body in full. Markdown is what a repository keeps and what the next agent converts
into whatever TestRail wants; HTML is one self-contained page whose every test is a
`<details>` that opens on its body, which is what makes a hundred of them scannable. Neither
inlines pictures: a test body's images live in the step's file area, and embedding them
would make this a publication, which is the report's job.

## A test is run from a panel, and a double-click there opens the test

A roster is not read, it is *worked down*. The gesture that was missing is the one between
two tests: mark this, look at the next. Doing it from the table alone means the body is a
one-line preview and the only way to read a test in full was to open its **step** — which
is the wrong thing twice over, because it is a page about the work rather than about what
you are checking, and because it is a modal that takes the list away every time.

So there is a **Test panel**, beside the roster inside the Tests tab: the test's id and
title, where it is filed, its last result, the four result verbs, *Show Step*, and
Previous/Next. The step editor has no seat beside a roster at all, which is what *The step
editor is a modal* settled. Four things about it are the design, and one about where it
stands.

**It renders the body rather than editing it.** A numbered list is a numbered list here,
not `1.` and a full stop. Authoring stays in the step panel's Tests tab, where the editor,
the images and the audience boxes already are, and *Show Step* is the door — one click, and
a door somebody executing a test wants anyway when what they find contradicts the step.
Rendering is also why the panel resolves `![](assets/…)` against the step's own file area:
the link the editor stores is relative to a directory nothing outside the plan can follow.

**Double-clicking a row in a Tests tab opens the test, not its step.** That is the one
deliberate exception to *double-clicking a step anywhere runs `steps.details`*, and the
reason is that in this table a row **is** a test — the step is not even a column, and the
row's own id is. The roll call does
the same, and because it spans projects and publishes no selection of its own, it hands the
verb a constructed context naming exactly that row. The verb (`test.details`) only
*reveals* the panel; the tab was already feeding it, so a single click updates it and a
double-click is what puts it on screen — and run from anywhere else, it opens the project's
Tests tab on the test first, since that is where the panel lives.

**Why it stands inside the tab.** It began as a dock panel in the right area, under the
project form, with the form yielding to it while a test was picked. A dock panel follows
the window: one instance, retargeted by whoever publishes — so it followed the pane in front
rather than the roster being worked, stayed on screen when no Tests tab was current, and
needed the form to know its name. A roster is worked *in* its tab, so the panel is the
tab's (*A panel inside a tab follows the tab*): one per Tests tab and one in the roll call,
fed by that table's own pick, gone with the tab and there again when the tab is. That is
also where the preference went — a tab's panel has no *View ▸ Panels* entry, so
`tests.side_panel` is one bool for every Tests tab, written by the strip button, the frame's
close and the double-click alike — and why Previous/Next walk by offset over *this* tab's
rows: the reader's own scope, filter and ordering, greyed at either end.

**A test is named with its step, never on its own.** Ids are minted per *project*
(`modules/testing/aspect.py`), so `T101` names a different test in every project in the
library, and this panel spent its first week looking one up by id across the whole library —
which answered with whichever project sorted first, so a reader working down the third
project's roster was shown the first project's namesakes. There is no fixing that at the
lookup: an id is not an address. Every view that picks a test therefore publishes
`selection/step/<id>` beside `selection/test/<id>` — the project tab's selection did already,
and the roll call, which is the one view holding several projects at once, now does too —
`test.details` is greyed without the pair, and the panel reads the test out of that one step.
`TestsModule._selected_tests` had the rule from the start, one step along: it narrows to the
context's project before it matches an id.

**Next and Previous move the table's selection, never the panel's own.** A panel may not
publish a selection — it follows the context, and writing to it would fight whatever else
is showing. So the panel asks the Tests tab to pick the neighbouring row, the table
publishes as it always does, and the panel follows like any other change. It is the *tab's*
order that "next" means, not the project's: the reader's scope, their audience filter and
their ergonomic order are what put the next test where they are looking. With no Tests tab
open there is nothing to walk, and both verbs are greyed saying so — which is honest rather
than defensive, because "next" has no meaning without a list.

## A right-click on a test is its step's

A row in a Tests tab **is** a test, and for a while its right-click led with the result: the
*Test* child menu's `test_result` band flat, then the whole Step menu one level down as a
`Step` child — two renders of the registry through `fill_bands`, never a copy, since *a
right-click renders a menu, never a copy of one* is a rule about entries and says nothing
against rendering two. It was the reason `fill_menu` learned to take a `group` **with** a
`submenu`: two groups fed the Test child, and the row wanted one of them.

It went when the menu bar was sorted by subject. Type and Test left the menus for Step
Details (*The menu bar is sorted by subject*), and the result verbs with them: a result is
recorded from the Tests strip and the Test panel beside the roster, both of which stand
right next to the row. With nothing about the test left to lead with, the popup is its
step's Step menu, the render every table gives its rows, and the Tests tab composes
nothing of its own. The double-click is still the exception — it runs `test.details`, not
`steps.details` (*A test is run from a panel*).

## A reference is a link, and a link is a preview

Test bodies point at each other. *Run this after T101 passes*, *the fixture T104 leaves
behind* — a roster is a sequence, and prose is how it says so. The reader had the id and
nothing to do with it: ids are minted per project and the table printed every fact about a
test except the word it is called by, so following a reference meant opening tests until
the right one turned up. The **Id column** is half the answer and the link is the other.

**What counts as a reference is decided by the project, not by the pattern.** `T` and
digits on their own word boundaries is only a candidate; it becomes a link when the project
has minted that id and not otherwise. An unminted `T999` staying plain words is the point
rather than a shortcoming: a body may legitimately quote an id from a spec whose tests are
not written, and a link that goes nowhere is a worse answer than no link. An id inside a
code span or inside a link that already points somewhere is left alone too — code is how a
body writes *about* the shape of an id.

**The linking is done to the rendered HTML.** `core/markdown.py` escapes every piece of
user text and lifts code spans, links and images out before anything else runs, so by the
time a body is HTML the only `<` in it opens one of our own tags — which is what makes a
walk of it exact rather than a guess. Over the markdown instead, the same pass would put
an anchor inside a fenced block, inside a URL, and inside the text of somebody's link.

**Following the link opens a modal, and that is the design rather than a compromise.**
Picking T101 in the table is a move: it loses the test being read, and a plan has no back
button. So a click opens a preview over what you were reading — glance, shut it, and you
are exactly where you were — and *Show in Tests* is the deliberate move, a button rather
than the only thing a click could have meant. The preview links its own references and
keeps a **trail**, because a preview that dead-ends at the first reference has the defect
it exists to fix; **Back** is a list and one button, and without it the second reference is
the one nobody follows.

**Show in Tests widens the tab only when the tab is what is hiding the test.** A Tests tab
can be scoped to a collector, filtered by audience, hiding the archived, and folded shut by
category — any of which can be why the asked-for test is not on the page. Answering that
request with nothing would be the worst of the three options; widening every time would
throw away a narrowing the reader made. So `TestsActivity.reveal` checks first, and only
then takes the narrowing off, and `TestsTable.reveal` opens the group the row is folded
under and scrolls to it. Opening the fold is deliberately *not* part of `select_tests`,
which runs on every rebuild to keep the selection: unfolding there would spring a group
open the moment the reader shut one holding the row they had picked.

**The preview and the panel are the same two widgets.** `cards.py`'s `TestHead` and
`TestBody` are the test as it is *read* — what it is called, where it is filed, how it last
did, and its body rendered. The Test panel puts its verb strip between them and the preview
puts nothing there, and that is the whole difference; written twice, one of them would have
grown a fact the other lacked by the second change.

## The test format is read before a test is written

A test is executed by a stranger — a year later, by a person with no memory of the work or
by an agent with no context at all — and the thing that makes one executable is dull and
uniform: **what must already be true**, then **what to do**, under those two headings.
Nothing said so anywhere, so every plan invented its own answer — and an unexecutable test
always fails the same way: a paragraph of narrative with the setup implied and the pass
condition buried at the end of it.

So there is a house format (`modules/testing/format.md`), and it is delivered exactly the
way the default graph shape is (*The default shape rides through the same door*): **printed
by one verb, never stored in a plan, and behind a gate.** Each of the three is the same
decision as its cousin one level up.

**Printed, never stored.** The obvious move is a project-level convention seeded at
`project create`, and it is the same trap: a plan's own prose reaches every agent briefing,
so a house document written into one is paid for again on every step anybody ever executes.
`dplanner test format` prints it, `test add`/`test set` refuse until it has been read, and a
briefing never carries a word of it — which a test pins.

**Behind a gate, because the skill is Claude's alone.** The shape could have been three more
paragraphs in `SKILL.md`. That reaches Claude and not Codex or OpenCode, and it is paid for
in every session including the ones that never write a test. The gate inverts both: the
document costs nothing until an agent is about to write a test body, and then it is
unavoidable, whichever agent CLI is driving. It cost 6.7 KB of document, 567 bytes of skill
(the concern, not the shape) and a `‡` on two verbs in the command index.

**The door is narrow on purpose.** Only the two verbs that write a body declare
`reads_guide` — `test add` and `test set`. Reading, filing, archiving, exporting and
`test-run mark` do not, so an agent handed a roster to *execute* never meets the gate;
neither does `step add --test`, which names a test and writes no body. The gate is for the
agent that is about to write prose somebody else will have to follow.

**One record, two doors.** The topology gate already had the mechanism — a per-user,
per-machine file of digests under `core/config_dir.py` — so the file became `reads.json`
(from `topology-read.json`, a name that stopped describing it), holding namespaced keys:
`topology:<project id>` per project, `guide:test format` per document. `ReadRecord` is the
file and the digest comparison; `TopologyGate` and `GuideGate` are the two sentences written
over it; `gated()` puts whichever the verb declared in front of its handler. The difference
between them is what the digest is *of*: a topology is the project's own text, so the record
is per project, and the format is this build's, so one reading covers the machine — and
changing `format.md` in a release un-reads it for everybody, which is the intent.

### Screenshots were a convention, not a feature

The ask was for screenshots in a test with a sequence and annotations, and the honest answer
is that the mechanism already shipped: `dplanner test attach` copies an image into the
step's file area and prints the `assets/…` link, content-addressed like every other asset,
and a test body is markdown. What was missing was only what nobody had written down.

The feature that was *not* built is worth recording, because it looks right. A structured
list on the test record — an ordered array of `{asset, caption}` — would give a renderer a
real sequence to draw and a place to hang a caption. It would also mean a schema migration,
a second way to put an image in a body beside the markdown link that already works, an
editor in the step panel to maintain it, and a decision in every renderer (the tab, the Test
panel, the export, the report) about what to do when the two disagree. That is a feature's
worth of surface for something the body already expresses: **the step number is the
sequence, and the alt text is the annotation.** `![2 — the signing dialog; Sign stays
disabled until a name is typed](assets/…)` sorts itself, renders everywhere markdown
renders, survives an export that carries no images, and needs no format bump. The rule the
document adds is that a picture goes on its step's line rather than in a gallery at the end,
which is what makes a body read as a sequence at all.

### Concurrency is a question the document asks, not a check lint runs

A test roster written against one actor on a freshly-loaded screen passes completely while
the expensive bugs ship: one reviewer signs a document that is already open, unsigned, on
another reviewer's screen, and nothing in the plan ever said what the second Sign should do.
The format document names the four shapes this takes — a stale screen then a write, two
writers at once, isolation between tenants or roles, and work happening behind the user —
and says how a concurrent test is written: the actors and what each session has loaded go in
the preconditions, and every step names its actor.

It is deliberately **a question, not a rule**. Whether a product is concurrent at all is not
derivable from a plan — no aspect says so, and a single-user tool with a roster of
single-actor tests is correct, not incomplete — so a `project lint` check would fire on
plans that are right, which is the one thing lint may not do (*Two shape checks, and only
one of them earned lint*). What the document asks for instead is that the agent raise it:
go through the roster on any system where more than one person or process touches the same
data, say which tests need a concurrent sibling, and where the user has not said whether
concurrency matters, propose rather than decide. The concern — not the shape — is in the
skill too, in one short paragraph, because the agent who should raise it may be the one
planning rather than the one writing, and never open this document at all.

## A test goes stale when the step under it moves

Eleven tests on one real plan contradicted the product and lint said nothing about any of
them. Nothing was broken: three decision notes had changed what the work should do, months
after the steps carrying those tests were marked done, and a test is exactly the thing that
does not notice. `dplanner test review` is the report that notices — `coverage review`'s
shape, because it answers the same kind of question: *what needs a person after something
underneath it changed?*

**The comparison is against the test's last run, because there is no other date to use.**
The obvious reading of "a done step with a later note" wants the day the step became done,
and `step_status` stores `{"status": "done"}` and nothing else — no stamp, anywhere. Adding
one was the wrong fix twice over: it is a stored fact where this codebase derives, and it
would answer for nothing that happened before the day it shipped, which is precisely the
eleven tests that prompted the feature.

So the verb asks the question the data can answer, which turns out to be the better one:
**has this test been run since the note landed?** `runs.latest_results` already gives every
test's last outcome in one pass, and a run carries the day it was closed — or opened, for a
run still open, because a result recorded in it was recorded then and not whenever the run
eventually ends. A test nobody has ever run is behind *every* note on its step, which is the
honest reading: nothing has established it against any of them. A note nobody dated is the
mirror case — it cannot be *shown* to postdate a run, so it counts only against a test that
never ran, rather than putting a row in front of somebody that they cannot act on.

**Only a done step is asked.** Work in progress is meant to be ahead of its tests; reporting
it would bury the real findings under every step anybody is currently working on.

**Which labels unsettle a test is named in the composition root**, `_unsettling_notes()`,
and the reason is the one the scope kinds were handed in for: `modules/testing/` may not
learn the notes module's vocabulary. A `decision` changes what the work should do and a `spec-change` records where
it departed from the spec — either can leave a test proving last month's answer. A
`handoff` says where the code lives, a `later` defers work, a `post-project` note is for
afterwards; none of them makes a claim about what a test should assert, so none should put
one in front of anybody. Notes reach testing as a neutral `(id, label, title, made)` keyed
by step — `cli/scopes.py`'s `CoveredTest` hand-over, one layer down — so testing learns
nothing about what else a note carries.

Superseded notes are dropped on the way. The note that replaced one is itself a decision,
made later, so it already stands for the doubt; keeping both would name one test twice for
what is one thing to do. For the same reason a row is **per test, not per note**: a test
behind three decisions is one piece of work, and the newest note is the one that says what
it now has to prove.

**A verb, not a lint check.** Lint is for findings with a crisp fix — a missing body, a
dangling edge. Whether a test still proves the right thing needs somebody to read the note
and decide, and the two ways out (re-run it, or rewrite what it asserts) are a judgement
rather than a remedy. `coverage review` drew that line first, and this follows it.

## A check is a scope over the graph, and so is a milestone

A **check** is a step type that stands for everything behind it having been verified. What it
covers is not stored: it is the `requires` cone, filtered by which of those steps carry tests.
Storing that list would let `dplanner step link` leave a check claiming coverage it no longer
has, with no window running to notice; it is the same rule as the topological order and
progression, for the same reason.

The part worth noticing is that **a milestone is already the same scope**, and so is a
**feature**. The walk takes a step id and answers for any step at all, so the Tests tab's
scope selector, the *Covers* tab, `dplanner scope show` and `test-run start --scope` are four
readers of one function — and a run can be scoped to a milestone without a line of code that
knows what a milestone is. A check is a scope you *declare*; a milestone is one you already
had; a feature is the one people actually name and demo.

### The cone stops at the next collector

What separates the three is a single predicate. `domain/ordering.py`'s `cone(origin, stops_at)`
walks `requires` backwards and refuses to pass **through** a step `stops_at` claims — it
records it as a *boundary* and stops there:

| Asked of | `stops_at` | Because |
|---|---|---|
| a check | nothing | it stands for everything behind it having passed |
| a milestone | milestones, and the start | it holds what is new since the last one |
| a feature | features, milestones, and the start | it holds its own work, up to the previous feature |

The start is the one row that is not a collector; *The origin is nobody's* below says why it
is there at all.

`ordering.upstream()` is that same function with nothing to stop it, which is why there is one
walk here and not two.

The alternative was a stored membership — a `feature` field, or a `belongs_to` edge kind. Both
were rejected for the reason the whole *Deriving rather than storing* section gives, and one
more specific to this shape: a `belongs_to` edge would draw the same relationship a second
time, beside `requires`, and the two would eventually disagree. The semantics wanted here —
everything upstream, minus what an earlier collector already took — *is* the `requires` cone.
There was nothing to add.

### `stops_at` and `gathers` are different questions

A milestone stops at milestones, and is *read* as a list of features. Those are not the same
fact and conflating them was the first attempt's bug: the boundaries are what the walk
deliberately excluded (an earlier milestone already accounts for them), while the group
headings are the finer collectors found **inside** the contents. So `ScopeKind` says both, and
`gathers` is empty for a feature — the finest grain, read flat.

Both are written literally in `planning/kinds.py`'s `scope_kinds()`, beside the kind facts
they read. A rank integer was considered and dropped: three lines a reader can
check by eye beat an ordering abstraction over exactly three things, and the ordering would
have to be explained anyway.

### A step two features both wait on belongs to both

Neither is behind the other, so neither has a better claim, and any tie-break would be
arbitrary. `gatherers()` therefore returns *both* owners, the Tests tab files the step under
one joint heading rather than listing its tests twice — a test in two rows is a test marked
twice — and `dplanner project lint` reports it as `scope.shared` so the ambiguity is nameable
rather than merely visible. Two siblings came free from the same inversion:
`scope.ungathered` (a step carrying tests that no feature waits on — work that reaches no
milestone) and `scope.gathers-nothing`, which generalised the old `check.covers-nothing`.

### Both readings, and when the switch is worth showing

A milestone honestly wants two answers: *what does it add* (the truncated walk) and *what must
pass for it to ship* (the whole cone, regressions included). The Covers tab offers both — and
shows the switch **exactly when the truncated walk handed off to an earlier collector** (a
boundary some kind carries — `handoffs()`). That is a pure function of the data rather than a
property of the kind, which makes it right in two places at once: a check never has a
boundary, and neither does the first milestone in a project, and in both cases the two
readings are the same answer. A control with one outcome is noise.

### The origin is nobody's

The default topology (`cli/shaping.md`) asks for one step at the origin with work fanning out
of it in parallel. Every branch traces back to that step, so every feature's cone reached it,
`gatherers()` returned all of them, and `scope.shared` reported the recommended shape as an
ambiguity. The remedy the finding offers — link one feature behind the other — would have
serialised the very parallelism the shape exists for. The finding was right about the walk
and wrong about the plan: the origin is not work any feature did.

So a **Start** aspect (`modules/step_start/`, a bare `{"on": true}`) marks it, and the two
kinds that *own* work — a milestone and a feature — stop at it. Four decisions shaped it:

- **A marker, not an inference.** "The step nothing precedes" is several steps while a plan is
  being built, and one of them is usually work somebody forgot to link. Inferring the origin
  would make that step quietly nobody's too, where today the canvas rings it and
  `graph.orphan` names it. The marker is the plan saying where it begins — the distinction
  shaping.md already drew between *the plan begins here* and *somebody forgot a link*.
- **Only the owners stop at it.** A check owns nothing; it stands for everything behind it
  having passed, and the start's own tests are part of that. So a check still stops at
  nothing — which also keeps *a check never has a boundary* true. `scope.shared` and
  `scope.crosses-milestones` only ever ask the owning kinds, so the finding goes away all the
  same.
- **Carrying is untouched.** A start marked as a milestone is a milestone with an empty cone
  (a start waits on nothing), and `scope.gathers-nothing` already says so with its own verb.
  Excluding it from `carried_by` was considered, and it makes a half-scope: `scope show`
  would refuse it while its key, `feature list` and the coverage trace still called it one.
- **A boundary is not always a hand-off.** Stopping at the start makes it a boundary of every
  feature right after it, and a boundary is what `scope show` names as *after* and what makes
  the Covers tab offer a second reading. The start is neither — it is where the graph ends, not
  an earlier collector that took something — so both ask `planning/scope.py`'s `handoffs()`,
  the boundaries some kind carries, and `scope.ungathered` skips a step the feature kind stops
  at without carrying (no link could hand it to one). Nothing new in `ScopeKind`: a third
  field would have been read by exactly those two surfaces.

What else it touched, and why it was allowed to: the start's documentation fragment and tests
drop out of every feature's and milestone's reading, so a collector compiled *with* the
start's fragment reads `docs.compiled-stale` once — true, since it no longer reads it — and
the Tests and Documentation views group the start's own under *Not in any feature*, which is
also true. Two walks wrote the feature stopping rule by hand (the briefing's *Flows into*, the
coverage trace); both now read the wired kinds, which is how the Steps lane stopped drawing
the origin under every feature. The start's shape has its own lint, **`graph.start`** — a
start that waits on something, a plan with two — naming `step unlink` or `start clear`; the
verbs refuse nothing, like `feature set`. It wears **no card mark**: the primary icon (F5)
gives it the person glyph like any step, its key stays `S`, and the origin already reads as
the origin, since every arrow leaves it. The noun is `start` (`dplanner start set|clear`,
`step add --start`), not to be confused with `schedule start`, which dates the plan's first
day.

**The schedule still dates the start.** `planning/schedule.py`'s `stretches()` stops at
milestones only, so `progress show`, the Time tab and milestone colours count the start in the
first milestone while `scope show` and the coverage trace give it to none. That is on purpose:
a stretch is the first milestone's whole cone and every later one's cone past the milestones
before it, so the start — which the first cone reaches — is dated where it is worked, first.
Ownership and dating are different questions, and only ownership was wrong.

### Who owns which half

`step_check` is a bare `{"on": true}` marker in its own package with a Type toggle and nothing
else; a feature step's marker names the catalogue record it realises (see *A feature is a
record, and a feature step is its instance*), and the walk reads only whether the marker is
there. The *Covers* tab that shows what any of them
gathers is registered by the **tests** module, because that tab is a list of tests, which is
testing's business. That keeps the wiring one-directional: `TestsDeps` takes the wired
`ScopeKind`s, and neither marker module needs anything from anybody.

The CLI made the same call one level up. `check show` would have become three near-identical
verbs the moment features arrived, so it became **`dplanner scope show`** in `cli/scopes.py` —
the cross-feature home `cli/lint.py` and `cli/authoring.py` already established, where the verb
owns the report and the composition root hands it the kinds and the coverage walk. `cli/` still
imports no module, and no module imports `cli/scopes.py`.

## Documentation is fragments, and a collector compiles them

A plan says what work will be done. It said nothing about what that work *produces for a
reader*, so release notes and user guides were written at the end by reading back over the
graph by hand. Two aspects close that, and the shape of them is the whole decision.

A **documentation fragment** is what one step adds to the product's documentation — `docs`,
prose beside the step, written while the work is fresh. A collector's **documentation** is
what a feature or a milestone makes of everything it gathers — `docs_compiled`, prose beside
the collector. Those are the words on every surface; the two on-disk ids are the older ones
and stay, because an id is a contract and a label is a sentence.

**Two aspect ids in one package, not one.** A node holds exactly one prose document per
module (`FORMAT.md`), and a feature legitimately has both: its own note, and the document
compiled from the four steps behind it. Putting the second in `module_data` as a string
would cost it the text stack — positional splicing, undo coalescing, a line-by-line diff —
which is the trade that section already refuses for prose.

### There is no step kind for compiling

The first attempt had one: a *Compose Docs* step you created, linked into the graph, and
ran. It worked, and it was wrong. A feature and a milestone **already are** the collectors
the graph defines — `cone()` and `planning/scope.py` have answered "what is behind this, up to the next one"
since checks arrived — so a second kind of collector, existing only to collect, was a node
somebody had to remember to create for a question the graph could already answer. Deleting
it removed a `StepKind`, a Type toggle, a medallion glyph, a mnemonic table the collision
had forced, and two CLI verbs. Every project that already has features and milestones now
gets documentation without adding anything.

Compile is therefore a verb on a collector, and the vocabulary is one predicate the
composition root already wires: *is this step a collector?* is `kind_of(scopes, step)`.

### Compiling launches a peer, and the window writes no document

The first version compiled with an in-app LLM call: a `TaskRunner` body around
`framework/llm_service.py`, the answer home on a queued Qt signal, the document and its stamp
landed as one undo entry. It worked, needed a provider key in *Settings ▸ LLM* to do anything
at all, and nobody used it — while the agents actually doing the work were already writing to
the plan through the CLI all day. So *Compile with Agent…* launches one, with a briefing built
from the fragments, the project's compilation instructions and the verb to finish with, and
the window's own compiler is gone. Five things follow.

**The docs module words the briefing; the launcher wraps it.** What a fragment is, which verb
lands a document and that `assets/…` links must survive are this module's vocabulary
(`modules/docs/prompt.py`, Qt-free); the header and the preflight every hand-over gets are the
agent module's (`prompt.handover_prompt`, shared with the conflict hand-over). The two meet at
two typed callbacks on `DocsDeps` — `compile_profiles` and `compile_with_agent` — wired by the
composition root, which is `library_watch`'s `hand_to_agent`/`agent_refusal` shape exactly. A
third module wanting a launch copies that; nothing imports the agent module.

**Nothing lands on the undo stack any more.** The document arrives minutes later from another
process and the store adopts it entry by entry, like any outside change — so *An LLM call is a
task*'s "the result lands on the undo stack, because a person pressed a button" stops applying
here. Ctrl+Z cannot put back a document an agent replaced, which is why the one gesture that
would overwrite a document that has text **asks first**, once for the whole gesture, and says
that there is no undo. Everywhere else in this application the confirmation was deleted and
undo made the case for it; here the safety net genuinely is not there.

**The run is the collector's, and it claims nothing about the work.** `_launch` hands the
shell to the run tracker as it does for Run Agent, so a compiling agent wears the chip and the
marching ring, appears in the Agents browser, is reachable through *Show Agent Terminal* and
leaves a usage row when it ends — for nothing, because the collector is a step. What it does
**not** do is `mark_started`: an agent writing a feature's documentation is not doing that
feature's work, and the claim is made in Run Agent's own step loop rather than in `_launch`
for exactly this reason. Two runs on one step are told apart by their terminal windows —
`_launch` takes a `note` the window title carries (`F7 Auth (documentation)`) — and by nothing
else, which is the pre-existing shape for two Run Agent launches on one step.

**Who compiled a document is the launching window's record, not the plan's.** The stamp in the
plan says *when* and *from what*; `provider` and `model` left it (`docs_compiled` format 2),
because with the CLI as the only writer they would hold one value each forever. Attribution is
the worded launch `compile_with_agent` returns, kept per collector in the docs module's own
`user_config` — exact, where reading the step's newest `AgentRun` back would credit a feature's
document to whichever agent happened to be working on that feature. The cost is stated rather
than hidden: a plan opened on another machine says when a document was compiled and not by
whom, and a compile nobody launched from a window is attributed to nothing. It is also why the
panel's live line says *an agent is working on this step* and never *compiling this now* — the
window cannot tell one run on a step from another, and the point of the line is to stop a
second launch.

**Compiling a whole project takes the frontier.** *Compile Out of Date…* launches one agent
per collector whose fragments have moved on — except a collector whose own sub-collectors are
also due, because a milestone reads its features' *compiled* documents and one launched beside
them would read documents about to change. `collect.sub_collectors` is that question, the same
two calls `sources_for` makes; the verb says how many are waiting, and the next gesture takes
them. Past *Max agents launched at once* the count itself refuses, as it does for a selection
of agent steps.

### A milestone reads its features' documents, not their notes again

`ScopeKind.gathers` says a milestone is read as a list of features. `collect.sources_for`
takes that literally: for each feature inside a milestone's cone it reads that feature's
**compiled** document — falling back to the feature's own fragments where it has none, so a
half-compiled project still produces something honest — plus the fragments of everything in
the cone no feature took. A feature has `gathers=""` and so reads flat.

Two things follow, and they are the reason for the shape. A milestone folds polished prose
rather than saying everything twice. And **recompiling a feature marks its milestone out of
date by itself**, because the milestone's sources are that feature's text — the cascade the
feature needed, with no notification plumbing at all.

### Staleness is a digest, not a timestamp

Nothing in the model records when a fragment was last edited, and adding that to support one
check would be storing a derivation. So a compile stores the **digest of what it read**
(sha256, sixteen hex, the convention `domain/assets.py` content-addresses blobs with) and
"is this out of date" is a comparison against the same walk run now.

That is exact where a timestamp is a heuristic, and it is right in a case a timestamp would
get wrong: `dplanner step link` changing what a feature gathers changes the digest, and the
document says it is out of date — which it is. It also gets the other direction right.
**Hand-editing a compiled document does not make it stale**, because the digest is over the
sources, not over the output; a person tidying the model's prose is finishing the job, not
invalidating it.

Three states fall out, and they are a pure function: no entry is *never compiled*, a
matching digest is *current*, anything else is *out of date*. The Documentation view says them
in words, in the row's trailing slot — and **nothing at all when a document is current**,
which is what the hollow ring and the filled dot bought before the row had words to spare.
What the last compile *was* — how much it read, when, and which agent this desk handed it to —
is the line underneath.

The digest covers the **sources**, not the compilation instructions: rewording how every
document should read does not mark every document out of date, exactly as hand-editing one
does not. Both are the same rule — the digest is over what a compile *read* — and the second
is a surface a person edits now, so it is worth saying out loud.

### Who owns which half

`modules/docs/` owns both aspects, the fragment editor, the Docs folder and the Documentation
view; `collect.py` is the one derivation, Qt-free, with four readers (the view, `docs collect`,
`docs status`, the compile briefing). The collector kinds arrive as an argument, exactly as
`TestsDeps` takes them — **nothing is added to `scope_kinds()`**. A fourth kind there would
have put documentation in the Tests tab's scope selector and its Group by, and given every
collector a Covers tab it never asked for: four surfaces learning about documentation to
serve none of it.

The project's **compilation instructions** are `modules/docs.md` beside the project — the
`docs` id spanning node kinds, which `FORMAT.md` sanctions and `step_agent_instruction`
already does. They have three presenters over one field: *Project ▸ Settings…*'s tab, a tab in
the Documentation view (two bindings, one undo stack, the standing agent instruction's shape),
and `dplanner docs set/show --for-project`. The CLI half is not a convenience: every compile
briefing opens with them, so an agent compiling without a window launch must be able to read
what its document is meant to follow.

## A test result is not a step status

Two vocabularies, deliberately sharing no words. A step's status is `pending`,
`in-progress`, `done`, `blocked` — where the *work* stands. A test's result is `ok`,
`failed`, `skipped`, or absent — what happened when somebody *ran* it. A test on a done step
is not "done"; it is a thing that passed last Tuesday and might not today.

**A failing test gates nothing.** It does not block a milestone, and it does not touch
`progression()`. Progression answers "what can be launched right now, given the graph and
the stored statuses"; folding results into it would quietly make `dplanner progression show`
answer a different question. A person deciding whether to ship reads both.

## One open run per project, and a run freezes its membership

A **test run** is one occasion of executing a scope: which tests were in it, and what each
one did. Two rules do most of the work.

**At most one run is open per project.** Starting a run closes whatever was open. That is
what makes "mark these twelve ok" a pure function of the context — there is no hidden
"which run" the user must have selected first, no verb carrying one, and the action state
can say *"Mark Ok — start a test run first"* rather than being mysteriously inert. The Tests
tab's Run selector can still *show* a closed run; it is read-only, because a record of an
occasion is not an editable list.

**A run freezes the tests it was opened over.** `tests` is a stored list of ids, not a live
query, so adding a test or relinking the graph afterwards cannot change what a closed run
means. The cost is that a test added mid-run does not join it — which is correct: it was not
there. A missing result reads as pending, so opening a run over two hundred tests writes two
hundred ids and no statuses, and the file grows as the work is actually done.

**The latest result is the newest run that recorded one**, not simply the newest run. A test
absent from yesterday's run has no answer from it, and reporting "not run" there would erase
what last week established.

## A feature is a step

A specification used to be read into **requirements**: quoted obligations in the spec
module's index, linked N:M to steps, cited in briefings, checked by lint. It was honest and
it was the wrong grain. Nobody demos a requirement; people name, build and test *features*,
and the graph already knew that — a feature step gathers the work that flows into it, and
`dplanner scope show` reads it.

The next answer was a **record**: a feature in the project's catalogue whether or not it
was on the graph, which a step later became the instance of. That bought one thing — the
feature *before* somebody cuts a step for it — and it cost a parallel store. With steps as
cheap as they are, the trade stopped paying:

- the record's `title` was the step's title and its `description` the step's description,
  so a feature had two of each and they drifted;
- *placed*, *unplaced*, *duplicate* and *unregistered* were four half-states, each with a
  lint check, a refusal and a phrase in the panel;
- undo had to restore either side independently, because the record outlived its step.

**So a feature is simply a step that carries the feature aspect.** Its name is the step's
title, its description the step's prose, its pictures the step's file area, and the only
fact that was ever the record's own — the specification passages it was read out of — is
the aspect's own data (`{"on": true, "cites": […]}`, format 3). Three consequences are the
design:

- **There is no verb that creates a feature.** `step add --feature` is the door in and
  `step remove` the door out, which is what keeps a feature on the graph *by
  construction* rather than by a check that notices when it is not. The passage flags
  (`--document`, `--quote`, `--page`, `--strict`) live on that same author, because
  *authoring a step is one verb, many modules* and creating a feature is creating its step.
  Two steps may both be features; the one-instance rule went with the thing there was one
  instance of.
- **Four lint checks ceased to exist.** `feature.unplaced`, `feature.duplicate`,
  `feature.dangling` and `feature.unregistered` each named a state the model can no longer
  be in. What survives is the passage checks — a quote that no longer anchors — which are
  about the *spec* moving, not about the plan being half-made.
- **A work step still reaches the spec through the feature it flows into.** No link on the
  step: its briefing lists the features `scope.gatherers` says own it, with the passages
  they were read from. A citation that was N:M on requirements is a walk on features, and
  it cannot go stale when `dplanner step link` rewires the graph with no window open.

The trace is therefore graph → feature step → spec passage, one hop shorter than it was.
The quote is still checked against the document — on `step add --feature`, on `feature
cite`, and on every lint — through the spec module's `anchor_quote`, handed across by the
composition root: the aspect belongs to one module and the document to another.

**The catalogue moves onto the steps at open, and that needs an `absorb`.** One module id
served both the project's catalogue and the step's marker, and a per-entry converter never
sees the project — so `planning/feature_migrate.py` is the format's `absorb` pass
(`modules/notes/migrate.py` is the other one). A placed record's passages go onto its step;
its description joins the step's prose, with a *Catalogued as "…"* line above it where the
two titles differed, so nothing a person wrote is dropped and nothing is invented; an
unplaced record becomes the step it always meant to be. Three things are worth knowing
before touching it: **a created step's data goes on the `Step` before `add_child` and its
id is never returned** (the builder flushes a returned id with the `module_data` and
`module_text` aspects only, and a step that did not exist a moment ago has no directory
recorded yet — the project's *structure* mark is what writes the subtree); **the shelf is
reached from here**, because `migrate_shelved` runs afterwards and would stamp a shelved
marker to format 3 with its record id still in it; and **it writes into a living module's
namespace** (`step_description`'s prose, opt-out and file area, named as a string constant
and never imported) — the alternative, a `description` inside the feature entry, would
re-create exactly the duplication this removes.

One pleasing consequence: the retired `step_feature` module wrote a bare `{"on": true}`,
and FORMAT.md used to call its converter "the one that cannot finish the job" because it
could not mint a record. With no catalogue left to be missing from, `{"on": true}` is now
a whole answer — a feature that cites nothing.

## A citation is a quote and a digest; its place is derived

A feature record says where in the spec it was read from, and the coverage view draws a
line from that passage to the feature. Two questions decided the shape: what to store,
and what happens when the spec changes underneath.

**A passage is stored as its quote, never as an offset.** The in-app editor flushes a new
blob on every pause in typing and `dplanner spec import` replaces a document with no
window running; an offset would be wrong within the hour, and a stored "found" would be
wrong the moment the file was replaced. So the quote is the anchor and `core/anchors.py`
finds it again on every read, exactly as the topological order is computed and not
written down. The match is exact first (case and whitespace aside, through an index map
that hands back raw offsets — what a viewer washes), then **fuzzy**: the quote's rarest
words seed windows the size of the quote, each end is tried a little either side, and the
best `SequenceMatcher` ratio wins if it reaches `DRIFT_RATIO`. That is the sentence
somebody reworded, offered back as the *drifted* candidate `feature reanchor
--accept-drift` takes. Nothing reaching the ratio is *lost*. The word-seeded search was
chosen over the longest-common-run seed it replaced because a heavily reworded sentence
keeps its nouns and little else.

**A passage carries the digest of the document it was read against**, the content-addressed
stem of the blob, so nothing new is hashed — `docs_compiled`'s digest for the same reason:
"did the spec move on since this was read" is a comparison, never a flag. But a
comparison alone would flag every citation in a document when somebody fixed a typo in
its last section. So *behind* is refined: the stamped blob is still on disk (blobs are
content-addressed and never pruned but for a session's own churn), and `diff_hunks`
between it and the current text says whether any change landed in the paragraph holding
the quote. Untouched is *anchored*; touched is *behind*; a stamp whose blob is gone is
*behind*, conservatively; no stamp — a passage migrated from format 1 — is judged by the
match alone, so an old project opens into no warnings. `feature reanchor` re-stamps what
still anchors, and lint names the three states with the verb that resolves each.

**Uncovered text is how new spec content surfaces, with no change tracking at all.**
`core/anchors.py::blocks` reads a document as paragraphs under their heading path; a
paragraph is covered when an anchored passage overlaps it. New text is simply uncovered
text, and `dplanner coverage spec <doc> --uncovered` is the agent's inbox after any
change — and the retrofit for a project that predates citations. It is a report, not a
lint, because it is perpetual by nature: a spec is never wholly claimed.

**The trace is one derived picture with two readers, and its path rule is feature
membership.** `modules/coverage/trace.py` arranges what four modules own — passages
(spec), records (feature), the gathering milestone and the tests in a cone (the graph and
testing), the compiled document's state (docs) — into four columns and links between
neighbours. `coverage/readers.py` reads each — through another module's `aspect.py` where
that is enough, else through a callable the composition root hands in — so the coverage
module reaches no other module's insides and the picture
cannot disagree with the verbs. Every item carries the features it serves: a passage the
features citing it, a feature itself, a milestone the features it gathers, a test the
feature whose cone holds its step (two features → both, honestly), a milestone's own docs
card all its features. What lights up on a pick is then one set intersection: a feature
lights exactly its chain, a milestone everything behind it, a passage two features cite
both — no case per kind. A milestone also carries a token of its own, so work it holds
directly belongs to it and to nothing else; that same token is what the lanes' drill-down
reads (below). The alternative — walking links upstream and
downstream — would have needed a rule per column pair to keep one feature's tests from
lighting another's, and it would have been wrong the first time a step sat in two cones.

**Lanes, each scrolling on its own, and links only in the gutters.** The tab is one
scene: a lane is a clipped column with its own offset and a thumb only while it
overflows, a link runs from one lane's edge to the next at the height of the cards it
joins, and a card scrolled out of view carries its end past the gutter's clip, so the
line is cut at the gutter rather than drawn over a caption. Cards paint with the
primitives the canvas paints with (`theme/cards.py`, moved there so two modules can share
them without importing each other), and every colour is read from the scene's palette at
paint time, so a theme switch costs nothing.

**The lanes are a drill-down, and the plan leads it.** They read *Milestones · Features ·
Spec · Tests & Docs*, and a lane stands only what the picks stand up: every milestone
always, the features the picked milestones gather (every feature while none is picked),
and — in the last two — what the picks *themselves* stand for. The first arrangement drew
the derivation's own order, spec first, with everything standing at once and everything
off the picked path faded to a fraction: a plan with a real specification opened as a wall
of passages and test cards, four fifths of it dimmed, and the question it answered ("what
became of this paragraph?") is the one a person asks *last*. A person opens this tab
holding a milestone or a feature in their head, which is why those two lead and why the
answers wait to be asked for. The rule that makes it one rule rather than four: an item
that can be picked carries its own `token` beside the features it serves, and a lane to
the right stands an item whose features meet the picked tokens. So a picked milestone
stands up the work it holds *directly* and never its features' whole spec — and a lane
with nothing in it says which pick would fill it, which is where the reader learns that
Ctrl-click adds another.

**The steps lane is asked for, and a lane that comes and goes reroutes the lines.** Between
the spec and its proof sits the work: the steps each pick holds, a feature's own step among
them, since that is where its tests and its document sit. *Show steps* on the strip stands
that lane there, so the picture reads requirement, work, proof from left to right. It is off
by default because the question the tab opens on is what became of the spec, and a lane of
every step behind every feature is the long way round to that answer. A line may only cross
the gutter between two lanes, so the trace records every pair that can stand side by side
— a document joins its features' tests directly *and* joins the steps they sit on, and each
step joins its tests — and the scene draws the pairs that are neighbours in the lanes
standing. That is the whole of the switch: no rule per arrangement, and nothing rebuilt but
the lines.

**A drill-down needs a selection, so a pick is a set.** A click picks within its own lane
and clears the lanes to its right; Ctrl (or Shift) adds to that lane, and picking a card
that lane already holds takes it back out; the ground and Escape clear. Picks the lanes
to their left no longer stand are dropped as the picks settle, so the feature you picked
under one milestone cannot survive picking another — and every picked card's step is
published, because picking three features is picking three steps and the Step verbs act
on all of them. Nothing is dimmed any more: a card that is not on the picture is not on
the picture. What lights is the *lines* into and out of a picked card, and the picture
carries fewer of them for it — the spec lane's document card is the hub on its right, so
a feature's tests hang off the document it was read from rather than off every passage
of it separately, which is the same claim drawn a dozen times.

**A view whose extent is laid out to its viewport must not report that extent as its size
hint.** `QGraphicsView.sizeHint()` *is* the scene rect mapped to the viewport, and this
scene's rect is laid to the viewport — so a splitter honouring the hint widens the view,
which widens the scene, which widens the hint: opening the tab pushed the index panel off
the left of the window and dragging the seam jumped. `CoverageView` returns a constant
instead. Two rules keep the rest of it still: the lane width is a whole number, so at any
width wider than the lanes at their narrowest the picture fits its viewport *exactly*
rather than by a rounding error that flickers the scroll bar on and off through a drag;
and a relayout for a viewport size the scene already has returns at once, because the
scroll bar coming and going resizes the viewport and would otherwise re-enter the layout.
When the lanes at their narrowest genuinely do not fit, the bar is honest and a pick
brings the lane it fills into view — a feature that filled a lane off the right of the
pane would look like a pick that did nothing.

## A note is a record with a label, and the briefing carries an index

A plan says what; what it does not say is everything a project learns as it goes — why it
went one way and not another, what a finished step's worker wants the next one to know,
where the work had to depart from the spec, what was noticed and put off. Two modules
used to hold two of those: a *decision log* beside the project, carried in full into every
briefing, and a *handoff* aspect on each step, inherited down the graph and carried in full
too. The first project to run forty agent steps showed what that costs: the briefing grew
with every step, an agent starting the thirtieth read twenty handoffs and a page of
decisions before its own instructions, and lost its focus in them — while the two record
kinds were the same thing wearing two shapes. Five decisions:

- **One log, and a closed list of labels.** A decision and a handoff are both *a note the
  project made along the way*; what differs is what the note *is*, and that is a word on
  the record — `decision`, `handoff`, `spec-change`, `later`, `post-project` — from a
  list this build owns (`log.LABELS`, a row each with its meaning and the index's heading
  over it — and nothing about who sees it, which is the graph's to say). Closed on purpose: an agent reading an index line must
  know what the line is without opening it, and a free tag vocabulary is what every agent
  invents differently. A new kind is a row, and `note add --help`, the skill and the
  index follow. The record is the decision log's shape kept — `N1, N2, …` minted per
  project and never reused, a title, markdown in the record, the day, the step it was made
  on, what it supersedes — with two fields the handoff needed: the steps it is *for*, and
  a *reach*. `modules/notes/` replaced both packages rather than sitting beside them,
  because two record kinds with one meaning is the entropy CLAUDE.md asks every pass to
  remove.
- **The briefing carries an index, and only what is addressed in full.** What the
  hundredth agent needs is to *find* what is relevant, not to read everything ever
  written. So a briefing's notes block is one line per standing note that reaches the
  step — id, title, when and where — grouped under the labels' headings, with the verb
  that opens one (`dplanner note show`); the bodies stay in the log. The exception is a
  note *addressed* to the step (`--for S12`, the editor's *For* field): that is one agent
  pointing the next at exactly what it must read, so it is printed in full, files and all,
  under *Notes for this step* ahead of the index. The block sits after the instructions,
  where the inherited context sat, because it is read once the work is understood. The
  title therefore carries the weight — the skill and the epilogue both say *title it as
  the fact it is* — and the agent that skims a line and does not open it has made a
  choice the old briefing never let it make.
- **Who sees a note is where it was made, with one stored exception.** Every label reaches
  the steps *after* the one it was made on — the cone the old handoff aspect walked, plus
  the step itself, since a re-run is a pick-up too. A note made on no step has nothing to be
  downstream of and reaches everyone whatever it wears; **so does one whose step is gone**,
  because a decision does not stop standing when the step that made it is deleted, and that
  is the same sentence generalised (`reaching()` is the only place that can know, so the
  live-id check lives there). `--reach project` lifts the one note that binds the whole plan
  and is stored only then (`FORMAT.md`'s absence rule). `reach.reaching()` is the one
  derivation.

  **This was settled twice, and the second time reversed the first.** Originally only a
  handoff used the graph: a decision, a spec change and a deferred item reached the whole
  project, on the argument that each is the project's and not a branch's. Then a 74-step
  plan with 320 standing notes was measured. The notes index was **73% of every briefing**
  — and 267 of its ~285 lines were *byte-identical on all 57 agent steps*, because four of
  the five labels bypassed the cone. An agent starting the fiftieth step read 171 decisions
  and 82 deferred items, almost none of them about its work, before reaching its own
  instructions. The argument was not wrong about what a decision *is*; it was wrong about
  what a briefing is *for*. The graph already answers "which earlier work does this step
  build on", and a project whose topology orders two steps that would touch the same file —
  which is the shape DPlanner's own plans declare — has already said that a decision binding
  you is a decision upstream of you. So the `reach` column came off `Label` entirely rather
  than keeping one value in five rows: a one-value column is an invitation for a future row
  to differ, and the point is that it cannot. Index 33,131 → 2,715 chars median, whole
  briefing 47,157 → 17,497.

  **Two pieces of prose had to follow, or the change would have quietly taken something
  away.** The briefing's epilogue tells an agent to record a `decision --step <key>`, which
  now reaches only the work after it — so the epilogue says what the reach is and when to
  add `--reach project`. And the index's own lead-in names `note list` as the whole log,
  because with reach narrowed *and* the index capped, an agent that suspects it is missing
  something needs a verb. A rule that removes what somebody could read owes them the way
  back to it.

  One thing deliberately left alone: `dplanner report` carries every standing note,
  uncapped. A publication is read by a person with a page and a scrollbar, not by an agent
  with a budget.
- **Adding twice is one note, and reversing is a new one — on the same step.** The
  decision log's retry safety kept, narrowed: a title already in the log *on the same
  step* is that note, reported with the verb that revises it and never duplicated. The
  narrowing is the handoff's doing — two agents each ending their step with a note titled
  *Done* must not have the second silently discarded. A reversal is a new record
  `--supersedes` the old; the history stays, `note list` shows what stands and `--all`
  what did, and a superseded note leaves every index.
- **The retired modules reach the log at open, one by takeover and one by absorption.**
  The decision log was already a record list on the project, so it is a `Takeover`
  (`D<n>` becomes `N<n>` wearing `decision`, supersedes links with it). A handoff was prose
  and files on a *step*, and a per-entry converter never sees the project the record
  belongs on — so `ModuleDataFormat` grew an `absorb` pass, run once per open over the
  whole repository with the loaded aggregate (`core/module_data.py`; `NOTES-FOR-APPFRAME.md`
  §21), and `migrate.absorb_handoffs` turns each step's handoff into a `handoff` note on
  that step, moves its files into the project's notes area with links written into the
  body, and clears the step. Idempotent, so a second open finds nothing. A handoff a
  person had turned *off* stays on the step's shelf under the retired id, untouched: that
  is what turning it off meant. The Handoff tab, its Type toggle and its place in the
  *Agent* template went with the aspect; the window's surfaces are the *Implementation
  notes* tab (the log as rows newest first beside the buttonless live editor with a
  label, a step, addressees, the reach box and the body, *Add Note…* opening on the
  title, Remove in the `⋯`) and the Agent tab's Notes pane, which renders the same
  blocks the briefing carries. The view lived in the project form as a card first, one
  widget per note; a plan whose agents had written 344 handoffs made every window
  relayout walk 688 word-wrapped labels, and the always-on panel was the wrong place for
  a log that grows with every run — see *The context is announced once per turn* below
  for the measurements. It was then a second reading inside the Docs tab behind a
  switch, which the index said nothing about; a tab of its own is what every other
  project surface is, and the row that opens it sits under the project in the Docs
  folder beside *Documentation*, because the notes are the project's other document. A
  tab page may carry a list of its own (DESIGN.md forbids one only inside a card, where
  the wheel would stop scrolling the stack), the rows are painted by the framework's
  two-line delegate, and the editor binds only the note that is picked. The notes module
  hands its row to the docs module through the root (`DocsDeps.more_rows`), the
  arrangement the order view and the estimation module's start-date bar already have;
  neither imports the other.
