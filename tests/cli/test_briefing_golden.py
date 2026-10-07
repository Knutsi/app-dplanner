"""What an agent is briefed with, held to the byte.

One plan that exercises every block a briefing can carry — a description beside a separate
instruction, a feature's passages and a step flowing into it, a PR, a review with a round
posted, a branch stretch and its landing, notes addressed and
indexed, a code location — and ``dplanner agent prompt`` for each agent step in it, compared
with the text under ``golden/briefings/``. A briefing is prose many functions compose; this is
the test that says a refactor of where they live changed none of it.

``DPLANNER_REGEN_GOLDEN=1`` rewrites the files from the code as it stands — for a change that
*means* to reword a briefing, never to make a failure go away.
"""

import json
import os
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "golden" / "briefings"
TMP = "<tmp>"

CASES = (
    "parser",
    "review",
    "spec-reader",
    "member",
    "landing",
    "sign-in",
)


@pytest.fixture
def plan(cli, tmp_path, workspace):
    def text(name, body):
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        return str(path)

    cli("project", "create", "Widget")
    cli(
        "location",
        "add",
        "widget",
        "--role",
        "code",
        "--repository",
        "https://github.com/acme/widget",
        "--ref",
        "main",
        "--checkout",
        str(workspace),
    )
    # Parser's worktree is on this machine, so a step taking its work is told where.
    (workspace / ".dplanner-worktrees" / "s2-parser").mkdir(parents=True)
    cli(
        "topology",
        "set",
        "widget",
        "--file",
        text("topology.md", "Views are features; a release follows them.\n"),
    )
    cli("spec", "import", "widget", text("auth.md", "# Auth\n\nOperators MUST sign in.\n"))
    cli("step", "add", "widget", "Start", "--start")
    cli(
        "step",
        "add",
        "widget",
        "Parser",
        "--after",
        "Start",
        "--agent",
        "--describe-file",
        text("parser.md", "Parse the widget file.\n\nKeep the last line."),
        "--agent-file",
        text("parser-agent.md", "Run the parser tests first."),
    )
    cli("github", "set", "Parser", "--branch", "feat/parser", "--pr", "12")
    cli("step", "add", "widget", "Review", "--after", "Parser", "--agent", "--review")
    cli("status", "set", "Parser", "ready-for-review")
    cli("review", "start", "Review")
    cli("review", "post", "Review", "--text", "The parser drops the last line.")
    cli(
        "step",
        "add",
        "widget",
        "Spec reader",
        "--after",
        "Start",
        "--agent",
        "--describe-file",
        text("spec-reader.md", "Read the auth spec."),
    )
    cli(
        "step",
        "add",
        "widget",
        "Wire up",
        "--after",
        "Spec reader",
        "--agent",
        "--describe-file",
        text("wire-up.md", "Wire the reader in."),
    )
    cli(
        "step",
        "add",
        "widget",
        "Sign in",
        "--after",
        "Wire up",
        "--feature",
        "--agent",
        "--describe-file",
        text("sign-in.md", "Operators sign in before anything else."),
    )
    cli("feature", "cite", "Sign in", "--document", "auth", "--quote", "Operators MUST")
    cli(
        "step",
        "add",
        "widget",
        "Member",
        "--after",
        "Start",
        "--agent",
        "--describe-file",
        text("member.md", "Edit a stack."),
    )
    stretch = json.loads(cli("branch", "put", "Member", "--branch", "feature/stacks", "--json"))
    cli(
        "note",
        "add",
        "widget",
        "decision",
        "Parse line by line",
        "--step",
        "Start",
        "--text",
        "Streams are long.",
        "--made",
        "2026-10-01",
    )
    cli(
        "note",
        "add",
        "widget",
        "handoff",
        "The lexer is half done",
        "--step",
        "Start",
        "--for",
        "Parser",
        "--text",
        "Tokens are in lexer.py.",
        "--made",
        "2026-10-02",
    )
    return {
        "parser": "Parser",
        "review": "Review",
        "spec-reader": "Spec reader",
        "member": "Member",
        "landing": stretch["land"],
        "sign-in": "Sign in",
    }


@pytest.mark.parametrize("case", CASES)
def test_the_briefing_is_unchanged(cli, plan, tmp_path, case):
    prompt = json.loads(cli("agent", "prompt", plan[case], "--json"))["prompt"]
    prompt = prompt.replace(str(tmp_path), TMP)
    golden = GOLDEN / f"{case}.md"
    if os.environ.get("DPLANNER_REGEN_GOLDEN"):
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(prompt, encoding="utf-8")
    assert prompt == golden.read_text(encoding="utf-8")
