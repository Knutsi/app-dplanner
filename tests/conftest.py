"""Shared test fixtures.

Two things here are order-sensitive and must stay at module level, above the imports they
look like they should sit below. Both are commented where they are.

The model here mirrors production: a per-test **library file** lists project directories,
each inside a git repository. ``session`` opens the library the way ``dplanner.app.main``
does; ``make_project`` gives GUI tests a *real* project (seeded on disk, attached to the
store) because a project with no directory cannot hold module files any more.
"""

import os

# Must precede any PySide6 import: the platform plugin is chosen when Qt's GUI layer loads.
# setdefault rather than a plain assignment so a developer can export QT_QPA_PLATFORM=xcb
# (or cocoa) to watch the tests drive a real window.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# A headless run takes no desktop theme either. A shell that presets QT_QPA_PLATFORMTHEME=gtk3
# (Omarchy does) has every worker initialise GTK — eight threads, a live connection to the
# compositor, DBus and dconf — and an offscreen window then becomes active one round of
# events later than a test that just gave a field focus expects, so a focus-dependent test
# passed one evening and failed every run the next morning. CLAUDE.md's *Checks* has the
# episode. The suite must not depend on the desktop's state.
if os.environ["QT_QPA_PLATFORM"] == "offscreen":
    os.environ["QT_QPA_PLATFORMTHEME"] = ""

# The same rule one layer up: the suite must not depend on the shell it was started from.
# Run Agent's wrapper exports DPLANNER_PROJECT (and a developer may export DPLANNER_LIBRARY)
# so that every `dplanner` call in that shell reaches the plan the window shows — and the
# CLI honours it, so in an agent's shell every test that builds a library under tmp_path
# failed with "no project matching <the agent's own project>". A test names the library and
# the project it means; nothing here may inherit either.
os.environ.pop("DPLANNER_PROJECT", None)
os.environ.pop("DPLANNER_LIBRARY", None)

import pytest

from dplanner.app import configure_application, new_session, set_early_attributes
from dplanner.theme import apply_theme
from dplanner.theme.themes import DEFAULT

# AA_DontUseNativeMenuBar is read at QMenuBar construction time and must be set before the
# QApplication exists. pytest-qt constructs it lazily inside the `qapp` fixture, so this has
# to run at import time rather than inside a fixture.
set_early_attributes()


@pytest.fixture(scope="session")
def app(qapp, tmp_path_factory):
    """The session ``QApplication``, with our configuration applied.

    pytest-qt owns construction — only one QApplication may exist per process, and it cannot
    be safely recreated once destroyed — so this fixture only configures the instance it
    provides.

    QSettings is redirected to a throwaway ini directory first: ``configure_application``
    reads the persisted theme, and the developer's real preference must not leak into the
    suite (nor test writes into the developer's settings).
    """
    from PySide6.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path_factory.mktemp("qsettings")),
    )
    configure_application(qapp)
    return qapp


@pytest.fixture
def themed(app):
    """A theme is applied application-wide, so put the default back for whatever runs next.

    A render test that samples colours applies its theme with ``apply_theme(themed, theme)``:
    a delegate paints from the palette, so setting a stylesheet on the widget alone is not
    enough.
    """
    yield app
    apply_theme(app, DEFAULT)


@pytest.fixture
def library_repo(tmp_path):
    """A git repository ready to hold this test's project directories."""
    from dplanner.core.storage.locations import init_repo

    return init_repo(tmp_path / "repo")


@pytest.fixture
def library_file(tmp_path):
    """An empty per-test library file — the source the session is built over."""
    from dplanner.domain.seed import create_library

    path = tmp_path / "library.json"
    create_library(path)
    return path


@pytest.fixture
def at_work_board(tmp_path):
    """Where an agent's *at work* claims land in a test: this test's own directory, never
    the user's (``domain/at_work.py``).

    One board for both surfaces of a test. The ``cli`` fixture hands it to the verbs *and*
    to the run, which is what ``entry.py`` does from inside an agent's shell — so a test
    invocation reads as an agent's, which is who the CLI is for; a run that is nobody's
    sign of life is ``run(board=None)``, tested where that distinction is the subject. The
    ``session`` fixture reads the same directory, so a claim one fixture writes is a banner
    the other shows.
    """
    from dplanner.domain.at_work import AtWorkBoard

    return AtWorkBoard(tmp_path / "at-work")


@pytest.fixture
def session(app, library_file, at_work_board):
    """A whole application, built over a fresh, empty library in a temp directory.

    Built through ``AppSession`` — the same path ``dplanner.app.main`` takes — so a test can
    never drift from production wiring. Yields the session; ``session.services`` reaches
    every part of the running application.

    ``close()`` at the end is not politeness: a build that is only closed stays alive and
    every later ``gc.collect()`` pays for it. Calling it twice is a no-op, so a test that
    closes early may still rely on this.
    """
    # The board is this test's own directory, never the user's: a window built here must
    # not read what some agent is really doing on this machine — and a test that writes a
    # claim through the ``cli`` fixture sees it in the window it built, because both
    # fixtures are handed the one board.
    session = new_session(at_work=at_work_board)
    assert session.open_initial(library_file)
    assert session.services is not None
    # Every coalesced view refresh runs inline: a test asserts on a view the line after it
    # pushes a command, which is the behaviour every view had before it was coalesced. The
    # deferred path is tested once, in tests/framework/test_debounce.py, and once per
    # converted view by switching this off.
    session.services.debounce.set_immediate(True)
    yield session

    session.close()


@pytest.fixture
def services(session):
    """Shorthand for the built application's services."""
    return session.services


@pytest.fixture
def make_project(services, library_repo):
    """A real project in the running application: on disk, attached, in the model.

    The in-memory shortcut (``AddNodeCommand`` straight onto the aggregate) is gone on
    purpose: a project now *is* a directory, and a store asked for a record-less project's
    files would refuse. Every project this creates lives in the test's one repository —
    several projects per repo is a supported layout, and the cheapest one to build.
    """
    from dplanner.core.fsio import slugify
    from dplanner.domain.seed import seed_project

    def make(title="Discovery"):
        store = services.repo
        directory = seed_project(library_repo / slugify(title, fallback="project"), title)
        project = store.attach(directory)
        services.document.add_child(services.document.id, project)
        return project

    return make


@pytest.fixture(autouse=True)
def _collect_qt_garbage():
    """Collect cyclic garbage at a safe point after each test.

    The application switches Python's automatic collector off and collects from a
    GUI-thread timer instead (framework/gc_policy.py has the crashes this avoids: a wrapper
    freed on a worker thread, or mid-dispatch on the GUI thread, deletes its C++ object
    there). The suite pumps events by hand, so that timer rarely gets to run here; cycles
    die in this fixture instead — after pytest-qt has closed and deleted the test's
    widgets, with no Qt code on the stack.

    A collection costs what the live object graph costs, so this line is only cheap while
    every test actually releases what it built — which is ``AppSession.close``'s job, and
    why the ``session`` fixture calls it.

    The deferred deletes are dispatched first, for the same reason ``AppSession.close``
    dispatches its own: this fixture discards Qt objects with no event loop to follow, so
    it owes them (`.claude/rules/runtime.md`). Without it, a widget a test ``deleteLater``'d — a
    gallery cell, a replaced tab page — stays a live C++ child until some *later* test's
    ``session.close()`` dispatches every pending delete globally, which is exactly the
    cross-test object lifetime this fixture exists to prevent.

    The clipboard is cleared here too, for the same reason. A ``QMimeData`` a test's copy
    handed to the clipboard is C++-owned with its Python wrapper kept alive, and under the
    offscreen platform Qt keeps it in a global static that libc destroys *after* the
    interpreter is gone — the worker then segfaulted at exit, after reporting green, on
    every run that drew a clipboard test (2026-09-03). Clearing while Python is alive
    deletes it under a live interpreter, and keeps one test's copy out of the next one's
    paste. A real platform owns its clipboard through the application and never hits this.

    When a worker still dies with SIGSEGV in ``gc_collect -> subtype_dealloc -> ~QWidget``,
    the test it is reported against is only whichever one that worker was running —
    the ``suite-crash`` skill has the diagnosis recipe. One such crash (2026-09-01,
    roughly one full run in three) turned out to ride on working-tree module code that was
    rewritten before it ever shipped; the next (2026-09-04, deterministic for one worker's
    four tests) was root-caused with ``scripts/gc_catalog.py``: a ``QLayoutItem`` wrapper
    cleared before its layout — the skill's *A `QLayoutItem` wrapper is a double delete
    waiting for a gc pass*. The policy that closes that one is installed below for every
    test that has an application, not only the ones built through the ``app`` fixture, so
    no test in a worker runs ahead of it.
    """
    from PySide6.QtCore import QCoreApplication

    application = QCoreApplication.instance()
    if application is not None:
        from dplanner.framework.gc_policy import install_gc_policy

        install_gc_policy(application)
    yield
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if QCoreApplication.instance() is not None:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().clear()
    gc.collect()


@pytest.fixture(autouse=True)
def _no_agent_shell(monkeypatch):
    """The suite must not depend on the shell it runs in.

    Run Agent's wrapper exports ``DPLANNER_PROJECT`` into an agent's shell so ``dplanner``
    reaches the plan from a worktree; an agent running this suite would hand every CLI
    test that project instead of the one the test built.
    """
    monkeypatch.delenv("DPLANNER_PROJECT", raising=False)


@pytest.fixture(autouse=True)
def _no_greeting(monkeypatch):
    """No test greets this machine.

    The checklist's start-up sweep probes the machine it runs on for real — a subprocess and,
    once the modal is open, a network request — so a suite that let it fire would be asking
    the developer's PATH what it should be asserting, and would open a modal over whatever
    build a test had just made. The surface itself is tested with fake probes in
    ``tests/modules/test_checklist_dialog.py``, which turns this off deliberately.
    """
    from dplanner.modules.checklist import module as checklist

    monkeypatch.setattr(checklist, "_greeted_this_process", True)


@pytest.fixture(autouse=True)
def _fresh_session_settings():
    """Per-user state must not leak between tests.

    The ``modules`` group holds per-module global preferences and ``libraries`` what each
    library's window remembered; the rest are the framework's.
    """
    yield
    from PySide6.QtCore import QSettings

    settings = QSettings()
    for group in ("appearance", "modules", "layout", "libraries", "window"):
        settings.beginGroup(group)
        settings.remove("")
        settings.endGroup()


# -- the headless CLI, over a real library -----------------------------------------------------
# Shared by tests/cli/ and by module tests exercising their verbs. These build no Qt
# objects; the CLI's no-Qt property itself is proven by test_architecture's subprocess
# probes, not by anything in this process.


@pytest.fixture
def registry(at_work_board):
    """The whole CLI, with both gates switched off.

    A read record with no file refuses nothing and writes nothing, so no test here needs a
    topology to add a step or a reading of the test format to write a test body, and none
    ever writes the per-user record. The gates themselves are exercised over a real record
    under ``tmp_path`` in ``tests/cli/test_topology_gate.py`` and ``test_test_format.py``.
    """
    from dplanner.cli.command import CliRegistry
    from dplanner.cli.gate import ReadRecord
    from dplanner.modules import default_cli_commands

    registry = CliRegistry()
    registry.register_all(default_cli_commands(reads=ReadRecord(None), board=at_work_board))
    return registry


@pytest.fixture
def workspace(tmp_path):
    """The CLI tests' git repository. Projects the tests create land directly inside it,
    so ``workspace / "discovery" / "steps" / …`` is where a created project's files are."""
    from dplanner.core.storage.locations import init_repo

    return init_repo(tmp_path / "widget")


@pytest.fixture
def cli_library(tmp_path):
    from dplanner.domain.seed import create_library

    path = tmp_path / "library.json"
    create_library(path)
    return path


def _default_project_dir(argv, workspace):
    """Test sugar: default the ``--dir`` a create/import verb requires.

    The GUI dialog supplies a directory; these fixtures supply the one the assertions
    expect — ``<workspace>/<slug(title)>`` — so fifty call sites do not each spell it.
    An explicit ``--dir`` in the call always wins.
    """
    from dplanner.core.fsio import slugify

    creating = list(argv[:2]) in (["project", "create"], ["project", "import"])
    if not creating or "--dir" in argv or "--in" in argv:
        return list(argv)
    title = next((word for word in argv[2:] if not word.startswith("-")), "imported")
    return [*argv, "--dir", str(workspace / slugify(title, fallback="imported"))]


@pytest.fixture
def clock():
    """The day the ``cli`` fixtures' runs date things by — the machine's until a test pins
    it (``core/clock.py``). A window's is ``services.clock``."""
    from dplanner.core.clock import Clock

    return Clock()


@pytest.fixture
def cli(registry, workspace, cli_library, at_work_board, clock):
    from io import StringIO

    from dplanner.cli.main import run
    from dplanner.modules import default_module_formats

    def invoke(*argv, expect=0):
        out, err = StringIO(), StringIO()
        argv = _default_project_dir(argv, workspace)
        code = run(
            registry,
            default_module_formats(),
            ["--library", str(cli_library), *argv],
            out,
            err,
            board=at_work_board,
            clock=clock,
        )
        assert code == expect, f"exit {code}: {err.getvalue()}{out.getvalue()}"
        return out.getvalue() + err.getvalue()

    return invoke


@pytest.fixture
def cli_stdin(registry, workspace, cli_library, at_work_board, clock):
    import sys
    from io import StringIO

    from dplanner.cli.main import run
    from dplanner.modules import default_module_formats

    def invoke(*argv, expect=0, stdin=""):
        out, err = StringIO(), StringIO()
        argv = _default_project_dir(argv, workspace)
        real = sys.stdin
        sys.stdin = StringIO(stdin)
        try:
            code = run(
                registry,
                default_module_formats(),
                ["--library", str(cli_library), *argv],
                out,
                err,
                board=at_work_board,
                clock=clock,
            )
        finally:
            sys.stdin = real
        assert code == expect, f"exit {code}: {err.getvalue()}{out.getvalue()}"
        return out.getvalue() + err.getvalue()

    return invoke


@pytest.fixture
def step_editor(services, monkeypatch):
    """A step's editor, as the application offers it: ``steps.details``, briefly modal.

    There is no anchored step panel to reach for — the editor has one seat and it is this
    dialog (``ARCHITECTURE.md``'s *The step editor is a modal*) — so a test that drives an
    aspect editor opens it the way a double-click does and reads ``.panel``. It is opened on
    a **constructed** context naming one step, which is the documented way to run a verb on
    something nobody selected, and leaves the window's own selection alone for the tests
    that assert on it.

    Two things are held off. ``exec`` blocks, so it is stood in for by ``show`` — which is
    what it does minus the loop, and a dialog that was never shown has no window for a field
    to take focus in, which is the difference between an editor that ignores the echo of its
    own write and one that cannot. And ``dispose`` runs the moment ``exec`` returns, which is
    right in production and useless in a test that wants to type in the editor and watch the
    model reach it. This fixture disposes what it opened instead.
    """
    from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    dispose = StepDetailsDialog.dispose
    opened = []

    def shown(dialog):
        dialog.show()
        opened.append(dialog)

    monkeypatch.setattr(StepDetailsDialog, "exec", shown)
    monkeypatch.setattr(StepDetailsDialog, "dispose", lambda self: None)

    def open_on(step_id):
        """The panel of a dialog opened on ``step_id``."""
        nodes = (ContextNode(selection_uri("step", step_id)),)
        services.actions.run("steps.details", Context({SCOPE_SELECTION: nodes}))
        return opened[-1].panel

    yield open_on
    for dialog in opened:
        dispose(dialog)
        dialog.close()
        dialog.deleteLater()


@pytest.fixture(autouse=True)
def _no_swallowed_slot_errors(request):
    """A listener that raises is logged and skipped by ``Signal.emit`` — right for the
    running application, where a broken view must not abort the model change that woke it,
    and wrong for a test, where the swallowed traceback is exactly the failure being looked
    for. So every test fails on one, unless it says it means to raise in a slot
    (``@pytest.mark.raises_in_a_slot``)."""
    import logging

    class Collect(logging.Handler):
        def __init__(self) -> None:
            super().__init__(level=logging.ERROR)
            self.failures: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            # Formatted now, not at teardown: the record names the slot by repr, and a
            # bound method of a widget the teardown has since deleted cannot be repr'd.
            if record.name == "dplanner.core.signals":
                self.failures.append(self.format(record))

    collector = Collect()
    logging.getLogger().addHandler(collector)
    try:
        yield
    finally:
        logging.getLogger().removeHandler(collector)
    if collector.failures and request.node.get_closest_marker("raises_in_a_slot") is None:
        pytest.fail(
            "a signal slot raised and Signal.emit swallowed it:\n" + "\n".join(collector.failures)
        )
