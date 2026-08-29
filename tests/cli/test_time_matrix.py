"""``dplanner schedule matrix`` and ``schedule focus`` end to end. No ``qapp`` fixture."""

import json

import pytest

from dplanner.domain.store import LibraryStore
from dplanner.modules.time_estimates.schedule import MODULE_ID


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
    assert data["calendar"] == [
        {"humans": 2, "agents": 3, "days": 8.0, "finish": "2026-09-16"}
    ]


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
