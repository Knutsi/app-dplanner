"""Whether an agent CLI can run here: the three levels, each harness's sign-in probe over
what the real CLIs said (2026-10-07), and the cache a playbook reads.

No CLI is ever run: ``which`` and the shell are fakes, and the suite's spawn guard is the
backstop.
"""

import json
import sys

import pytest

from dplanner.domain.agents import AgentHarness, AgentLevel, SignedIn, SignIn
from dplanner.modules import agent_harnesses
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.agent_codex import harness as codex
from dplanner.modules.agent_launch import availability
from dplanner.modules.agent_launch.availability import Availability, probe, version_of
from dplanner.modules.agent_opencode import harness as opencode

CLAUDE_SIGNED_IN = json.dumps(
    {"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max"}
)
OPENCODE_NO_CREDENTIALS = (
    "\x1b[0m\n┌  Credentials \x1b[90m~/.local/share/opencode/auth.json\n│\n└  0 credentials\n"
)


def answering(answers, calls=None):
    """A shell factory: each argv's words joined is a key of ``answers`` — an
    ``(exit code, output)`` or an exception to raise."""

    def shell_for(path):
        def run(arguments):
            if calls is not None:
                calls.append((path, tuple(arguments)))
            answer = answers[" ".join(arguments)]
            if isinstance(answer, Exception):
                raise answer
            return answer

        return run

    return shell_for


def on_path(name):
    return f"/usr/bin/{name}"


def fake(sign_in=None):
    return AgentHarness("fake", "Fake", "fake {prompt}", binary="fake", sign_in=sign_in)


SIGNED = SignIn(probe=lambda shell: SignedIn(shell(("whoami",))[0] == 0, "it said"), command="x")


# -- the levels --------------------------------------------------------------------------


def test_not_on_path_is_missing_and_runs_nothing():
    calls: list[tuple[str, tuple[str, ...]]] = []
    status = probe(fake(SIGNED), lambda _name: None, answering({}, calls))
    assert status.level is AgentLevel.MISSING and calls == []
    assert status.reason == "Fake is not installed"


def test_each_level_is_reached_in_turn_and_the_shell_is_bound_to_the_found_path():
    calls: list[tuple[str, tuple[str, ...]]] = []
    shell_for = answering({"--version": (0, "fake 1.2.3\n"), "whoami": (0, "")}, calls)
    status = probe(fake(SIGNED), on_path, shell_for)
    assert status.usable and status.version == "1.2.3" and status.detail == "it said"
    assert calls == [("/usr/bin/fake", ("--version",)), ("/usr/bin/fake", ("whoami",))]


@pytest.mark.parametrize(
    "answer",
    [(1, "boom"), (0, ""), OSError("exec format error"), TimeoutError("no answer in 10 s")],
)
def test_a_cli_that_will_not_say_its_version_is_broken(answer):
    status = probe(fake(SIGNED), on_path, answering({"--version": answer}))
    assert status.level is AgentLevel.BROKEN and status.detail
    assert status.reason.startswith("Fake is installed but broken")


def test_signed_out_and_a_sign_in_check_that_hangs_are_both_signed_out():
    out = probe(fake(SIGNED), on_path, answering({"--version": (0, "1.0"), "whoami": (1, "")}))
    hung = probe(
        fake(SIGNED),
        on_path,
        answering({"--version": (0, "1.0"), "whoami": TimeoutError("no answer in 10 s")}),
    )
    assert out.level is hung.level is AgentLevel.SIGNED_OUT
    assert "no answer in 10 s" in hung.detail


def test_a_harness_that_cannot_be_asked_is_usable_once_it_says_its_version():
    status = probe(fake(), on_path, answering({"--version": (0, "1.0")}))
    assert status.usable and status.detail == "sign-in not checked"


@pytest.mark.parametrize(
    ("said", "version"),
    [
        ("2.1.280 (Claude Code)\n", "2.1.280"),
        ("codex-cli 0.160.0\n", "0.160.0"),
        ("1.18.34\n", "1.18.34"),
        ("nightly\n", "nightly"),
    ],
)
def test_the_version_is_the_first_dotted_number_else_the_line(said, version):
    assert version_of(said) == version


def test_every_shipped_harness_says_how_to_ask_whether_it_is_signed_in():
    assert all(harness.sign_in is not None for harness in agent_harnesses())


# -- each harness's sign-in probe --------------------------------------------------------


def shell(answers):
    return answering(answers)("/usr/bin/cli")


def test_claude_reads_logged_in_from_its_json():
    assert claude.signed_in(shell({"auth status": (0, CLAUDE_SIGNED_IN)})) == SignedIn(
        True, "signed in (claude.ai, max)"
    )
    out = claude.signed_in(shell({"auth status": (1, json.dumps({"loggedIn": False}))}))
    garbled = claude.signed_in(shell({"auth status": (0, "Error: something")}))
    assert not out.ok and not garbled.ok and "JSON" in garbled.detail


def test_codex_is_signed_in_when_its_status_says_logged_in():
    assert codex.signed_in(shell({"login status": (0, "Logged in using ChatGPT\n")})) == SignedIn(
        True, "logged in using ChatGPT"
    )
    assert not codex.signed_in(shell({"login status": (1, "Not logged in\n")})).ok


def test_opencode_is_signed_in_with_a_credential_or_a_built_in_model():
    one = opencode.signed_in(shell({"auth list": (0, "└  1 credential\n")}))
    built_in = opencode.signed_in(
        shell(
            {
                "auth list": (0, OPENCODE_NO_CREDENTIALS),
                "models opencode": (0, "opencode/big-pickle\nopencode/exo-free\n"),
            }
        )
    )
    nothing = opencode.signed_in(
        shell({"auth list": (0, OPENCODE_NO_CREDENTIALS), "models opencode": (0, "")})
    )
    assert one == SignedIn(True, "1 credential")
    assert built_in.ok and "built-in" in built_in.detail
    assert not nothing.ok


# -- the cache ---------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def cache(calls, *, signed=True, clock=None):
    return Availability(
        (fake(SIGNED),),
        which=on_path,
        shell_for=answering({"--version": (0, "1.0"), "whoami": (0 if signed else 1, "")}, calls),
        clock=clock or Clock(),
        ttl_s=60,
    )


def test_reading_never_probes_and_an_old_reading_is_not_known():
    calls: list[tuple[str, tuple[str, ...]]] = []
    clock = Clock()
    known = cache(calls, clock=clock)
    assert known.cached("fake") is None and calls == []
    assert known.check("fake").usable
    asked = len(calls)
    clock.now = 59
    assert known.cached("fake") is not None
    clock.now = 61
    assert known.cached("fake") is None and len(calls) == asked


def test_checking_always_probes_and_refresh_probes_only_what_is_stale():
    calls: list[tuple[str, tuple[str, ...]]] = []
    clock = Clock()
    known = cache(calls, clock=clock)
    known.check("fake")
    known.check("fake")
    assert len(calls) == 4
    known.refresh_stale()
    assert len(calls) == 4
    clock.now = 61
    known.refresh_stale()
    assert len(calls) == 6


def test_why_not_is_the_playbooks_question_and_never_probes():
    calls: list[tuple[str, tuple[str, ...]]] = []
    usable, signed_out = cache(calls), cache(calls, signed=False)
    assert usable.why_not(["fake"]) == "checking Fake…"
    assert calls == []
    usable.check("fake")
    signed_out.check("fake")
    assert usable.why_not(["fake", "fake"]) == ""
    assert signed_out.why_not(["fake"]) == "Fake is installed but not signed in — `x`"
    assert "nobody" in usable.why_not(["fake", "nobody"])


def test_the_default_shell_merges_stderr_and_gives_up_on_a_cli_that_hangs(monkeypatch):
    said = availability.subprocess_shell(sys.executable)(
        ("-c", "import sys; print('out'); print('err', file=sys.stderr)")
    )
    assert said == (0, "out\nerr\n")
    monkeypatch.setattr(availability, "PROBE_TIMEOUT_S", 0.2)
    with pytest.raises(TimeoutError):
        availability.subprocess_shell(sys.executable)(("-c", "import time; time.sleep(5)"))
