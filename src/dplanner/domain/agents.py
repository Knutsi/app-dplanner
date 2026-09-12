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
facts the launcher recorded (:class:`RunFacts`: the session it named, the directory the
agent worked in, when it started). The answer is a :class:`RunReport`: the session the
record belongs to — found by directory and start time for a CLI that mints its own ids,
which is also what makes such a run resumable after the fact — and a :class:`Usage`, or
``None`` when the record is not there or not readable. That is an honest answer and
never an error: the formats are the vendors' own, undocumented, and change between their
releases, so a reader is tolerant by construction.

**One meaning of input and output across harnesses**, so two agents' numbers can be
added on one step: ``input`` is everything sent to the model — uncached, cache reads and
cache writes alike — and ``output`` everything it generated, reasoning included. The
vendor's own finer split goes under ``details`` in the vendor's words.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Usage:
    """What one agent session consumed, as the harness could read it back."""

    input: int
    output: int
    # The CLI's own finer breakdown, when it keeps one — ``cache_read``,
    # ``cache_creation``, ``reasoning`` — keyed by the harness's words. Already counted
    # in ``input`` or ``output``; a breakdown, never a third total.
    details: Mapping[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.input + self.output


@dataclass(frozen=True)
class RunFacts:
    """What the launcher knows about one run, handed to a harness's ``report``."""

    session: str  # The id the command named, "" when the harness names none.
    directory: str  # Where the agent worked — the wrapper's ``dir`` fact.
    launched: str  # ISO stamp of the launch.
    ended: str = ""  # ISO stamp of the exit, "" while live.


@dataclass(frozen=True)
class RunReport:
    """What the CLI's own records say about one run."""

    session: str  # The id the CLI gave the session, "" when the record names none.
    usage: Usage | None = None


RunReader = Callable[[RunFacts], RunReport | None]


@dataclass(frozen=True)
class AgentHarness:
    id: str  # "claude" — what a run records and a profile stores.
    label: str  # "Claude Code" — what a dropdown says.
    # The command the wrapper runs: {prompt} becomes the opening line (quoted), {session}
    # the run's session id and {run_dir} the run's directory (quoted).
    command: str
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
    # The binary the command runs, for the settings page's "not found" note.
    binary: str = ""

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

    def capabilities(self) -> tuple[str, ...]:
        """The harness's abilities in words, for a settings page or a listing."""
        words = []
        if self.names_session:
            words.append("names its session")
        if self.resumes:
            words.append("resumes")
        if self.counts_tokens:
            words.append("counts tokens")
        return tuple(words)


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
