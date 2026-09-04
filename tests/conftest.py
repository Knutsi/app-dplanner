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

import pytest

from dplanner.app import configure_application, new_session, set_early_attributes

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
def session(app, library_file):
    """A whole application, built over a fresh, empty library in a temp directory.

    Built through ``AppSession`` — the same path ``dplanner.app.main`` takes — so a test can
    never drift from production wiring. Yields the session; ``session.services`` reaches
    every part of the running application.

    ``close()`` at the end is not politeness: a build that is only closed stays alive and
    every later ``gc.collect()`` pays for it. Calling it twice is a no-op, so a test that
    closes early may still rely on this.
    """
    session = new_session()
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

    Left to its own schedule, Python's GC can free PySide wrappers mid Qt event dispatch in
    a later test — ``QObject::property`` on a half-destroyed object, a flaky SIGSEGV whose
    location shifts with any allocation change anywhere in the suite. Collecting between
    tests, while no Qt code is on the stack, keeps destruction deterministic.

    A collection costs what the live object graph costs, so this line is only cheap while
    every test actually releases what it built — which is ``AppSession.close``'s job, and
    why the ``session`` fixture calls it.

    The deferred deletes are dispatched first, for the same reason ``AppSession.close``
    dispatches its own: this fixture discards Qt objects with no event loop to follow, so
    it owes them (CLAUDE.md's rule). Without it, a widget a test ``deleteLater``'d — a
    gallery cell, a replaced tab page — stays a live C++ child until some *later* test's
    ``session.close()`` dispatches every pending delete globally, which is exactly the
    cross-test object lifetime this fixture exists to prevent.

    When a worker still dies with SIGSEGV in ``gc_collect -> subtype_dealloc -> ~QWidget``,
    the test it is reported against is only whichever one that worker was running —
    ``CLAUDE.md``'s *Checks* section has the diagnosis recipe. One such crash (2026-09-01,
    roughly one full run in three) turned out to ride on working-tree module code that was
    rewritten before it ever shipped; on the committed tree it has not reproduced since.
    """
    yield
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


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
def registry():
    """The whole CLI, with the topology gate switched off.

    A gate with no record file refuses nothing and writes nothing, so no test here needs
    a topology to add a step and none ever writes the per-user record. The gate itself is
    exercised over a real record under ``tmp_path`` in ``tests/cli/test_topology_gate.py``.
    """
    from dplanner.cli.command import CliRegistry
    from dplanner.cli.gate import TopologyGate
    from dplanner.modules import default_cli_commands
    from dplanner.modules.spec.aspect import read_topology

    registry = CliRegistry()
    registry.register_all(
        default_cli_commands(gate=TopologyGate(record_path=None, topology_of=read_topology))
    )
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

    if list(argv[:2]) not in (["project", "create"], ["project", "import"]) or "--dir" in argv:
        return list(argv)
    title = next((word for word in argv[2:] if not word.startswith("-")), "imported")
    return [*argv, "--dir", str(workspace / slugify(title, fallback="imported"))]


@pytest.fixture
def cli(registry, workspace, cli_library):
    from io import StringIO

    from dplanner.cli.main import run
    from dplanner.modules import default_module_formats

    def invoke(*argv, expect=0):
        out, err = StringIO(), StringIO()
        argv = _default_project_dir(argv, workspace)
        code = run(
            registry, default_module_formats(), ["--library", str(cli_library), *argv], out, err
        )
        assert code == expect, f"exit {code}: {err.getvalue()}{out.getvalue()}"
        return out.getvalue() + err.getvalue()

    return invoke


@pytest.fixture
def cli_stdin(registry, workspace, cli_library):
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
            )
        finally:
            sys.stdin = real
        assert code == expect, f"exit {code}: {err.getvalue()}{out.getvalue()}"
        return out.getvalue() + err.getvalue()

    return invoke
