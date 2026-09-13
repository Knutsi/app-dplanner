"""The Add Git Repository dialog: the refusal ladder, the listing that runs off the GUI
thread, and what the person's pick becomes. The engine behind it is covered in
``test_spec_git_source.py``."""

import pytest
from tests.modules.spec_git_helpers import clean_git, make_remote, wait_for  # noqa: F401

from dplanner.domain.document_source import SourceUnavailableError
from dplanner.modules.spec_git import source
from dplanner.modules.spec_git.connect import GitSourceDialog
from dplanner.modules.spec_git.module import NO_GIT, SpecGitDeps, SpecGitKind
from dplanner.modules.spec_git.source import Folder, Probe

TREE = {"README.md": "# Handbook\n", "docs/spec/auth.md": "# Auth\n"}

FOUND = Probe(
    ref="main",
    folders=(
        Folder(path="", files=2, documents=2),
        Folder(path="docs", files=1, documents=1),
        Folder(path="docs/spec", files=1, documents=1),
    ),
)


@pytest.fixture
def probes():
    return []


@pytest.fixture
def dialog(services, probes):
    def probe(url, ref):
        probes.append((url, ref))
        return FOUND

    made = GitSourceDialog(services.window, tasks=services.tasks, probe=probe)
    yield made
    made.deleteLater()


def _text(made, row):
    item = made.table.item(row, 0)
    return "" if item is None else item.text()


def refused(made):
    primary = made.primary()
    return primary is not None and not primary.isEnabled()


# -- the ladder ----------------------------------------------------------------------------------


def test_the_primary_says_what_is_still_missing_at_every_step(app, dialog):
    assert refused(dialog) and dialog.status.words() == ""  # Blank is plain to see.
    dialog.url.setText("http://host/repo")
    assert refused(dialog) and "https address" in dialog.url_problem.words()
    dialog.url.setText("https://github.com/acme/handbook.git")
    assert refused(dialog) and dialog.url_problem.words() == ""
    assert "List the folders" in dialog.status.words()
    dialog.list_button.click()
    wait_for(app, lambda: dialog.passed)
    assert not refused(dialog) and dialog.status.words() == ""


def test_listing_runs_off_the_gui_thread_and_fills_the_table(app, dialog, probes):
    dialog.url.setText("https://github.com/acme/handbook.git")
    dialog.ref.setText("main")
    dialog.list_button.click()
    assert dialog.status.tone() == "busy" and not dialog.list_button.isEnabled()
    wait_for(app, lambda: dialog.passed)
    assert probes == [("https://github.com/acme/handbook.git", "main")]
    assert dialog.table.rowCount() == 3
    assert _text(dialog, 0) == "the whole repository"
    assert dialog.list_button.isEnabled() and dialog.empty.isHidden()


def test_a_failed_listing_says_one_sentence_and_keeps_the_primary_refused(app, services):
    def probe(_url, _ref):
        raise SourceUnavailableError("cannot reach acme/handbook — check the network")

    made = GitSourceDialog(services.window, tasks=services.tasks, probe=probe)
    try:
        made.url.setText("https://github.com/acme/handbook.git")
        made.list_button.click()
        wait_for(app, lambda: made.list_button.isEnabled() and made.status.tone() != "busy")
        assert made.status.words() == "cannot reach acme/handbook — check the network"
        assert refused(made) and made.status.tone() == "error"
    finally:
        made.deleteLater()


def test_an_oversized_folder_is_refused_with_the_folder_named(app, dialog, monkeypatch):
    monkeypatch.setattr(source, "MAX_DOCUMENTS", 1)
    dialog.url.setText("https://github.com/acme/handbook.git")
    dialog.list_button.click()
    wait_for(app, lambda: dialog.passed)
    dialog.table.selectRow(0)  # The whole repository: two documents, cap of one.
    assert refused(dialog) and "pick a folder inside it" in dialog.status.words()
    dialog.table.selectRow(1)
    assert not refused(dialog)


def test_editing_the_address_forgets_what_was_listed(app, dialog):
    dialog.url.setText("https://github.com/acme/handbook.git")
    dialog.list_button.click()
    wait_for(app, lambda: dialog.passed)
    dialog.url.setText("https://github.com/acme/other.git")
    assert not dialog.passed and dialog.table.rowCount() == 0 and refused(dialog)
    assert not dialog.empty.isHidden()


def test_the_dialog_answers_with_the_locator_the_person_picked(app, dialog):
    dialog.url.setText("git@github.com:acme/handbook.git")
    dialog.list_button.click()
    wait_for(app, lambda: dialog.passed)
    dialog.table.selectRow(2)
    assert dialog.chosen() == (
        "acme/handbook/docs/spec",
        {"url": "git@github.com:acme/handbook.git", "ref": "main", "path": "docs/spec"},
    )


# -- the kind over it ----------------------------------------------------------------------------


@pytest.fixture
def kind(services, tmp_path):
    return SpecGitKind(SpecGitDeps(tasks=services.tasks, cache_root=tmp_path / "spec-git"))


def test_locate_returns_what_the_dialog_answered(kind, services, monkeypatch):
    def accept(self):
        self.url.setText("https://github.com/acme/handbook.git")
        self._found = FOUND
        self._folders = list(FOUND.folders)
        self._fill()
        self.table.selectRow(1)
        return GitSourceDialog.DialogCode.Accepted

    monkeypatch.setattr(GitSourceDialog, "exec", accept)
    assert kind.locate(services.window) == (
        "acme/handbook/docs",
        {"url": "https://github.com/acme/handbook.git", "ref": "main", "path": "docs"},
    )
    monkeypatch.setattr(GitSourceDialog, "exec", lambda self: GitSourceDialog.DialogCode.Rejected)
    assert kind.locate(services.window) is None


def test_status_answers_without_a_subprocess(kind, monkeypatch):
    """It runs from an action's state on every context change."""

    def never(*_args, **_kwargs):
        raise AssertionError("status must not start a process")

    monkeypatch.setattr("dplanner.modules.spec_git.client.subprocess.Popen", never)
    good = {"url": "https://github.com/acme/handbook.git", "ref": "main", "path": "docs"}
    for _ in range(50):
        assert kind.status(good).ready
    refusal = kind.status({"url": "ext::sh -c x", "ref": "main", "path": ""})
    assert not refusal.ready and "not a git repository" in refusal.message


def test_git_missing_is_said_in_words_and_refuses_the_fetch(kind, monkeypatch):
    monkeypatch.setattr("dplanner.modules.spec_git.module.git_path", lambda: None)
    good = {"url": "https://github.com/acme/handbook.git", "ref": "main", "path": ""}
    assert kind.status(good).message == NO_GIT
    assert not kind.connect(None, good)
    with pytest.raises(SourceUnavailableError, match="git is not installed"):
        kind.check(good, {})


def test_connect_proves_access_and_stores_nothing(kind, services, monkeypatch, tmp_path):
    heard = []
    kind.config_changed.connect(lambda: heard.append(True))

    def accept(self):
        self._found = FOUND
        return GitSourceDialog.DialogCode.Accepted

    monkeypatch.setattr(GitSourceDialog, "exec", accept)
    good = {"url": "https://github.com/acme/handbook.git", "ref": "main", "path": "docs"}
    assert kind.connect(services.window, good) and heard == [True]
    # Nothing was written anywhere: no keychain, no settings, not even a cache directory.
    assert not (tmp_path / "spec-git").exists()


def test_the_probe_reads_a_real_repository(app, services, tmp_path, clean_git):  # noqa: F811
    """One slower test wiring the dialog to the real probe over a local bare repository,
    so the seam between them is proven and not only each half."""
    remote = make_remote(tmp_path, TREE)
    kind = SpecGitKind(SpecGitDeps(tasks=services.tasks, cache_root=tmp_path / "spec-git"))
    made = kind._dialog(services.window)
    try:
        made.url.setText(remote.url)
        made.ref.setText("main")
        made.list_button.click()
        wait_for(app, lambda: made.passed or made.status.tone() == "error")
        assert made.passed, made.status.words()
        assert [_text(made, row) for row in range(made.table.rowCount())] == [
            "the whole repository",
            "docs",
            "docs/spec",
        ]
    finally:
        made.deleteLater()


def test_the_real_build_offers_the_git_kind(services):
    spec = services.actions.spec("spec.add_source.git")
    assert spec.label == "&Git Repository…"


# -- the whole path, through the application the window builds -----------------------------------

DOCS = {
    "README.md": "# Handbook\n",
    "docs/spec/README.md": "# Spec\n",
    "docs/spec/auth.md": "# Auth\n\nWhat the modal asks for.\n",
    "docs/spec/tokens.md": "# Tokens\n",
}


@pytest.fixture
def live_git(tmp_path, monkeypatch, clean_git):  # noqa: F811
    """The real git kind in the real build, with its cache under ``tmp_path``.

    **Listed before ``services``**: the composition root resolves the cache root while it
    builds, so the patch must already be in place — the ``fake_kind`` ordering rule.
    """
    monkeypatch.setattr(
        "dplanner.core.config_dir.config_dir", lambda app="dplanner": tmp_path / "config"
    )
    return make_remote(tmp_path, DOCS)


def test_a_git_source_imports_a_subdirectory_and_then_sees_an_update(
    app, live_git, services, make_project, monkeypatch
):
    """The step's own test, end to end through the application the window builds: a git
    source added by its verb, its documents nested under the subdirectory's own README,
    and a commit upstream showing up in the next check."""
    from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
    from dplanner.modules.spec.documents import read_index

    project = make_project("Quick registration")
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )

    def accept(self):
        self.url.setText(live_git.url)
        self.ref.setText("main")
        self._list()
        wait_for(app, lambda: self.passed or self.status.tone() == "error")
        assert self.passed, self.status.words()
        row = next(
            index for index, folder in enumerate(self._folders) if folder.path == "docs/spec"
        )
        self.table.selectRow(row)
        return GitSourceDialog.DialogCode.Accepted

    monkeypatch.setattr(GitSourceDialog, "exec", accept)
    services.actions.run("spec.add_source.git", services.context.current())
    refresher = services.tabs.activities()[0]._refresher
    wait_for(app, lambda: not refresher.is_fetching())

    index = read_index(services.document.project(project.id))
    # Keys are relative to the chosen folder; the two pages hang under its own README,
    # by the name the spec module minted from that document's heading.
    assert [doc.key for doc in index.documents] == ["README.md", "auth.md", "tokens.md"]
    assert [doc.parent for doc in index.documents] == ["", "spec", "spec"]
    assert [doc.title for doc in index.documents] == ["Spec", "Auth", "Tokens"]
    assert index.sources[0].kind == "git" and index.sources[0].fetched

    # The remote moves, and the check says which document it was — no bodies downloaded.
    live_git.commit({"docs/spec/auth.md": "# Auth\n\nAnd what it answers.\n"}, "edit")
    refresher.check_all(project.id)
    wait_for(app, lambda: refresher.freshness(project.id, "src1") is not None)
    found = refresher.freshness(project.id, "src1")
    assert found is not None and found.changed == ("auth.md",)
    assert not found.added and not found.removed
