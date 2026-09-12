"""``dplanner schedule matrix`` and ``schedule focus`` end to end. No ``qapp`` fixture."""

import json
from datetime import date

import pytest

from dplanner.domain.store import LibraryStore
from dplanner.modules.time_estimates.schedule import MODULE_ID, PALETTES, shades


@pytest.fixture
def cli(cli):
    """A chain of two 2d human steps, plus an independent 1d agent step, dated.

    Human work serialises to 4d whatever the staffing (it is one chain), the agent step
    rides alongside — so every parallel cell reads 4d, and at 50% focus every calendar
    cell reads 8d, landing eight working days after Monday 7 September 2026.
    """
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Read the spec", "--days", "2")
    cli("step", "add", "Discovery", "Draft the model", "--days", "2")
    cli("step", "add", "Discovery", "Write the docs", "--days", "1", "--agent")
    cli("step", "link", "draft-the-model", "read-the-spec")
    cli("schedule", "start", "Discovery", "--date", "2026-09-07")
    return cli


def test_the_full_grid_prices_every_staffing(cli):
    data = json.loads(cli("schedule", "matrix", "Discovery", "--json"))
    assert data["effort"] == {"human": 4.0, "agent": 1.0, "total": 5.0}
    assert data["efficiency"] == 0.5
    assert data["unestimated"] == 0
    assert data["has_agent_steps"] is True
    assert data["floor"] == {"days": 4.0, "calendar_days": 8.0}
    assert len(data["parallel"]) == 12 and len(data["calendar"]) == 12
    assert {cell["days"] for cell in data["parallel"]} == {4.0}
    assert {cell["days"] for cell in data["calendar"]} == {8.0}
    assert {cell["finish"] for cell in data["calendar"]} == {"2026-09-16"}
    assert {(cell["humans"], cell["agents"]) for cell in data["parallel"]} == {
        (humans, agents) for humans in (1, 2, 3) for agents in (1, 2, 3, 4)
    }


def test_naming_a_team_narrows_the_grid_to_it(cli):
    data = json.loads(
        cli("schedule", "matrix", "Discovery", "--humans", "2", "--agents", "3", "--json")
    )
    assert data["parallel"] == [{"humans": 2, "agents": 3, "days": 4.0}]
    assert data["calendar"] == [{"humans": 2, "agents": 3, "days": 8.0, "finish": "2026-09-16"}]


def test_half_a_team_is_refused(cli):
    said = cli("schedule", "matrix", "Discovery", "--humans", "2", expect=1)
    assert "both --humans and --agents" in said


def test_an_efficiency_override_prices_this_run_and_stores_nothing(cli, cli_library):
    data = json.loads(cli("schedule", "matrix", "Discovery", "--efficiency", "80", "--json"))
    assert data["efficiency"] == 0.8
    assert {cell["days"] for cell in data["calendar"]} == {5.0}  # 2/0.8 twice, down the chain
    library = LibraryStore(cli_library).load()
    assert MODULE_ID not in library.projects[0].module_data  # an override never writes
    again = json.loads(cli("schedule", "matrix", "Discovery", "--json"))
    assert again["efficiency"] == 0.5


def test_focus_is_stored_cleared_and_read_back_by_the_matrix(cli, cli_library):
    cli("schedule", "focus", "Discovery", "--percent", "25")
    library = LibraryStore(cli_library).load()
    entry = library.projects[0].module_data[MODULE_ID]
    assert entry["efficiency"] == 0.25 and isinstance(entry["efficiency"], float)
    data = json.loads(cli("schedule", "matrix", "Discovery", "--json"))
    assert data["efficiency"] == 0.25
    assert {cell["days"] for cell in data["calendar"]} == {16.0}
    cli("schedule", "focus", "Discovery", "--clear")
    library = LibraryStore(cli_library).load()
    assert MODULE_ID not in library.projects[0].module_data
    assert "give either" in cli("schedule", "focus", "Discovery", expect=1)


def test_a_stepless_project_reports_no_steps(cli):
    cli("project", "create", "Empty")
    assert "No steps yet." in cli("schedule", "matrix", "Empty")


def test_the_prose_prints_both_matrices_and_the_agent_note(cli):
    said = cli("schedule", "matrix", "Discovery")
    assert "Parallel-adjusted" in said
    assert "Calendar (at 50% focus, from 7 September" in said
    assert "4 agents" in said
    assert "No agent steps" not in said
    cli("project", "create", "Manual")
    cli("step", "add", "Manual", "By hand", "--days", "1")
    assert "No agent steps" in cli("schedule", "matrix", "Manual")


# -- milestones in sequence --------------------------------------------------------------------


@pytest.fixture
def staged(cli):
    """The chain closed by two milestones: v1 is the model, v2 the docs on top of it."""
    cli("step", "add", "Discovery", "Ship the docs", "--days", "2")
    cli("step", "link", "ship-the-docs", "write-the-docs")
    cli("step", "link", "ship-the-docs", "draft-the-model")
    cli("milestone", "set", "draft-the-model", "--label", "v1")
    cli("milestone", "set", "ship-the-docs", "--label", "v2")
    return cli


def test_the_milestones_land_in_sequence_for_the_smallest_team(staged):
    data = json.loads(staged("schedule", "matrix", "Discovery", "--json"))
    assert data["team"] == {"humans": 1, "agents": 1}
    v1, v2 = data["milestones"]
    assert v1["label"] == "v1" and len(v1["steps"]) == 2 and v1["step"] == v1["steps"][-1]
    assert (v1["start"], v1["finish"]) == ("2026-09-07", "2026-09-16")  # 8 calendar days
    assert v2["label"] == "v2"
    assert v2["start"] == "2026-09-17"
    assert v2["finish"] == "2026-09-23"  # the agent day, then 2/0.5 = 4 days of docs
    assert [v1["color"], v2["color"]] == shades(PALETTES[0], 2)
    assert data["palette"] == "viridis"
    assert not v1["pushed"] and not v2["pushed"]
    assert {cell["finish"] for cell in data["calendar"]} == {"2026-09-23"}


def test_dating_a_milestone_moves_its_stretch_and_the_whole(staged, cli_library):
    said = staged("schedule", "milestone", "ship-the-docs", "--start", "2026-10-05")
    assert "v2 (Ship the docs): starts 5 October" in said
    library = LibraryStore(cli_library).load()
    docs = next(step for step in library.projects[0].steps if step.title == "Ship the docs")
    assert docs.module_data[MODULE_ID] == {"start": "2026-10-05", "format": 1}
    data = json.loads(staged("schedule", "matrix", "Discovery", "--json"))
    v2 = data["milestones"][1]
    assert (v2["asked"], v2["start"], v2["finish"]) == ("2026-10-05", "2026-10-05", "2026-10-09")
    assert data["calendar"][0]["finish"] == "2026-10-09"
    staged("schedule", "milestone", "ship-the-docs", "--clear-start")
    library = LibraryStore(cli_library).load()
    docs = next(step for step in library.projects[0].steps if step.title == "Ship the docs")
    assert MODULE_ID not in docs.module_data


def test_a_date_the_sequence_cannot_keep_is_pushed_and_said(staged):
    staged("schedule", "milestone", "ship-the-docs", "--start", "2026-09-10")
    data = json.loads(staged("schedule", "matrix", "Discovery", "--json"))
    v2 = data["milestones"][1]
    assert v2["pushed"] and v2["start"] == "2026-09-17"
    said = staged("schedule", "matrix", "Discovery")
    assert "asked for 10 September, but the previous lands later" in said


def test_a_milestone_colour_is_stored_lower_case_and_cleared(staged, cli_library):
    staged("schedule", "milestone", "draft-the-model", "--color", "#C98500")
    data = json.loads(staged("schedule", "matrix", "Discovery", "--json"))
    assert data["milestones"][0]["color"] == "#c98500"
    assert data["milestones"][1]["color"] == shades(PALETTES[0], 2)[1]  # still dealt in turn
    assert "--color is #rrggbb" in staged(
        "schedule", "milestone", "draft-the-model", "--color", "orange", expect=1
    )
    staged("schedule", "milestone", "draft-the-model", "--clear-color")
    library = LibraryStore(cli_library).load()
    model = next(step for step in library.projects[0].steps if step.title == "Draft the model")
    assert MODULE_ID not in model.module_data


def test_the_palette_is_chosen_listed_and_kept_beside_the_focus_factor(staged, cli_library):
    said = staged("schedule", "palette", "Discovery")
    assert "shaded from Viridis" in said and "* viridis" in said and "  mako" in said
    assert "shaded from Mako" in staged("schedule", "palette", "Discovery", "mako")
    data = json.loads(staged("schedule", "matrix", "Discovery", "--json"))
    mako = next(found for found in PALETTES if found.id == "mako")
    assert data["palette"] == "mako"
    assert [m["color"] for m in data["milestones"]] == shades(mako, 2)
    # The focus factor and the palette share the entry; each write keeps the other.
    staged("schedule", "focus", "Discovery", "--percent", "60")
    library = LibraryStore(cli_library).load()
    assert library.projects[0].module_data[MODULE_ID] == {
        "efficiency": 0.6,
        "palette": "mako",
        "format": 1,
    }
    assert "no palette called 'neon'" in staged(
        "schedule", "palette", "Discovery", "neon", expect=1
    )
    staged("schedule", "palette", "Discovery", "viridis")  # the default: absent again
    library = LibraryStore(cli_library).load()
    assert library.projects[0].module_data[MODULE_ID] == {"efficiency": 0.6, "format": 1}


def test_only_a_milestone_takes_a_date(staged):
    said = staged("schedule", "milestone", "read-the-spec", "--start", "2026-10-05", expect=1)
    assert "is not a milestone" in said
    assert "nothing to change" in staged("schedule", "milestone", "draft-the-model", expect=1)


def test_the_prose_lists_the_milestones_in_sequence(staged):
    said = staged("schedule", "matrix", "Discovery")
    assert "Milestones in sequence (1 person + 1 agents)" in said
    assert "v1: 7 September → 16 September (1.6w, 2 steps)" in said
    assert "v2: 17 September → 23 September (5d, 2 steps)" in said


def test_a_loop_in_the_file_is_refused_with_its_steps_named(cli, workspace):
    """The model refuses a cycle; a file does not. Write one in by hand."""
    steps = workspace / "discovery" / "steps"
    draft = json.loads((steps / "draft-the-model" / "step.json").read_text())["id"]
    record = steps / "read-the-spec" / "step.json"
    raw = json.loads(record.read_text())
    raw["edges"] = {"requires": [draft]}
    record.write_text(json.dumps(raw))
    said = cli("schedule", "matrix", "Discovery", expect=1)
    assert "wait on each other" in said
    assert "'Read the spec'" in said and "'Draft the model'" in said


# -- the team, and progress against the plan -----------------------------------------------------


def test_the_team_is_stored_and_the_milestones_are_printed_for_it(staged, cli_library):
    staged("schedule", "team", "Discovery", "--humans", "2", "--agents", "3")
    library = LibraryStore(cli_library).load()
    assert library.projects[0].module_data[MODULE_ID] == {"team": [2, 3], "format": 1}
    data = json.loads(staged("schedule", "matrix", "Discovery", "--json"))
    assert data["team"] == {"humans": 2, "agents": 3}
    said = staged("schedule", "team", "Discovery", "--clear")
    assert "1 person + 1 agent" in said
    library = LibraryStore(cli_library).load()
    assert MODULE_ID not in library.projects[0].module_data
    assert "both --humans and --agents" in staged("schedule", "team", "Discovery", expect=1)
    assert "≥ 1" in staged(
        "schedule", "team", "Discovery", "--humans", "0", "--agents", "1", expect=1
    )


def test_the_team_rides_beside_the_focus_and_the_palette(staged, cli_library):
    staged("schedule", "team", "Discovery", "--humans", "2", "--agents", "1")
    staged("schedule", "focus", "Discovery", "--percent", "60")
    staged("schedule", "palette", "Discovery", "mako")
    library = LibraryStore(cli_library).load()
    assert library.projects[0].module_data[MODULE_ID] == {
        "efficiency": 0.6,
        "palette": "mako",
        "team": [2, 1],
        "format": 1,
    }
    staged("schedule", "focus", "Discovery", "--clear")
    library = LibraryStore(cli_library).load()
    assert library.projects[0].module_data[MODULE_ID] == {
        "palette": "mako",
        "team": [2, 1],
        "format": 1,
    }


def test_progress_show_counts_what_landed_toward_each_milestone(staged):
    staged("status", "set", "read-the-spec", "done")
    data = json.loads(staged("progress", "show", "Discovery", "--json"))
    v1, v2, whole = data["scopes"]
    assert (v1["label"], v1["steps"], v1["done"], v1["by_steps"]) == ("v1", 2, 1, 0.5)
    assert (v1["days"], v1["done_days"], v1["by_days"]) == (4.0, 2.0, 0.5)
    assert v1["finish"] == "2026-09-16"
    assert (v2["label"], v2["steps"], v2["done"], v2["finish"]) == ("v2", 4, 1, "2026-09-23")
    assert whole["label"] == "All work" and whole["by_steps"] == 0.25
    assert whole["expected"][0] == {"date": "2026-09-07", "share": 0.0}
    assert whole["expected"][-1] == {"date": "2026-09-23", "share": 1.0}
    assert whole["actual"] == [{"date": date.today().isoformat(), "share": 0.25}]
    assert data["recorded_days"] == 0
    assert whole["baseline"] is None and whole["delta"] is None
    assert "no earlier plan" not in staged("progress", "show", "Discovery")
    said = staged("progress", "show", "Discovery")
    assert "v1: 50% by steps (1 of 2), 50% by days (2d of 4d) — lands 16 September" in said
    assert "All work: 25% by steps" in said
    # A milestone is named by its label or by its step, whichever comes to mind.
    one = json.loads(staged("progress", "show", "Discovery", "--milestone", "v2", "--json"))
    assert [scope["label"] for scope in one["scopes"]] == ["v2"]
    by_step = json.loads(staged("progress", "show", "Discovery", "--milestone", "S4", "--json"))
    assert [scope["label"] for scope in by_step["scopes"]] == ["v2"]
    assert "not a milestone" in staged(
        "progress", "show", "Discovery", "--milestone", "read-the-spec", expect=1
    )


def test_progress_record_writes_a_day_once_and_the_delta_reads_against_it(
    staged, cli_library, workspace
):
    assert "progress recorded" in staged("progress", "record", "Discovery")
    assert "nothing changed" in staged("progress", "record", "Discovery")
    library = LibraryStore(cli_library).load()
    (row,) = library.projects[0].module_data["progress_history"]["days"]
    assert row["day"] == date.today().isoformat() and len(row["stretches"]) == 2
    assert row["stretches"][0]["landings"][-1] == {"date": "2026-09-16", "steps": 1, "days": 2.0}
    # Date the record back to the 1st, before the basis: a history that begins today has
    # no baseline to compare against, and a change on the record's own day is inside that
    # day's record, so today's edits only read as changes against an earlier day.
    history_file = next(workspace.glob("*/modules/progress_history.json"))
    entry = json.loads(history_file.read_text())
    entry["days"][0]["day"] = "2026-09-01"
    history_file.write_text(json.dumps(entry))
    for step_file in workspace.glob("*/steps/*/step.json"):  # born before that record
        node = json.loads(step_file.read_text())
        node["created"] = "2026-08-30T09:00:00+00:00"
        step_file.write_text(json.dumps(node))
    data = json.loads(staged("progress", "show", "Discovery", "--json"))
    assert data["basis"] == "2026-09-07" and data["baseline_day"] == "2026-09-01"
    assert data["scopes"][1]["delta"] == {
        "steps": 0,
        "days": 0.0,
        "finish_then": "2026-09-23",
        "finish_now": "2026-09-23",
        "shift": 0,
    }
    assert "v2: 0% by steps (0 of 4), 0% by days (0d of 7d) — lands 23 September; unchanged" in (
        staged("progress", "show", "Discovery")
    )
    # More work behind v2 moves its landing; the report says what moved it.
    staged("step", "add", "Discovery", "Polish", "--days", "2")
    staged("step", "link", "ship-the-docs", "polish")
    staged("estimate", "set", "read-the-spec", "--days", "3")
    data = json.loads(staged("progress", "show", "Discovery", "--json"))
    v2 = data["scopes"][1]
    assert (
        v2["finish"] == "2026-09-30"
    )  # six days of reading, then four of polishing, four of shipping
    assert data["baseline_day"] == "2026-09-01" and data["changes"]["since"] == "2026-09-01"
    assert v2["baseline"]["finish"] == "2026-09-23" and v2["baseline"]["steps"] == 4
    assert v2["baseline"]["expected"][0] == {"date": "2026-09-07", "share": 0.0}
    assert v2["delta"]["steps"] == 1 and v2["delta"]["days"] == 3.0 and v2["delta"]["shift"] == 5
    assert [(row["key"], row["days"]) for row in data["changes"]["added"]] == [("S5", 2.0)]
    assert data["changes"]["estimates"] == [
        {
            "step": data["changes"]["estimates"][0]["step"],
            "key": "S1",
            "title": "Read the spec",
            "day": date.today().isoformat(),
            "from": 2.0,
            "to": 3.0,
        }
    ]
    said = staged("progress", "show", "Discovery")
    assert "since 1 September: +1 step, +3d, lands 5 working days later (was 23 September)" in said
    assert "added since 1 September: S5 (2d)" in said
    assert "re-estimated since 1 September: S1 2d → 3d on" in said
    staged("progress", "record", "Discovery")  # a new day's row, after the dated-back one
    library = LibraryStore(cli_library).load()
    first, second = library.projects[0].module_data["progress_history"]["days"]
    assert first["day"] == "2026-09-01" and second["stretches"][1]["finish"] == "2026-09-30"


def test_the_basis_can_be_any_day_and_a_bad_one_is_refused(staged):
    staged("progress", "record", "Discovery")
    data = json.loads(staged("progress", "show", "Discovery", "--basis", "2030-01-01", "--json"))
    assert data["basis"] == "2030-01-01" and data["baseline_day"] == date.today().isoformat()
    assert "compared with the plan recorded" in staged(
        "progress", "show", "Discovery", "--basis", "2030-01-01"
    )
    assert "YYYY-MM-DD" in staged("progress", "show", "Discovery", "--basis", "soon", expect=1)
    # Nothing was recorded that early and the only record is today's own, which is the
    # plan now: there is no earlier plan to compare with, and none is claimed.
    fresh = json.loads(staged("progress", "show", "Discovery", "--basis", "2020-01-01", "--json"))
    assert fresh["baseline_day"] == "" and fresh["scopes"][0]["baseline"] is None


def test_progress_on_a_stepless_project_says_so(cli):
    cli("project", "create", "Empty")
    assert "No steps yet." in cli("progress", "show", "Empty")
    assert "nothing to record" in cli("progress", "record", "Empty", expect=1)
