"""The bootstrap skill: hand-written, because it runs before DPlanner exists to generate
anything, and held here to what the installer actually does.

It lives in the Claude Code plugin at ``plugins/dplanner`` — the one home every route reaches:
a marketplace install, Codex's skill installer pointed at the repository, or any agent told
to read the file's URL. ARCHITECTURE.md's *Installing is one act* has the reasoning.
"""

import json
import re
from pathlib import Path

from dplanner.cli.checklist import MANAGERS
from dplanner.cli.main import PROG, WINDOW_SHORTCUT, WINDOW_WORD
from dplanner.identity import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN = ROOT / "plugins" / "dplanner"
SKILL = PLUGIN / "skills" / "dplanner-install" / "SKILL.md"


def parts() -> tuple[str, str]:
    """The skill's front matter and its body."""
    _, front, body = SKILL.read_text(encoding="utf-8").split("---\n", 2)
    return front, body


def test_the_skill_names_itself_after_its_folder_and_says_when_to_reach_for_it() -> None:
    front, _ = parts()
    assert re.search(rf"^name: {SKILL.parent.name}$", front, re.MULTILINE)
    assert re.search(r"^description: .*not on PATH", front, re.MULTILINE)


def test_the_skill_warns_that_dplanner_is_a_work_in_progress_before_installing() -> None:
    """The user is told what they are getting before anything is written — the warning
    comes before the first step, and it is about compatibility as much as features."""
    _, body = parts()
    assert body.index("work in progress") < body.index("## 1.")
    assert "compatibility between versions" in body
    assert "feature set is not stable" in body


def test_the_skill_installs_the_way_the_installer_does() -> None:
    _, body = parts()
    for line in (
        f"{PROG} install all",
        f"{PROG} install status",
        f"{PROG} checklist show",
        f"{PROG} install remove",
        f"uv tool uninstall {PROG}",
        "git clone https://github.com/Knutsi/app-dplanner",
    ):
        assert line in body, line
    assert "worktree" in body  # The installer refuses one; the skill says not to try.


def test_the_skill_covers_every_package_manager_the_checklist_knows() -> None:
    _, body = parts()
    missing = [manager for manager in MANAGERS if manager not in body]
    assert missing == []
    assert "astral.sh/uv/install.sh" in body


def test_the_skill_never_names_the_window() -> None:
    """The word is not a noun (tests/cli/test_entry.py reserves it); the launcher opens it."""
    _, body = parts()
    assert f"{PROG} {WINDOW_WORD}" not in body
    assert re.search(rf"\b{WINDOW_SHORTCUT}\b", body) is None


def test_the_plugin_carries_the_build_version() -> None:
    """Claude Code updates a plugin when its version moves, and the version is one string
    (identity.APP_VERSION) — so the manifest may not carry another."""
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    assert manifest["name"] == "dplanner"
    assert manifest["version"] == APP_VERSION


def test_the_marketplace_lists_the_plugin_where_it_is() -> None:
    marketplace = json.loads(MARKETPLACE.read_text("utf-8"))
    assert marketplace["name"] == "dplanner"
    (entry,) = marketplace["plugins"]
    assert entry["name"] == "dplanner"
    assert (ROOT / entry["source"]).resolve() == PLUGIN
    assert SKILL.is_file()
