"""Each agent CLI's reader: a run's whole tree — the main agent and every subagent — per
model, from the records the CLI keeps on disk. The shapes are reduced copies of real
sessions read on 2026-10-01 (``docs/research/2026-10-01-agent-token-tracking.md``)."""

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dplanner.domain.agents import RunFacts, Tokens
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.agent_codex import harness as codex
from dplanner.modules.agent_opencode import harness as opencode

# -- Claude Code: the transcript tree ---------------------------------------------------------


def _assistant(message: str, request: str, model: str = "claude-opus-5-5", **usage: int) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "requestId": request,
            "message": {"id": message, "model": model, "usage": usage},
        }
    )


def _write(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
    return path


def test_a_claude_session_is_its_transcript_and_every_subagent_beside_it(tmp_path):
    """Three rules make the sum Claude Code's own: a request counts once however many lines
    carry it, the largest count of a request wins (a subagent's first line holds a
    placeholder output), and a request belongs to the first file that has it (a fork copies
    its parent's last one)."""
    config = tmp_path / "claude"
    session = "3f1c0b8e-0000-4000-8000-000000000001"
    directory = str(tmp_path / "code" / "widget")
    main = claude.transcript_path(session, directory, config)
    assert main.parent.name == re.sub(r"[^A-Za-z0-9]", "-", directory)
    _write(
        main,
        [
            json.dumps({"type": "user", "message": {"content": "hi"}}),
            _assistant(
                "m1",
                "r1",
                input_tokens=2,
                cache_creation_input_tokens=500,
                cache_read_input_tokens=1000,
                output_tokens=40,
            ),
            _assistant(
                "m1",
                "r1",
                input_tokens=2,
                cache_creation_input_tokens=500,
                cache_read_input_tokens=1000,
                output_tokens=40,
            ),
            "not json at all",
            _assistant(
                "m2",
                "r2",
                model="claude-opus-5-5[1m]",
                input_tokens=10,
                cache_read_input_tokens=1500,
                output_tokens=60,
            ),
            _assistant("x", "r9", model="<synthetic>", output_tokens=999),
        ],
    )
    subagents = main.parent / session / "subagents"
    _write(
        subagents / "agent-a1.jsonl",
        [
            _assistant("m2", "r2", input_tokens=10, cache_read_input_tokens=1500, output_tokens=60),
            _assistant(
                "m3",
                "r3",
                model="claude-haiku-4-5",
                input_tokens=5,
                cache_read_input_tokens=200,
                output_tokens=3,
            ),
            _assistant(
                "m3",
                "r3",
                model="claude-haiku-4-5",
                input_tokens=5,
                cache_read_input_tokens=200,
                output_tokens=700,
            ),
        ],
    )
    (subagents / "agent-a1.meta.json").write_text(json.dumps({"agentType": "Explore"}))

    report = claude.report(RunFacts(session, directory, "2026-10-01T10:00:00+00:00"), config)
    assert report is not None and report.session == session
    main_agent, explorer = report.agents
    assert (main_agent.id, main_agent.parent, main_agent.session) == ("main", "", session)
    assert main_agent.models == {"claude-opus-5-5": Tokens(input=512, cached=2500, output=100)}
    assert (explorer.id, explorer.parent, explorer.kind) == ("a1", "main", "Explore")
    assert explorer.models == {"claude-haiku-4-5": Tokens(input=5, cached=200, output=700)}
    assert report.tokens == Tokens(517, 2700, 800)


def test_a_claude_session_is_found_by_its_id_wherever_its_folder_is(tmp_path):
    """The folder is Claude Code's spelling of the working directory — a symlink, or a run
    whose directory record is gone, must not hide the session."""
    config = tmp_path / "claude"
    session = "3f1c0b8e-0000-4000-8000-000000000002"
    _write(
        config / "projects" / "-some-other-spelling" / f"{session}.jsonl",
        [_assistant("m", "r", input_tokens=1, output_tokens=2)],
    )
    report = claude.report(RunFacts(session, "", ""), config)
    assert report is not None and report.tokens == Tokens(1, 0, 2)


def test_a_missing_or_unreadable_claude_transcript_answers_none(tmp_path):
    facts = RunFacts("s", str(tmp_path), "2026-09-11T10:00:00+00:00")
    assert claude.report(facts, tmp_path / "nowhere") is None
    path = claude.transcript_path("s", str(tmp_path), tmp_path / "c")
    _write(path, [json.dumps({"type": "assistant", "message": {"id": "m", "usage": "?"}})])
    assert claude.report(facts, tmp_path / "c") is None
    assert claude.report(RunFacts("", str(tmp_path), ""), tmp_path / "c") is None


def test_the_claude_account_is_the_plan_and_an_opaque_id_and_nothing_else(tmp_path):
    path = tmp_path / ".claude.json"
    path.write_text(
        json.dumps(
            {
                "oauthAccount": {
                    "accountUuid": "acc-1",
                    "organizationType": "claude_max",
                    "emailAddress": "someone@example.com",
                    "displayName": "Someone",
                }
            }
        )
    )
    assert claude.read_account(path) == {"vendor": "anthropic", "plan": "claude_max", "id": "acc-1"}
    assert claude.read_account(tmp_path / "missing.json") == {}
    assert claude.account_file({"CLAUDE_CONFIG_DIR": "/cc"}) == Path("/cc/.claude.json")


def test_the_claude_config_dir_follows_the_persons_variable():
    assert claude.config_dir({"CLAUDE_CONFIG_DIR": "/home/me/.cc"}) == Path("/home/me/.cc")
    assert claude.config_dir({}) == Path.home() / ".claude"


# -- Codex: the rollout tree ------------------------------------------------------------------


def _rollout(
    home: Path,
    when: datetime,
    thread: str,
    cwd: str,
    lines: list[dict[str, object]],
    source: object = "cli",
) -> Path:
    local = when.astimezone()
    folder = home / "sessions" / f"{local.year:04d}" / f"{local.month:02d}" / f"{local.day:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-{local.strftime('%Y-%m-%dT%H-%M-%S')}-{thread}.jsonl"
    meta = {
        "timestamp": when.isoformat(),
        "type": "session_meta",
        "payload": {"id": thread, "timestamp": when.isoformat(), "cwd": cwd, "source": source},
    }
    path.write_text("\n".join(json.dumps(record) for record in [meta, *lines]))
    return path


def _token_count(plan: str = "", **totals: int) -> dict[str, object]:
    payload: dict[str, object] = {"type": "token_count", "info": {"total_token_usage": totals}}
    if plan:
        payload["rate_limits"] = {"primary": {"used_percent": 1.0}, "plan_type": plan}
    return {"timestamp": "x", "type": "event_msg", "payload": payload}


def _model(name: str) -> dict[str, object]:
    return {"type": "turn_context", "payload": {"model": name}}


def _response(thread: str, response: str, **usage: int) -> dict[str, object]:
    return {
        "type": "token_usage_record",
        "payload": {"thread_id": thread, "response_id": response, "usage": usage},
    }


def _state_index(home: Path, edges: list[tuple[str, str]], paths: dict[str, Path]) -> None:
    connection = sqlite3.connect(home / "state_5.sqlite")
    connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT)")
    connection.execute(
        "CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT)"
    )
    connection.executemany(
        "INSERT INTO threads VALUES (?, ?)", [(k, str(v)) for k, v in paths.items()]
    )
    connection.executemany("INSERT INTO thread_spawn_edges VALUES (?, ?)", edges)
    connection.commit()
    connection.close()


LAUNCHED = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
ROOT = "00000000-0000-4000-8000-00000000000b"
CHILD = "00000000-0000-4000-8000-00000000000c"


def test_the_codex_run_is_the_earliest_unclaimed_rollout_in_its_directory(tmp_path):
    """Codex mints its own thread ids: the run is found by where and when it began — never
    a thread another run already owns, never a subagent's rollout — and the last cumulative
    count is the total of a rollout that keeps no per-response records."""
    home = tmp_path / "codex"
    tree = str(tmp_path / "widget")
    earlier, taken = "0" * 35 + "a", "0" * 35 + "d"
    _rollout(home, LAUNCHED - timedelta(hours=1), earlier, tree, [_token_count(input_tokens=1)])
    _rollout(home, LAUNCHED + timedelta(seconds=10), taken, tree, [_token_count(input_tokens=2)])
    _rollout(
        home,
        LAUNCHED + timedelta(seconds=15),
        CHILD,
        tree,
        [],
        source={"subagent": {"thread_spawn": {"parent_thread_id": taken}}},
    )
    _rollout(
        home,
        LAUNCHED + timedelta(seconds=30),
        ROOT,
        tree,
        [
            _model("gpt-5.6-sol"),
            _token_count(input_tokens=100, output_tokens=10),
            _token_count(
                plan="plus",
                input_tokens=900,
                cached_input_tokens=600,
                cache_write_input_tokens=50,
                output_tokens=80,
            ),
        ],
    )
    facts = RunFacts("", tree, LAUNCHED.isoformat(), claimed=frozenset({taken}))
    report = codex.report(facts, home)
    assert report is not None and report.session == ROOT
    (main,) = report.agents
    assert main.models == {"gpt-5.6-sol": Tokens(input=350, cached=600, output=80)}
    assert report.account == {"vendor": "openai", "plan": "plus"}
    assert report.partial  # No state index: the subagents could not be looked for.
    assert codex.report(RunFacts("", str(tmp_path / "nowhere"), LAUNCHED.isoformat()), home) is None
    assert codex.report(RunFacts("", tree, "not a time"), home) is None


def test_a_codex_tree_is_the_root_and_every_thread_the_index_says_it_spawned(tmp_path):
    """A child's rollout replays its parent's history; counting only the records that name
    the child's own thread keeps the parent's tokens out of it."""
    home = tmp_path / "codex"
    tree = str(tmp_path / "widget")
    root = _rollout(
        home,
        LAUNCHED,
        ROOT,
        tree,
        [
            _model("gpt-5.6-sol"),
            _response(ROOT, "p1", input_tokens=15000, cached_input_tokens=11000, output_tokens=200),
            _response(ROOT, "p2", input_tokens=27157, cached_input_tokens=23000, output_tokens=335),
            _token_count(input_tokens=42157, cached_input_tokens=38528, output_tokens=535),
        ],
    )
    child = _rollout(
        home,
        LAUNCHED + timedelta(seconds=7),
        CHILD,
        tree,
        [
            _model("gpt-5.6-sol"),
            _response(ROOT, "p1", input_tokens=15000, cached_input_tokens=11000, output_tokens=200),
            _response(
                CHILD, "c1", input_tokens=15261, cached_input_tokens=11136, output_tokens=164
            ),
            _response(
                CHILD, "c1", input_tokens=15261, cached_input_tokens=11136, output_tokens=164
            ),
            _response(
                CHILD, "c2", input_tokens=15675, cached_input_tokens=11136, output_tokens=144
            ),
        ],
        source={"subagent": {"thread_spawn": {"parent_thread_id": ROOT}}},
    )
    _state_index(home, [(ROOT, CHILD)], {ROOT: root, CHILD: child})

    report = codex.report(RunFacts(ROOT, "", ""), home)
    assert report is not None and not report.partial
    main, spawned = report.agents
    assert main.models["gpt-5.6-sol"] == Tokens(input=4000 + 4157, cached=34000, output=535)
    assert (spawned.id, spawned.parent, spawned.session) == (CHILD, "main", CHILD)
    assert spawned.models["gpt-5.6-sol"] == Tokens(
        input=(15261 - 11136) + (15675 - 11136), cached=2 * 11136, output=164 + 144
    )


def test_the_codex_home_follows_the_persons_variable():
    assert codex.codex_home({"CODEX_HOME": "/srv/codex"}) == Path("/srv/codex")
    assert codex.codex_home({}) == Path.home() / ".codex"


# -- OpenCode: the session tree ---------------------------------------------------------------


def _opencode_db(path: Path, rows: list[tuple[object, ...]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE session (id TEXT PRIMARY KEY, parent_id TEXT, directory TEXT,"
        " time_created INTEGER, model TEXT, tokens_input INTEGER, tokens_output INTEGER,"
        " tokens_reasoning INTEGER, tokens_cache_read INTEGER, tokens_cache_write INTEGER)"
    )
    connection.executemany("INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    connection.commit()
    connection.close()


def _oc_model(model: str, provider: str = "anthropic") -> str:
    return json.dumps({"id": model, "providerID": provider})


def test_an_opencode_run_is_its_session_and_every_child_session_under_it(tmp_path):
    """The session OpenCode keeps holds its own totals only: a task's child session is read
    by its parent id, down the whole tree."""
    db = tmp_path / "opencode.db"
    ms = int(LAUNCHED.timestamp() * 1000)
    sonnet, haiku = _oc_model("claude-sonnet-5"), _oc_model("claude-haiku-4-5")
    _opencode_db(
        db,
        [
            ("ses_old", None, "/w", ms - 3_600_000, sonnet, 1, 1, 0, 0, 0),
            ("ses_taken", None, "/w", ms + 10_000, sonnet, 2, 2, 0, 0, 0),
            ("ses_ours", None, "/w", ms + 20_000, sonnet, 100, 40, 10, 300, 50),
            ("ses_kid", "ses_ours", "/w", ms + 30_000, haiku, 7, 3, 0, 20, 0),
            ("ses_grandkid", "ses_kid", "/w", ms + 40_000, haiku, 1, 1, 0, 0, 0),
            ("ses_other", None, "/elsewhere", ms + 20_000, sonnet, 7, 7, 0, 0, 0),
        ],
    )
    (tmp_path / "auth.json").write_text(json.dumps({"anthropic": {"type": "oauth", "access": "x"}}))
    facts = RunFacts("", "/w", LAUNCHED.isoformat(), claimed=frozenset({"ses_taken"}))
    report = opencode.report(facts, db)
    assert report is not None and report.session == "ses_ours"
    assert [(a.id, a.parent) for a in report.agents] == [
        ("main", ""),
        ("ses_kid", "main"),
        ("ses_grandkid", "ses_kid"),
    ]
    assert report.agents[0].models == {"claude-sonnet-5": Tokens(input=150, cached=300, output=50)}
    assert report.tokens == Tokens(150 + 7 + 1, 320, 50 + 3 + 1)
    assert report.account == {"vendor": "anthropic", "plan": "oauth"}
    by_id = opencode.report(RunFacts("ses_kid", "", ""), db)
    assert by_id is not None and [a.id for a in by_id.agents] == ["main", "ses_grandkid"]
    assert opencode.report(RunFacts("", "/nowhere", LAUNCHED.isoformat()), db) is None
    assert opencode.report(RunFacts("", "/w", LAUNCHED.isoformat()), tmp_path / "none.db") is None


def test_an_opencode_database_this_build_cannot_read_answers_none(tmp_path):
    db = tmp_path / "opencode.db"
    sqlite3.connect(db).execute("CREATE TABLE session (id TEXT)").connection.close()
    assert opencode.report(RunFacts("", "/w", "2026-09-11T10:00:00+00:00"), db) is None


def test_the_opencode_database_path_follows_the_variables():
    home = Path("/home/dev")
    assert opencode.database_path({"OPENCODE_DB": "/x/o.db"}) == Path("/x/o.db")
    assert opencode.database_path({"XDG_DATA_HOME": "/d"}) == Path("/d/opencode/opencode.db")
    assert opencode.database_path({}, "linux", home) == home / ".local/share/opencode/opencode.db"
    # XDG is not a Windows idea; the data directory there is %LOCALAPPDATA%.
    local = Path("C:/Users/dev/AppData/Local")
    assert opencode.database_path({"LOCALAPPDATA": str(local)}, "win32", home) == (
        local / "opencode" / "opencode.db"
    )
    assert opencode.database_path({}, "win32", home) == (
        home / "AppData" / "Local" / "opencode" / "opencode.db"
    )
