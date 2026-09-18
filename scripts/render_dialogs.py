"""Render every dialog the dialogs pass put on the frame, in the dark and the light theme.

    uv run python scripts/render_dialogs.py --out docs/screenshots/s16-dialogs

S16 brought the dialog-shaped surfaces onto ``DialogFrame``: the Settings dialog and its
pages, the Project dialog in both modes and the dialogs around it, Install DPlanner, the
run fallback and the Run Anyway question, the asset picker, the image preview, the diff,
Connect, the conflict question, and the chart and text windows. What each shows is
invented rather than probed — a screenshot of the developer's own machine would show
whatever it happens to have — and the dialogs a module builds over services are built
over a whole application on a throwaway library, torn down per theme. ``HOME`` and
``QSettings`` point into a temporary directory, so no path or preference of this machine
reaches an image and nothing of this machine is written.
"""

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

from PySide6.QtCore import QBuffer, QCoreApplication, QEvent, QSettings, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit, QWidget

from dplanner.app import new_session
from dplanner.cli.install import COMMAND, LAUNCHER, SKILL, Item, Outcome
from dplanner.core.storage.locations import init_repo
from dplanner.core.storage.sparse import Probe
from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.locations import CODE, Location, roles_by_id
from dplanner.domain.project_link import ProjectLink, encode
from dplanner.domain.relocate import Moved
from dplanner.domain.repositories import repository_facts
from dplanner.domain.seed import create_library, seed_project
from dplanner.framework.asset_picker import DIALOG_SIZE as PICKER_SIZE
from dplanner.framework.asset_picker import AssetPickerDialog, PickerEntry
from dplanner.framework.image_preview import ImagePreviewDialog
from dplanner.framework.tasks import TaskService
from dplanner.framework.text_dialog import ExpandedTextDialog
from dplanner.framework.user_config import set_global
from dplanner.modules import default_location_roles, managed_for
from dplanner.modules.install import dialog as install_dialog
from dplanner.modules.library_watch.view import ConflictDialog
from dplanner.modules.projects.checkouts import CheckoutService
from dplanner.modules.projects.location_dialog import LocationDialog
from dplanner.modules.projects.move_dialog import MovePlanDialog
from dplanner.modules.projects.open_dialog import (
    BROWSE_PAGE,
    LINK_PAGE,
    OpenProjectDialog,
)
from dplanner.modules.projects.open_dialog import DIALOG_SIZE as OPEN_SIZE
from dplanner.modules.projects.project_dialog import (
    CREATE,
    CREATE_SIZE,
    SETTINGS_SIZE,
    ProjectDialog,
)
from dplanner.modules.projects.repo_picker import GH_LIST_SIZE, GhRepoListDialog
from dplanner.modules.projects.repos import LogEntry, PullRequest, RepoLog, RepositoryServices
from dplanner.modules.projects.repositories_folder import RepositoriesFolderDialog
from dplanner.modules.projects.share_dialog import ShareProjectDialog
from dplanner.modules.settings.dialog import DIALOG_SIZE as SETTINGS_DIALOG_SIZE
from dplanner.modules.settings.module import SettingsModule
from dplanner.modules.spec_confluence import module as confluence_module
from dplanner.modules.spec_confluence.connect import ConnectDialog
from dplanner.modules.step_agent_instruction.run_dialog import DIALOG_SIZE as PROMPT_SIZE
from dplanner.modules.step_agent_instruction.run_dialog import (
    PromptFallbackDialog,
    RunAnywayDialog,
)
from dplanner.modules.sync.view import DIFF_DIALOG_SIZE, DiffDialog
from dplanner.modules.time_estimates.chart import ChartData, ChartDialog, Segment
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

FIT_WIDTH = 520  # A fit dialog at the width a person's first sentence would give it.
CHART_SIZE = (1000, 720)
EDITOR_SIZE = (900, 600)
CODE_URL = "https://github.com/acme/widget"
PLANS_URL = "https://github.com/acme/plans"
WAIT_S = 10.0

PROMPT = """# Step: Build the quick-reg modal

Project: Discovery

## Before you start

Confirm you are in this step's own git worktree: `git rev-parse --show-toplevel` must end
in `.dplanner-worktrees/s3-build-the-quick-reg-modal`.

## Instructions

The modal asks for the e-mail address and the one-time code, and nothing else. Remember
this computer is off by default.

## When you are done

- `dplanner status set S3 done`
- `dplanner note add Discovery handoff '<one line>' --step S3 --file -`
"""

DIFF_PLANS = """diff --git a/discovery/project.dproj b/discovery/project.dproj
index 3f1a2b4..9c0d7e1 100644
--- a/discovery/project.dproj
+++ b/discovery/project.dproj
@@ -1,6 +1,6 @@
 {
   "format": 2,
-  "title": "Discovery",
+  "title": "Discovery — quick registration",
   "last_number": 7,
   "repository": "https://github.com/acme/widget"
 }
diff --git a/discovery/steps/9f/step.json b/discovery/steps/9f/step.json
index 1b2c3d4..5e6f7a8 100644
--- a/discovery/steps/9f/step.json
+++ b/discovery/steps/9f/step.json
@@ -1,5 +1,5 @@
 {
   "number": 3,
-  "title": "Build the modal",
+  "title": "Build the quick-reg modal",
   "created": "2026-09-01"
 }
"""

DIFF_SATELLITE = """diff --git a/satellite/steps/77aa/step.json b/satellite/steps/77aa/step.json
--- a/satellite/steps/77aa/step.json
+++ b/satellite/steps/77aa/step.json
@@ -1,3 +1,3 @@
-  "title": "Sketch the orbit",
+  "title": "Sketch the orbit and the ground track",
"""


# -- the render loop's helpers -----------------------------------------------------------------


def settle(app: QApplication) -> None:
    for _ in range(3):
        app.processEvents()


def save(widget: QWidget, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    settle(app)
    path = out / f"{name}-{theme.name}.png"
    widget.grab().save(str(path), "PNG")
    print(path)


def discard(widget: QWidget) -> None:
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def framed(dialog: QDialog, size: tuple[int, int], app: QApplication) -> None:
    """Shown at the size it opens at on a real screen: the offscreen screen is smaller than
    a desktop's, and a framed dialog is clamped to a share of it."""
    dialog.show()
    dialog.resize(*size)
    settle(app)


def fitted(dialog: QDialog, app: QApplication, width: int = FIT_WIDTH) -> None:
    """A fit dialog at a sentence's width — or its own, when its footer needs more — and
    as tall as its wrapped words need."""
    dialog.show()
    settle(app)
    width = max(width, dialog.sizeHint().width())
    layout = dialog.layout()
    height = (
        layout.totalHeightForWidth(width)
        if layout is not None and layout.hasHeightForWidth()
        else dialog.sizeHint().height()
    )
    dialog.resize(width, height)
    settle(app)


def wait_until(app: QApplication, done: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_S
    while not done() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def inline(*runners: object) -> None:
    """A task body run on the spot: what a worker would deliver lands at once."""

    def run_now(_label: str, body: Callable[[], None], **_kwargs: object) -> bool:
        body()
        return True

    for runner in runners:
        runner.run = run_now  # type: ignore[attr-defined]


def picture(color: str, words: str, width: int = 320, height: int = 200) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    painter = QPainter(image)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, words)
    painter.end()
    return image


def png(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def commit_all(root: Path, author: str) -> None:
    git = ["git", "-C", str(root)]
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run(
        [
            *git,
            "-c",
            f"user.name={author}",
            "-c",
            "user.email=a@example.com",
            "commit",
            "-qm",
            "plans",
        ],
        check=True,
    )


# -- the dialogs that need no application ------------------------------------------------------


def machine(*, done: bool) -> Callable[[dict[str, str]], list[Item]]:
    """One machine's worth of rows: the command there, the launcher missing, the skill
    from another build — or, once the install has run, all three in place."""
    home = Path.home()
    launcher = home / ".local/share/applications/dplanner.desktop"
    skill = home / ".claude/skills/dplanner"
    rows = [
        Item(
            COMMAND,
            "dplanner command",
            "installed",
            home / ".local/bin/dplanner",
            "Resolves at ~/.local/bin/dplanner",
        ),
        Item(
            LAUNCHER,
            "Desktop launcher",
            "installed" if done else "missing",
            launcher,
            "Opens DPlanner from the applications menu"
            if done
            else "DPlanner is not in this desktop's applications menu",
        ),
        Item(
            SKILL,
            "Agent skill",
            "installed" if done else "stale",
            skill,
            "Generated from this build's commands"
            if done
            else "Installed from another build — updating rewrites it from this one",
        ),
    ]
    return lambda _files: rows


def render_bare(app: QApplication, theme: Theme, out: Path) -> None:
    tasks = TaskService()

    install_dialog.items = machine(done=False)  # type: ignore[assignment]
    install_dialog.worktree_warning = lambda: None  # type: ignore[assignment]
    install = install_dialog.InstallDialog(tasks, {}, None)
    framed(install, install_dialog.DIALOG_SIZE, app)
    save(install, out, "install", theme, app)
    install_dialog.items = machine(done=True)  # type: ignore[assignment]
    install._finished(
        [
            Outcome(COMMAND, True, "dplanner command: up to date at ~/.local/bin/dplanner"),
            Outcome(LAUNCHER, True, "Desktop launcher: written"),
            Outcome(SKILL, True, "Agent skill: rewritten from this build"),
        ]
    )
    save(install, out, "install-done", theme, app)
    discard(install)

    fallback = PromptFallbackDialog(PROMPT, "/tmp/dplanner-agent-3kq9/prompt.md", None)
    framed(fallback, PROMPT_SIZE, app)
    save(fallback, out, "prompt-fallback", theme, app)
    fallback.copy_button.click()
    save(fallback, out, "prompt-copied", theme, app)
    QGuiApplication.clipboard().clear()  # Offscreen, the clipboard outlives the interpreter.
    discard(fallback)

    one = RunAnywayDialog(
        1,
        "“Build the quick-reg modal” waits on 1 step not done yet.",
        [("", ["• Design the modal — in progress"])],
        "The agent would start without what those steps produce. Run it anyway?",
        None,
    )
    fitted(one, app)
    save(one, out, "run-anyway", theme, app)
    discard(one)
    many = RunAnywayDialog(
        3,
        "2 of the chosen steps wait on work not done yet.",
        [
            ("Build the quick-reg modal waits on", ["• Design the modal — in progress"]),
            (
                "Wire the code field waits on",
                ["• Pick the SMS provider — pending", "• Write the code rules — blocked"],
            ),
        ],
        "The agents would start without what those steps produce. Run them anyway?",
        None,
    )
    fitted(many, app)
    save(many, out, "run-anyway-many", theme, app)
    discard(many)

    shots = [("#4c6ef5", "the sign-in flow"), ("#2a9d8f", "the modal"), ("#8e6fd8", "error states")]
    entries = [
        PickerEntry(
            key=f"assets/{index}.png",
            title=words,
            filename=f"{words}.png",
            detail="Descriptions · used by S3",
            read=lambda c=color, w=words: png(picture(c, w)),
        )
        for index, (color, words) in enumerate(shots)
    ]
    entries.append(
        PickerEntry(
            key="assets/rules.txt",
            title="code rules.txt",
            filename="code rules.txt",
            read=lambda: b"six digits",
        )
    )
    picker = AssetPickerDialog(entries)
    framed(picker, PICKER_SIZE, app)
    for row in (0, 2):
        item = picker.grid.item(row)
        if item is not None:
            item.setSelected(True)
    save(picker, out, "asset-picker", theme, app)
    discard(picker)
    empty = AssetPickerDialog([])
    framed(empty, PICKER_SIZE, app)
    save(empty, out, "asset-picker-empty", theme, app)
    discard(empty)

    preview = ImagePreviewDialog(
        picture("#4c6ef5", "the sign-in flow", 640, 360),
        "flow.png",
        path="/nowhere/assets/flow.png",
    )
    preview.show()
    settle(app)
    preview.adjustSize()
    save(preview, out, "image-preview", theme, app)
    preview._open_externally("/nowhere/assets/flow.png")
    save(preview, out, "image-preview-missing", theme, app)
    discard(preview)

    diff = DiffDialog(None)
    diff.set_sources(
        [
            ("plans (~/Code/plans)", lambda: DIFF_PLANS),
            ("satellite (~/Code/satellite)", lambda: DIFF_SATELLITE),
        ]
    )
    framed(diff, DIFF_DIALOG_SIZE, app)
    save(diff, out, "diff", theme, app)
    discard(diff)

    connect = ConnectDialog(
        None,
        "acme.atlassian.net",
        tasks=tasks,
        probe=lambda _c: "Auth Overview",
        open_url=lambda _u: None,
        backend_problem=None,
        email="anna@acme.example",
    )
    connect.token.setText("ATATT3xFfGF0-token")
    fitted(connect, app)
    save(connect, out, "connect", theme, app)
    discard(connect)
    refused = ConnectDialog(
        None,
        "acme.atlassian.net",
        tasks=tasks,
        probe=lambda _c: "",
        open_url=lambda _u: None,
        backend_problem="no keychain service is running",
    )
    fitted(refused, app)
    save(refused, out, "connect-refused", theme, app)
    discard(refused)

    rows = ["S3 · Build the quick-reg modal · description", "Discovery · title and summary"]
    conflict = ConflictDialog(rows, "", None)
    fitted(conflict, app, 560)
    save(conflict, out, "conflict", theme, app)
    discard(conflict)
    conflict_refused = ConflictDialog(rows, "no launch profile can run on this machine", None)
    fitted(conflict_refused, app, 560)
    save(conflict_refused, out, "conflict-refused", theme, app)
    discard(conflict_refused)

    violet, teal, blue = QColor("#8e6fd8"), QColor("#2a9d8f"), QColor("#4a7fd6")
    start, today, end = date(2026, 8, 3), date(2026, 9, 13), date(2026, 10, 16)
    data = ChartData(
        today,
        expected=((start, 0.0), (date(2026, 9, 1), 0.38), (date(2026, 9, 18), 0.62), (end, 1.0)),
        actual=((start, 0.0), (date(2026, 8, 20), 0.2), (today, 0.46)),
        baseline=((start, 0.0), (date(2026, 9, 10), 0.55), (date(2026, 10, 2), 1.0)),
        basis="the plan at start, recorded 3 Aug",
        segments=(
            Segment(
                "M1",
                "Improvements #1",
                violet,
                now=(start, date(2026, 9, 18)),
                then=(start, date(2026, 9, 10)),
            ),
            Segment(
                "M2",
                "Improvements #2",
                teal,
                now=(date(2026, 9, 21), end),
                then=(date(2026, 9, 11), date(2026, 10, 2)),
            ),
            Segment("", "Remaining work", blue),
        ),
        volume=((start, 40.0), (date(2026, 9, 1), 52.0), (today, 58.0)),
        remaining=((start, 40.0), (date(2026, 9, 1), 33.0), (today, 31.0)),
    )
    chart = ChartDialog(data, title="Discovery — Progress")
    framed(chart, CHART_SIZE, app)
    save(chart, out, "chart", theme, app)
    discard(chart)


# -- the dialogs a module builds over the application's services -------------------------------


def fake_repositories(services, plans: Path) -> RepositoryServices:  # type: ignore[no-untyped-def]
    """The projects module's seam, over the real store's facts and invented git and gh."""
    store, library = services.repo, services.document
    roles = roles_by_id(default_location_roles())
    managed = managed_for(roles)
    now = datetime.now(UTC)
    log = RepoLog(
        branch="main",
        entries=(
            LogEntry("a1", "Add the login form", "Anna", (now - timedelta(hours=2)).isoformat()),
            LogEntry("b2", "Wire the code field", "Bo", (now - timedelta(days=1)).isoformat()),
            LogEntry(
                "c3", "Start the quick-reg modal", "Anna", (now - timedelta(days=3)).isoformat()
            ),
        ),
    )
    pr = PullRequest(
        7, "Build the quick-reg modal", "agent/s3-build-the-quick-reg-modal", f"{CODE_URL}/pull/7"
    )
    return RepositoryServices(
        facts_of=lambda pid: repository_facts(
            library.project(pid), store.project_dir(pid), store.checkouts(), managed=managed
        ),
        roles=roles,
        project_dir=store.project_dir,
        checkout_for=store.checkout_for,
        set_checkout=store.set_checkout,
        checkout_changed=store.checkout_changed,
        plan_roots=lambda: [plans],
        pr_steps=lambda _pid: {7: "S3 Build the quick-reg modal"},
        history_for=lambda _root, _scope, _limit: log,
        gh_refusal=lambda: None,
        list_repositories=lambda: ["acme/widget", "acme/plans", "acme/website", "anna/dotfiles"],
        clone=lambda _url, dest: dest.mkdir(parents=True),
        clone_url=lambda _url, dest: dest.mkdir(parents=True),
        publish=lambda _root, name: f"https://github.com/acme/{name}",
        create_repository=lambda name, _dest: f"https://github.com/acme/{name}",
        open_prs=lambda _remote: [pr],
        list_folders=lambda _url, ref: Probe(ref, ()),
        move_project=lambda *_args: Moved(Path(), Path(), False, False, ()),
    )


def render_session(app: QApplication, theme: Theme, out: Path, home: Path) -> None:
    workspace = home / "company-plans"
    library_file = home / "library.json"
    create_library(library_file)
    init_repo(workspace)
    session = new_session()
    assert session.open_initial(library_file)
    services = session.services
    assert services is not None
    services.debounce.set_immediate(True)

    # A plan repository with two projects two people worked on, and a code checkout.
    plans = init_repo(home / "Code" / "plans")
    seed_project(plans / "search", "Search")
    commit_all(plans, "Anna")
    seed_project(plans / "billing", "Billing")
    commit_all(plans, "Bo")
    code = init_repo(home / "Code" / "widget")

    discovery = services.repo.attach(seed_project(workspace / "discovery", "Discovery"))
    services.document.add_child(services.document.id, discovery)
    services.undo.push(
        SetFieldCommand(
            discovery.id,
            "locations",
            (
                Location("l1", CODE.id, CODE_URL),
                Location("l2", "spec", "https://github.com/acme/specs", path="products/search"),
                Location("l3", "reporting", CODE_URL, path="reports/search"),
            ),
        )
    )
    services.repo.set_checkout(CODE_URL, code)
    satellite = services.repo.attach(seed_project(workspace / "satellite", "Satellite"))
    services.document.add_child(services.document.id, satellite)
    settle(app)
    repos = fake_repositories(services, plans)
    checkouts = CheckoutService(
        repos, services.tasks, kept_root=home / "config", parent=services.window
    )

    # -- Settings, on the pages this pass changed most -----------------------------------------
    set_global(
        confluence_module.MODULE_ID,
        confluence_module.SITES_KEY,
        {"acme.atlassian.net": "anna@acme.example", "globex.atlassian.net": "anna@globex.example"},
    )
    settings = next(m for m in services.modules if isinstance(m, SettingsModule)).dialog
    framed(settings, SETTINGS_DIALOG_SIZE, app)
    for section, name in (
        ("step_agent_instruction.launch", "settings-agent-profiles"),
        ("appearance.providers", "settings-appearance"),
        ("llm.openai", "settings-openai"),
        ("spec_confluence", "settings-confluence"),
    ):
        settings.show_section(section)
        save(settings, out, name, theme, app)
    settings.hide()

    # -- the Project dialog, apart from its code and still inside it ---------------------------
    project = ProjectDialog(
        services.document,
        services.undo,
        repos,
        services.tasks,
        services.theme,
        checkouts=checkouts,
        move=lambda _pid: None,
        parent=services.window,
    )
    inline(project._reader, project._worker)
    project.show_project(discovery.id)
    framed(project, SETTINGS_SIZE, app)
    save(project, out, "project-settings", theme, app)
    project.show_project(satellite.id)
    save(project, out, "project-colocated", theme, app)
    discard(project)

    creating = ProjectDialog(
        services.document,
        services.undo,
        repos,
        services.tasks,
        services.theme,
        checkouts=checkouts,
        move=lambda _pid: None,
        mode=CREATE,
        parent=services.window,
    )
    (plans / "alpha-search").mkdir()
    creating.name_edit.setText("Alpha Search")
    framed(creating, CREATE_SIZE, app)
    save(creating, out, "project-create", theme, app)
    discard(creating)

    # -- one location, asked for: the repositories gh knows listed, a position to browse ------
    adding = LocationDialog(
        repos.roles["spec"],
        location_id="l4",
        repositories=[CODE_URL, PLANS_URL],
        location=None,
        checkout_for=lambda _url: None,
        record_checkout=lambda _repository, _root: None,
        services=repos,
        tasks=services.tasks,
        theme=services.theme,
        parent=services.window,
    )
    inline(adding._runner)
    adding.repository.setEditText("https://github.com/acme/specs")
    adding.position.setText("products/search")
    fitted(adding, app, 560)
    save(adding, out, "location-add", theme, app)
    discard(adding)

    opening = OpenProjectDialog(
        replace(repos, plan_roots=lambda: []),
        services.tasks,
        services.theme,
        listed_dirs=[],
        listed_ids=[],
        parent=services.window,
    )
    inline(opening.browse._runner, opening.link._runner)
    framed(opening, OPEN_SIZE, app)
    save(opening, out, "open-project-ways", theme, app)
    opening.show_page(LINK_PAGE)
    opening.link.set_text(
        encode(
            ProjectLink(
                plan_remote=PLANS_URL,
                plan_path="search",
                title="Search",
                summary="Replace the index",
                code_remote=CODE_URL,
            )
        )
    )
    settle(app)
    save(opening, out, "open-project-link", theme, app)
    opening.show_page(BROWSE_PAGE)
    opening.browse.picker.set_current(plans)
    save(opening, out, "open-project-browse", theme, app)
    discard(opening)

    sharing = ShareProjectDialog(
        ProjectLink(
            plan_remote=PLANS_URL,
            plan_path="search",
            title="Search",
            summary="Replace the index",
            code_remote=CODE_URL,
        ),
        services.window,
    )
    fitted(sharing, app, 560)
    save(sharing, out, "share-project", theme, app)
    discard(sharing)

    moving = MovePlanDialog(
        title="Discovery",
        folder_name="discovery",
        facts=repos.facts_of(discovery.id),
        services=repos,
        tasks=services.tasks,
        theme=services.theme,
        parent=services.window,
    )
    fitted(moving, app, 600)
    save(moving, out, "move-plan", theme, app)
    discard(moving)

    folders = RepositoriesFolderDialog([home / "Code", home / "src"], None)
    fitted(folders, app)
    save(folders, out, "repositories-folder", theme, app)
    discard(folders)

    listing = GhRepoListDialog(repos, services.tasks, services.window)
    wait_until(app, lambda: listing.list.count() > 0)
    framed(listing, GH_LIST_SIZE, app)
    save(listing, out, "gh-repo-list", theme, app)
    discard(listing)

    source = QPlainTextEdit()
    source.setPlainText(PROMPT)
    expanded = ExpandedTextDialog.over_document(
        source.document(), services.undo, title="Description — S3"
    )
    framed(expanded, EDITOR_SIZE, app)
    save(expanded, out, "expanded-text", theme, app)
    expanded.dispose()
    discard(expanded)
    discard(source)

    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/s16-dialogs"))
    args = parser.parse_args(argv)
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    with TemporaryDirectory(prefix="dplanner-render-") as tmp:
        # No path and no preference of this machine reaches an image, and nothing of this
        # machine is written: the home the dialogs shorten paths against, and QSettings.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tmp)
        for theme in (DARK, LIGHT):
            home = Path(tmp) / theme.name
            home.mkdir()
            os.environ["HOME"] = str(home)
            QSettings().clear()
            apply_theme(app, theme)
            render_bare(app, theme, args.out)
            render_session(app, theme, args.out, home)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
