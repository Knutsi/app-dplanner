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
    cli("step", "add", "Discovery", "Deploy")
    cli_stdin("describe", "set", "Deploy", "--file", "-", stdin="The release step.")
    cli_stdin("agent", "set", "--for-project", "Discovery", "--file", "-", stdin="House rules.")
    cli("estimate", "set", "Deploy", "--days", "2")
    cli("schedule", "start", "Discovery", "--date", "2026-09-01")
    assert "Clean." in cli("project", "lint", "Discovery")


def test_a_bare_step_is_reported_on_every_authoring_axis(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert checks_in(report) == ["description.missing", "estimate.missing"]
    assert report["count"] == 2
    # Every finding says what to type next.
    assert all("dplanner " in row["message"] for row in report["findings"])


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


def test_spec_checks_track_the_link_lifecycle(cli, tmp_path):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    spec = tmp_path / "spec.txt"
    spec.write_text("The system must deploy on tag.\n")
    cli("spec", "import", "Discovery", str(spec))
    cli("spec", "mark", "Discovery", "spec", "--title", "Deploy on tag")

    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert "spec.requirement-unimplemented" in checks_in(report)
    assert "spec.step-unlinked" in checks_in(report)

    cli("spec", "link", "Deploy", "r1")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert "spec.requirement-unimplemented" not in checks_in(report)
    assert "spec.step-unlinked" not in checks_in(report)

    cli("spec", "unmark", "Discovery", "r1")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert "spec.link-dangling" in checks_in(report)


def test_a_replaced_document_exposes_quotes_that_no_longer_anchor(cli, tmp_path):
    def doc(name, text):
        path = tmp_path / name
        path.write_text(text)
        return str(path)

    cli("project", "create", "Discovery")
    cli("spec", "import", "Discovery", doc("s.md", "The rule is argon2id."), "--name", "s")
    cli("spec", "mark", "Discovery", "s", "--title", "Hashing", "--quote", "argon2id")
    cli("spec", "mark", "Discovery", "s", "--title", "Quoteless")
    cli("step", "add", "Discovery", "Deploy")
    cli("spec", "link", "Deploy", "r1", "r2")

    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert "spec.quote-unanchored" not in checks_in(report)

    cli("spec", "import", "Discovery", doc("s2.md", "The rule is scrypt now."), "--name", "s")
    report = data(cli("project", "lint", "Discovery", "--json", expect=1))
    assert "spec.quote-unanchored" in checks_in(report)
    flagged = [row for row in report["findings"] if row["check"] == "spec.quote-unanchored"]
    # Only the quoted requirement is flagged; a quoteless one has nothing to drift.
    assert [row["subject"] for row in flagged] == ["r1"]
    assert "spec mark" in flagged[0]["message"]


def test_a_description_image_that_resolves_nothing_is_reported(cli, cli_stdin, tmp_path):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    cli_stdin(
        "describe", "set", "Deploy", "--file", "-",
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
    cli("step", "add", "Two", "Deploy")
    report = data(cli("project", "lint", "--json", expect=1))
    projects = {row["project"] for row in report["findings"]}
    assert len(projects) == 1  # only Two has steps to complain about
    assert report["count"] == 2
