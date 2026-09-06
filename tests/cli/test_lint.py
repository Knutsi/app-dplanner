"""``dplanner project lint`` — the machine-checkable definition of a plan that is done.

No ``qapp`` fixture, like every CLI test: lint is the verb an agent runs last, on a machine
with no graphics stack.
"""

import json


def data(text):
    return json.loads(text)


def checks_in(report):
    return sorted({row["check"] for row in report["findings"]})


def test_a_complete_plan_is_clean_and_exits_zero(cli, cli_stdin):
    cli("project", "create", "Discovery")
    cli("project", "set", "Discovery", "--accept-colocation")
    cli_stdin("topology", "set", "Discovery", "--file", "-", stdin="One feature, one step.")
    cli("step", "add", "Discovery", "Deploy")
    cli_stdin("describe", "set", "Deploy", "--file", "-", stdin="The release step.")
    cli_stdin("agent", "set", "--for-project", "Discovery", "--file", "-", stdin="House rules.")
    cli("estimate", "set", "Deploy", "--days", "2")
    cli("schedule", "start", "Discovery", "--date", "2026-09-01")
    assert "Clean." in cli("project", "lint", "Discovery")


def test_a_bare_step_is_reported_on_every_authoring_axis(cli):
    cli("project", "create", "Discovery")
    cli("project", "set", "Discovery", "--accept-colocation")
    cli("step", "add", "Discovery", "Deploy")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert checks_in(report) == ["description.missing", "estimate.missing", "topology.missing"]
    assert report["count"] == 3
    # Every finding says what to type next.
    assert all("dplanner " in row["message"] for row in report["findings"])


def test_a_plan_with_no_code_repository_or_inside_it_is_a_finding_until_accepted(cli, workspace):
    """The plan's own place is the first thing lint asks about: a project that records
    no code repository reads as living inside it, one that records its own repository
    does, and both stop once the people on it say the plan stays there on purpose."""
    import subprocess

    cli("project", "create", "Discovery")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert "repo.unset" in checks_in(report)
    assert "project move" in next(
        r["message"] for r in report["findings"] if r["check"] == "repo.unset"
    )

    subprocess.run(
        ["git", "-C", str(workspace), "remote", "add", "origin", "https://github.com/acme/widget"],
        check=True,
    )
    cli("project", "set", "Discovery", "--repository", "git@github.com:acme/widget.git")
    checks = checks_in(data(cli("project", "lint", "Discovery", "--json", expect=1)))
    assert "repo.colocated" in checks and "repo.unset" not in checks

    cli("project", "set", "Discovery", "--accept-colocation")
    assert "Clean." in cli("project", "lint", "Discovery")


def test_an_agent_step_with_nothing_to_brief_it_is_reported(cli, cli_stdin):
    """A plain step owes no briefing; an agent step with no description, no separate
    instruction and no standing one cannot be launched, and lint says so."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy", "--agent")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert "agent.missing" in checks_in(report)

    cli_stdin("describe", "set", "Deploy", "--file", "-", stdin="The release step.")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert "agent.missing" not in checks_in(report)


def test_a_standing_instruction_silences_the_agent_check(cli, cli_stdin):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy", "--agent")
    cli_stdin("agent", "set", "--for-project", "Discovery", "--file", "-", stdin="House rules.")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert "agent.missing" not in checks_in(report)


def test_a_start_date_is_only_expected_once_something_is_estimated(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert "schedule.start-missing" not in checks_in(report)
    cli("estimate", "set", "Deploy", "--days", "2")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert "schedule.start-missing" in checks_in(report)


def test_a_project_with_steps_owes_a_topology(cli, cli_stdin):
    """An empty project has no shape to describe; the first step makes the question
    real, and the finding names the verb — the same one the gate points at."""
    cli("project", "create", "Discovery")
    cli("project", "set", "Discovery", "--accept-colocation")
    report = data(cli("project", "lint", "Discovery", "--json"))
    assert "topology.missing" not in checks_in(report)
    cli("step", "add", "Discovery", "Deploy")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    flagged = [row for row in report["findings"] if row["check"] == "topology.missing"]
    assert len(flagged) == 1 and "topology set 'Discovery'" in flagged[0]["message"]
    cli_stdin("topology", "set", "Discovery", "--file", "-", stdin="Flat.")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert "topology.missing" not in checks_in(report)


def test_a_description_image_that_resolves_nothing_is_reported(cli, cli_stdin, tmp_path):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    cli_stdin(
        "describe",
        "set",
        "Deploy",
        "--file",
        "-",
        stdin="See ![](assets/nope.png) and ![web](https://example.com/x.png).",
    )
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    flagged = [row for row in report["findings"] if row["check"] == "description.image-missing"]
    # The web image is not the module's file; only the area reference is checked.
    assert len(flagged) == 1 and "assets/nope.png" in flagged[0]["message"]

    figure = tmp_path / "diagram.png"
    figure.write_bytes(b"png bytes")
    attached = data(cli("describe", "attach", "Deploy", str(figure), "--json"))["asset"]
    cli_stdin("describe", "set", "Deploy", "--file", "-", stdin=f"See ![]({attached}).")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert "description.image-missing" not in checks_in(report)


def test_an_edge_kept_after_a_remove_is_finally_visible(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "A")
    cli("step", "add", "Discovery", "B", "--after", "A")
    cli("step", "remove", "A")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert "graph.requires-dangling" in checks_in(report)


def test_lint_without_a_project_covers_them_all(cli):
    cli("project", "create", "One")
    cli("project", "create", "Two")
    for title in ("One", "Two"):
        cli("project", "set", title, "--accept-colocation")
    cli("step", "add", "Two", "Deploy")
    report = data(cli("project", "lint", "--json", expect=1))
    projects = {row["project"] for row in report["findings"]}
    assert len(projects) == 1  # only Two has steps to complain about
    assert report["count"] == 3
