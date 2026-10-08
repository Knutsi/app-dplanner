"""What an agent CLI is to DPlanner: the **harness** contract a provider module fills.

Run Agent opens a terminal on a command — ``claude …``, ``codex …``, ``opencode …`` —
and that is all the launcher has to know about any of them. Everything else an agent
CLI can or cannot do is a fact about *that* CLI: whether a session can be named up
front and picked up again, which variables it sets in the shells it runs (so a nested
launch would become its child), and whether the tokens one session consumed can be read
back afterwards. Each provider module (``modules/agent_claude/``, ``agent_codex/``,
``agent_opencode/``) writes those facts down once in an :class:`AgentHarness`, from its
Qt-free half; the composition root assembles the tuple, and the launcher, the settings
page, the entry point's shell guard and the usage bookkeeping all read it. A fourth
agent is a fourth module and no ``if`` anywhere.

**Capabilities are derived from the record, never declared beside it.** A harness that
carries a ``resume`` template can resume; one whose ``command`` names ``{session}`` names
its session; one with a ``report`` reader counts tokens. :meth:`AgentHarness.capabilities`
words them, so a settings page can say *resumes · counts tokens* without a second list
that could disagree with the first.

**What a run cost is read back, never reported.** No agent CLI tells a launcher what a
session consumed; each keeps a record somewhere on disk — a transcript, a rollout file,
a database — and the harness's ``report`` knows where to look for *one* run, given the
facts the launch recorded (:class:`RunFacts`: the session it named, the directory the
agent worked in, when it started, and the sessions other runs have already claimed). The
answer is a :class:`RunReport`: the session the record belongs to — found by directory
and start time for a CLI that mints its own ids, which is also what makes such a run
resumable after the fact — and **one :class:`AgentUsage` per agent in the run's tree**,
the main agent and every subagent it spawned, each per model. ``None`` when the record
is not there or not readable. That is an honest answer and never an error: the formats
are the vendors' own, undocumented, and change between their releases, so a reader is
tolerant by construction. Reading is idempotent — the same record read twice gives the
same answer, larger while the run goes on — which is what lets anybody harvest a run at
any time (``modules/agent_usage/harvest.py``).

**A briefed run and a bare one are two invocations, and neither is derived from the
other.** ``command`` opens a session on a briefing and carries whatever mode a hand-over
wants; ``open_command`` is the same CLI with nothing to do — no opening line, no mode of
ours — which is what *Open Agent in Code* launches for the planning that happens before
there are steps to brief. Dropping Claude's ``{prompt}`` from the first would leave its
plan mode behind, and a launch that exists to open a *working* session must not open a
planning one, so each is written down.

**One meaning of the three counts across harnesses**, so two agents' numbers add on one
step (:class:`Tokens`): ``input`` is what was sent fresh — uncached input and cache
writes — ``cached`` what was read back from the prompt cache, and ``output`` everything
generated, reasoning included. Cached is its own number because it dwarfs the rest: an
agent re-reads its whole context on every request, and a session that sent half a million
fresh tokens read eleven million from cache. One "input" figure would be mostly that.

**A harness has a headless half too** (:class:`~dplanner.domain.headless.Headless`): the argv
for one unattended turn of each playbook stage, a reader for the CLI's JSON events and how
the turn ended. It is a second record rather than more templates here, because nothing about
it is a terminal's: the supervisor spawns the argv itself and never waits on a person.

**Installed is not usable.** A CLI on PATH may be broken or signed out, and a headless turn on
a dead login is a three-minute retry storm rather than an answer. So a harness says how to ask
whether it is signed in (:class:`SignIn`), and an :class:`AgentStatus` is the level a probe
reached — on PATH, a version, signed in. The probe talks to the CLI only through a
:data:`Shell`, never by path, which is the seam a probe *on another machine* will take.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # domain.headless reads Tokens from here.
    from dplanner.domain.headless import Headless


@dataclass(frozen=True)
class Tokens:
    """What was consumed on one model: fresh input, cache reads, output."""

    input: int = 0
    cached: int = 0
    output: int = 0

    def __add__(self, other: "Tokens") -> "Tokens":
        return Tokens(
            self.input + other.input, self.cached + other.cached, self.output + other.output
        )

    @property
    def worked(self) -> int:
        """Fresh input and output: what the work itself took, cache reads aside."""
        return self.input + self.output

    def __bool__(self) -> bool:
        return bool(self.input or self.cached or self.output)


def summed(counts: Iterable[Tokens]) -> Tokens:
    return sum(counts, Tokens())


def short_count(count: float) -> str:
    """``12.3k``, ``4.1M`` — a token count at a glance, the same on every surface."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(round(count))


@dataclass(frozen=True)
class AgentUsage:
    """One agent in a run's tree — the main one or a subagent — and what it consumed,
    per model."""

    id: str  # "main" for the agent the run launched; the vendor's id for a subagent.
    models: Mapping[str, Tokens]
    parent: str = ""  # The id of the agent that spawned it; "" for the main agent.
    session: str = ""  # The vendor's session or thread id, when it has one of its own.
    kind: str = ""  # What the vendor calls this agent ("Explore"), when it says.

    @property
    def tokens(self) -> Tokens:
        return summed(self.models.values())


@dataclass(frozen=True)
class RunFacts:
    """What the launcher knows about one run, handed to a harness's ``report``."""

    session: str  # The id the command named, "" when the harness names none.
    directory: str  # Where the agent worked — the wrapper's ``dir`` fact.
    launched: str  # ISO stamp of the launch.
    ended: str = ""  # ISO stamp of the exit, "" while live.
    # Sessions other runs already own: a CLI that mints its own ids is found by directory
    # and time, and two runs in one checkout must not both take the first session there.
    claimed: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RunReport:
    """What the CLI's own records say about one run."""

    session: str  # The id the CLI gave the session, "" when the record names none.
    agents: tuple[AgentUsage, ...] = ()
    # Which account the vendor ran it on, in words safe to share — a plan and an opaque
    # id, never an address: the ledger is committed with the plan.
    account: Mapping[str, str] = field(default_factory=dict)
    # Whether part of the tree could not be read (a subagent list, an index), so the
    # counts are a floor rather than the whole.
    partial: bool = False

    @property
    def tokens(self) -> Tokens:
        return summed(agent.tokens for agent in self.agents)


RunReader = Callable[[RunFacts], RunReport | None]

# Runs *this* CLI with these arguments: its exit code and what it said, stdout and stderr
# together (Codex says "Logged in" on stderr). Raises OSError, or TimeoutError when it does
# not answer in time. The harness never names its binary: the shell found it.
Shell = Callable[[Sequence[str]], tuple[int, str]]


@dataclass(frozen=True)
class SignedIn:
    ok: bool
    detail: str = ""  # "signed in (claude.ai, max)", "not signed in"


@dataclass(frozen=True)
class SignIn:
    """How a harness tells whether it can run here: a probe over its own CLI, and what a
    person types to sign in."""

    probe: Callable[[Shell], SignedIn]
    command: str  # "claude auth login"


class AgentLevel(IntEnum):
    """How far a status probe got, in the order it asks."""

    MISSING = 0  # Not on PATH.
    BROKEN = 1  # On PATH, but would not say its version.
    SIGNED_OUT = 2
    USABLE = 3


@dataclass(frozen=True)
class AgentStatus:
    """Whether one agent CLI can run here, and the words for it."""

    harness: str  # The harness id.
    label: str  # "Claude Code".
    level: AgentLevel
    version: str = ""
    detail: str = ""  # What the last level reached said: "not on PATH", "signed in (…)".

    @property
    def usable(self) -> bool:
        return self.level is AgentLevel.USABLE

    @property
    def reason(self) -> str:
        """Why it cannot run here — what a disabled entry says; "" when it can."""
        if self.usable:
            return ""
        if self.level is AgentLevel.MISSING:
            return f"{self.label} is not installed"
        if self.level is AgentLevel.BROKEN:
            return f"{self.label} is installed but broken: {self.detail}"
        return f"{self.label} is installed but not signed in"


@dataclass(frozen=True)
class AgentHarness:
    id: str  # "claude" — what a run records and a profile stores.
    label: str  # "Claude Code" — what a dropdown says.
    # The command the wrapper runs: {prompt} becomes the opening line (quoted), {session}
    # the run's session id and {run_dir} the run's directory (quoted).
    command: str
    # The same CLI opened with nothing to do — no briefing and none of the modes a briefed
    # run picks. {session} and {run_dir} substitute as in ``command``; "" for a CLI this
    # build cannot open bare, which greys *Open Agent in Code* with that as the reason.
    open_command: str = ""
    # How a run is picked up again, over its {session} — the one the launcher named, or
    # the one ``report`` found afterwards; "" when the CLI cannot resume by id.
    resume: str = ""
    # The command texts earlier versions shipped for this harness. The settings store the
    # picked text, so a machine that picked it before the command changed holds the old
    # one: read as this harness, it runs the current command and resumes.
    superseded: tuple[str, ...] = ()
    # What this CLI sets in every shell it runs — the names that say "you are inside a
    # session of mine". The launcher scrubs them so an agent it starts is a top-level
    # session; the entry point refuses to open a window under the first of them.
    shell_markers: tuple[str, ...] = ()
    # Whether a name is a marker beyond the fixed list — a prefix rule, for a CLI that
    # mints new ones between releases. Optional; the list alone is fine.
    is_marker: Callable[[str], bool] | None = None
    # Reads the CLI's own record of one run back — its session and what it consumed —
    # or None when there is none; absent for a CLI whose records this build cannot read.
    report: RunReader | None = None
    # The binary the command runs: what the checklist asks PATH for, and what the
    # settings page's detection and "not found" note name.
    binary: str = ""
    # The words in a command that start this CLI's session in plan mode — writing a plan
    # and waiting for a person to approve it; "" for a CLI with no such mode. Whether a
    # launch waits on somebody is read off the command it ran (``launcher.plans_first``),
    # so a profile edited to drop the words launches an agent that does not wait.
    plan_mode: str = ""
    # How it runs one unattended turn of a playbook stage; None for a CLI this build cannot
    # run headless.
    headless: "Headless | None" = None
    # How to ask whether it is signed in; None for a CLI this build cannot ask, which counts
    # as usable once it says its version.
    sign_in: SignIn | None = None
    # Where the CLI keeps its login and state under this process's environment
    # (``$CLAUDE_CONFIG_DIR``, ``$CODEX_HOME``…): with the id, the account a usage limit is
    # held on — two homes are two logins. None for one this build does not know.
    home: Callable[[], Path] | None = None

    def marks(self, name: str) -> bool:
        """Whether an environment variable of this name marks one of this CLI's shells."""
        if name in self.shell_markers:
            return True
        return self.is_marker is not None and self.is_marker(name)

    @property
    def names_session(self) -> bool:
        return "{session}" in self.command

    @property
    def resumes(self) -> bool:
        """Whether a run can be picked up again: by the id the launcher named, or by one
        the harness's ``report`` finds afterwards."""
        return bool(self.resume) and (self.names_session or self.report is not None)

    @property
    def counts_tokens(self) -> bool:
        return self.report is not None

    @property
    def runs_headless(self) -> bool:
        return self.headless is not None

    def capabilities(self) -> tuple[str, ...]:
        """The harness's abilities in words, for a settings page or a listing."""
        words = []
        if self.names_session:
            words.append("names its session")
        if self.resumes:
            words.append("resumes")
        if self.counts_tokens:
            words.append("counts tokens")
        if self.runs_headless:
            words.append("runs headless")
        return tuple(words)


def shell_markers(harnesses: tuple[AgentHarness, ...]) -> tuple[str, ...]:
    """What an agent CLI sets in every shell it runs: each harness's first marker — the
    one that names the CLI itself rather than a session detail. A missed agent here costs
    a guard, never a wrong answer: the window word refuses on it and ``status set`` holds
    an agent's done at review on it, and neither decides what runs."""
    return tuple(h.shell_markers[0] for h in harnesses if h.shell_markers)


def shell_marker(harnesses: tuple[AgentHarness, ...], env: Mapping[str, str]) -> str:
    """The marker set in ``env``, or "" when no agent's shell is around us. Set to nothing
    is not set."""
    return next((name for name in shell_markers(harnesses) if env.get(name)), "")


def is_session_marker(name: str, harnesses: tuple[AgentHarness, ...]) -> bool:
    """Whether an environment variable of this name says "inside an agent's session" —
    for any of the harnesses this build knows."""
    return any(harness.marks(name) for harness in harnesses)


def scrubbed_environment(
    env: Mapping[str, str], harnesses: tuple[AgentHarness, ...]
) -> dict[str, str]:
    """``env`` without any harness's session markers, so the agent starts a session of
    its own.

    Inside another agent's session markers a nested ``claude``
    is a child session — no transcript, ended with its parent — and every agent launched
    from a window that inherited them died with the agent that had started the window.
    """
    return {name: value for name, value in env.items() if not is_session_marker(name, harnesses)}


def harness_by_id(harnesses: tuple[AgentHarness, ...], harness_id: str) -> AgentHarness | None:
    return next((h for h in harnesses if h.id == harness_id), None)


def harness_for_command(harnesses: tuple[AgentHarness, ...], command: str) -> AgentHarness | None:
    """The harness a stored command text means: its current command, or one it shipped
    earlier — the settings page reads a stale text as the harness it was picked as."""
    text = command.strip()
    for harness in harnesses:
        if text == harness.command or text in harness.superseded:
            return harness
    return None
