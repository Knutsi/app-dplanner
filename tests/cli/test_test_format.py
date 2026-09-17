"""The house format of a test body, and the door it is read through.

The same arrangement as the topology's, one level in: a document this build owns, printed
by one verb, recorded in the same per-user record, and refused until it has been read —
which is what puts it in front of every agent that writes a test and no agent that does
not. ``gated_cli`` (``tests/cli/conftest.py``) is the CLI with both doors live.
"""

import json

import pytest
from tests.cli.skill_helpers import noun_verbs

from dplanner.modules.testing.format import guide


def data(text):
    return json.loads(text)


@pytest.fixture
def step(gated_cli):
    """A project past the topology gate, with one step to hang tests on."""
    gated_cli("topology", "set", "Discovery", "--file", "-", stdin="Views are features.")
    gated_cli("topology", "show", "Discovery")
    gated_cli("step", "add", "Discovery", "Sign a document")
    return "Sign a document"


# -- what the document says ------------------------------------------------------------------


def test_the_format_is_preconditions_then_numbered_steps():
    """The shape the user asked for, and the one thing a stranger executing a test needs."""
    prose = " ".join(guide().split())
    assert "## Preconditions" in prose and "## Steps" in prose
    assert "Preconditions are bullets, and each one is a state rather than an action" in prose
    assert "Steps are numbered, one action each, in the imperative" in prose
    assert "the last one says what proves the test passed" in prose
    assert "One test per thing that can independently break" in prose


def test_screenshots_carry_their_sequence_and_their_annotation():
    """A picture in the step it belongs to, the alt text saying what to look at — the
    sequence is the step number, so nothing had to be invented to order them."""
    prose = " ".join(guide().split())
    assert "dplanner test attach" in prose
    assert "A picture goes in the step it belongs to, in the order the steps run" in prose
    assert "The alt text is the annotation" in prose
    assert "The words still stand without it" in prose


def test_concurrency_is_asked_about_rather_than_assumed():
    """The thought this document exists to put in front of an agent: every single-actor
    test passes while the multi-user bug ships."""
    prose = " ".join(guide().split())
    assert "which of these tests needs a concurrent sibling?" in prose
    assert "It is a recommendation, not a decision to make for them" in prose
    assert "A stale screen, then a write" in prose
    assert "Two writers at once" in prose
    assert "Isolation" in prose and "Work happening behind the user" in prose
    # The worked example is the one the shape is hardest to see from prose alone.
    assert "without reloading, press **Sign** on the same document" in prose


def test_the_document_tells_a_plan_not_to_keep_a_copy_of_it():
    """The trap `cli/shaping.md` closes, in the same words: a plan's prose reaches every
    briefing, so a house document written into one is paid for on every step."""
    prose = " ".join(guide().split())
    assert "The project's conventions win" in prose
    assert "Never copy this document into a plan" in prose


# -- the door --------------------------------------------------------------------------------


def test_a_test_body_waits_on_the_format(gated_cli, step):
    out = gated_cli("test", "add", step, "A signature lands", "--text", "1. Sign it.", expect=1)
    assert "how a test is written here has not been read on this machine" in out
    assert "`dplanner test format`" in out
    assert data(gated_cli("test", "list", "Discovery", "--json"))["tests"] == []
    gated_cli("test", "format")
    gated_cli("test", "add", step, "A signature lands", "--text", "1. Sign it.")
    gated_cli("test", "set", "T100", "--title", "A signature lands on the document")


def test_setting_a_test_waits_on_it_too(gated_cli, step):
    """`test set` rewrites the body, so it is the same door — and it is the verb an agent
    reaches for when a test comes back wrong."""
    gated_cli("test", "format")
    gated_cli("test", "add", step, "A signature lands", "--text", "1. Sign it.")
    assert "has not been read" not in gated_cli("test", "show", "T100")


def test_reading_it_once_covers_every_project(gated_cli, step, workspace):
    """Unlike a topology the document is the build's, not the plan's: one reading stands."""
    gated_cli("test", "format")
    gated_cli("project", "create", "Other", "--dir", str(workspace / "other"))
    gated_cli("topology", "set", "Other", "--file", "-", stdin="Views are features.")
    gated_cli("topology", "show", "Other")
    gated_cli("step", "add", "Other", "Ship it")
    gated_cli("test", "add", "Ship it", "It ships", "--text", "1. Ship.")


def test_nothing_else_about_a_test_is_gated(gated_cli, step):
    """Only the verbs that write a body. Reading, filing, archiving and recording a result
    are never refused — an agent executing a roster never passes this door."""
    gated_cli("test", "format")
    gated_cli("test", "add", step, "A signature lands", "--text", "1. Sign it.")
    gated_cli("test", "list", "Discovery")
    gated_cli("test-category", "add", "Signing", "--project", "Discovery")
    gated_cli("test", "file", "T100", "--category", "Signing", "--project", "Discovery")
    gated_cli("test-run", "start", "--project", "Discovery", "--label", "First")
    gated_cli("test-run", "mark", "T100", "ok")
    gated_cli("test", "archive", "T100")


def test_a_first_test_on_a_new_step_is_a_title_and_is_not_gated(gated_cli, step):
    """`step add --test` names a test; it writes no body, so it asks for no format. The
    step's own door — the topology — is the one it stands behind."""
    gated_cli("step", "add", "Discovery", "Export the ledger", "--test", "The export opens")
    assert "The export opens" in gated_cli("test", "list", "Discovery")


def test_nothing_is_written_when_the_format_has_not_been_read(gated_cli, step, workspace):
    before = sorted(str(path) for path in (workspace / "discovery").rglob("*"))
    gated_cli("test", "add", step, "A signature lands", "--text", "1. Sign it.", expect=1)
    assert sorted(str(path) for path in (workspace / "discovery").rglob("*")) == before


def test_the_verb_prints_the_document_and_the_json_carries_it(gated_cli):
    assert "# How a test is written" in gated_cli("test", "format")
    assert data(gated_cli("test", "format", "--json"))["format"] == guide()


def test_the_skill_marks_the_verbs_that_read_it(gated_cli):
    """The `‡` is where an agent reads that writing a test costs a `test format` first."""
    skill = gated_cli("skill", "show")
    verbs = noun_verbs(skill)
    assert "add‡" in verbs["test"] and "set‡" in verbs["test"]
    assert "format" in verbs["test"] and "list" in verbs["test"]
    assert "‡ reads the house format first: `dplanner test format`" in skill
    # One thought, said once: the skill names the concern, the document holds the shape.
    assert "## Preconditions" not in skill


def test_the_document_never_reaches_a_briefing(gated_cli, step):
    """The guard the whole delivery rests on, and the reason it is printed rather than
    stored: an executing agent reads its briefing and pays for nothing it did not ask for."""
    gated_cli("describe", "set", step, "--file", "-", stdin="Sign it.")
    gated_cli("agent", "on", step)
    prompt = gated_cli("agent", "prompt", step)
    assert "How a test is written" not in prompt
