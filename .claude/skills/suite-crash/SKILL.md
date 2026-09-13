---
name: suite-crash
description: Diagnose a crash in DPlanner's own test suite or a headless DPlanner script — a pytest-xdist worker dying with SIGSEGV, "Process crashed: python3.13" after a green run, a segfault inside the boundary gc.collect, ~QBoxLayout calling through a null vtable, a stack that dies in resizeEvent, or a crash that moves with the test count. Use it before debugging the test a crashed worker names.
---

# Diagnosing a crash in the suite

The episodes the suite has died of, how each was found, and what stops it now. The rules they
left behind are `CLAUDE.md`'s *Qt objects* list; this is the diagnosis, to read when one of them
has been broken anyway.

**A SIGSEGV is not always memory corruption: check the stack depth first.** The
2026-09-02 crash — every `time_estimates` test, deterministic, "in `resizeEvent`" — was a
**synchronous layout loop**: the calendar called `setFixedHeight` inside its own resize
event, inside a resizable scroll area, so the new height toggled the scrollbar, the
scrollbar changed the width, the width changed the height, and the process died 184,800
frames deep with `QScrollArea::eventFilter` on the stack 20,000 times. gdb's `bt | wc -l`
says so in one line, where faulthandler shows four Python frames and a symbol
(`_Pep_PrivateMangle`) that is only where the stack ran out. **A widget whose height
depends on its width implements `heightForWidth` and lets the layout ask; it never resizes
itself in `resizeEvent`.** `time_estimates/months.py` is the worked example, and its
regression test sweeps a scroll area across every width that could flip the scrollbar.
**Its `minimumSizeHint` is the least it can ever need — one row — never its `sizeHint`**:
a resizable scroll area sizes its page to the minimum, and a minimum computed at the
*minimum width* (every month in one column) made the Time tab scroll over empty space
in any window.

**A worker that segfaults after reporting green is dying at exit, not in a test.** The
2026-09-03 cores — two per full run, "Process crashed: python3.13" on the desktop, the
suite itself green — were libc `exit` running a Qt static destructor over a Python-made
`QMimeData` a copy test had handed the clipboard: under the *offscreen* platform Qt keeps
the clipboard's data in a global static that dies after the interpreter, and shiboken's
destroy hook then calls into a finalized Python. `coredumpctl info` shows it in one look:
`exit` at the bottom of the stack and no test frame anywhere. `tests/conftest.py`'s
`_collect_qt_garbage` clears the clipboard after every test for exactly this, and a
headless script that copies clears it before it returns (`scripts/measure_scaling.py`'s
`discard`, tested); a real platform owns its clipboard through the application and never
hits it.

**A pytest worker dying with SIGSEGV names an innocent test.** The suite has crashed this
way before (2026-09-01, roughly one run in three): the test reported is whichever one that
worker happened to be running, and the trigger moves with the total test count. That
episode rode on working-tree module code that was rewritten before it shipped — 21+ runs
across paddings and configurations have not reproduced it on the committed tree — but the
hazard is structural: ~520 tests hand their entire app build to the boundary collector as
one reference cycle, so a single widget-lifetime bug anywhere makes gc free a `QWidget`
whose C++ side is already gone. If it comes back, diagnose before debugging the named test:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q --dist loadfile   # green while --dist load is red
                                                             # = cross-test, not the named test
```

**To prove it is not your change**, replace your new test files with the same number of
`def test_x(): assert True` stubs and rerun; if it still crashes, only the test count
mattered. **To find the poisoning object without a crash**, run the crashing worker's tests
(`pytest -v` under `-n` says which worker ran what) single-threaded under
`scripts/gc_catalog.py`, a `gc.DEBUG_SAVEALL` plugin: nothing is freed, so the run cannot
crash, and it prints each test's Qt wrappers **in the order the collector would have cleared
them** — the order that decides which side of a wrapper dies first. Three shapes to
suspect: a `QLayoutItem` wrapper (below), a parentless `QObject` connected to its own
method, and a long-lived plain-Python signal holding a widget's bound method.

**A `QLayoutItem` wrapper is a double delete waiting for a gc pass.** The 2026-09-04
crash — `~QBoxLayout` calling through a null vtable, deterministic for one worker's four
tests, and moving with any allocation elsewhere in the build — was `layout.itemAt(i)` in a
view's read-back (`cards()`). PySide parents the returned wrapper to the layout's wrapper,
so it lives as long as the layout does; when a cycle holding both is collected, shiboken's
`tp_clear` hands every wrapper it clears **ownership back** (`removeParent(self)` in
`SbkObject_tp_clear`) before invalidating that wrapper's own children, so a `QWidgetItem`
or `QSpacerItem` cleared before its layout deletes an item the C++ layout still holds. A
`QObject` in the same position survives it — `~QObject` unregisters from its parent —
which is why only layout items bite. **Never read a layout back**: keep your own list of
what you put in it (`StatusColumn._held`, `MilestoneList._rows`) and read that; `takeAt`
in a loop that drops the wrapper each turn is fine. **And add a child layout to its parent
before filling it**: a parentless `QHBoxLayout()` given `addWidget` and `addStretch` first
leaves a `QWidgetItem` and a `QSpacerItem` wrapper alive on the Python side (none when
`addLayout` comes first), which is what the 2026-09-04 evening crash rode on — a worker
dying in the boundary collector on `test_asset_gallery.py`, whose bare `AssetGallery` had
exactly those two beside it in `gc_catalog`'s listing. A test that builds a top-level
widget of its own disposes it with `deleteLater` (the conftest dispatches it before
collecting), so the tree dies under Qt's rules and never inside the collector.
`NOTES-FOR-APPFRAME.md` §14 has the shiboken references.

**Why that crash moved with the test count, and what stops it now.** The collector clears
garbage in its list order, and a full collection walks generation 0 before generation 1:
a young collection landing between a layout's wrapper and its items' wrappers puts the
items ahead of the layout, and `gc.collect(0)` at that spot makes the double delete
deterministic — `scripts/layout_item_double_delete.py` (`plain` dies in `~QBoxLayout`,
`guard` survives, `order` prints the listing). `framework/gc_policy.py` closes it from the
framework side: every QObject wrapper gets a finalizer that invalidates its C++-created
children before any wrapper is cleared (PEP 442 runs all finalizers of a cycle first);
automatic collection is off and collections run from a GUI-thread timer at safe points,
never on a worker thread or inside an event handler; and the conftest installs both for
every test. The layout rules above stay as hygiene. **Never construct a `QLayoutItem` in
Python** (`addStretch`/`addSpacing` instead): that is the one shape the finalizer cannot
see. **A worker thread never holds the last reference to a Qt object**: shiboken deletes
a Python-owned QObject on whatever thread drops that reference, and `TaskRunner` hands
what its worker carried back to the GUI thread to be dropped on the next turn — any
hand-written thread-plus-signal goes through it. **The amplifier for this whole family:**
`MALLOC_PERTURB_=165 QT_QPA_PLATFORM=offscreen uv run pytest -q` (macOS:
`MallocScribble=1`) poisons freed memory so a use-after-free faults at the first bad
access instead of somewhere random; the committed `TaskRunner` before this pass died 3 of
3 under it in a 3000-round stress. `NOTES-FOR-APPFRAME.md` §15 has the sources and the
backtraces.
