"""Whether each agent CLI can run here: on PATH, then a version, then signed in.

"Installed" is not "usable" (``docs/research/2026-10-07-headless-agents/`` §9): a CLI on PATH
may be signed out, and a headless turn on a dead login is a retry storm rather than a
one-second answer. :func:`probe` walks the three levels in order and stops at the first it
cannot reach; anything the CLI does — not answering, not running — becomes words, never a
raise.

**Everything goes through a** :data:`~dplanner.domain.agents.Shell`. The probe asks ``which``
where the CLI is and hands the harness a shell bound to that path, so the harness never
names its binary (a Windows ``.cmd`` shim runs as found) and a probe *on another machine* is
a different ``which`` and ``shell_for``, nothing more.

**Asking is fresh; reading is cached.** :meth:`Availability.check` always probes — a person
pressing *Re-check* after signing in must see the truth — and keeps what it found.
:meth:`Availability.cached` and :meth:`Availability.why_not` never probe, so a state callback
on the UI thread may read them; a reading older than the TTL reads as not known, and
:meth:`Availability.refresh_stale` is the body a ``TaskRunner`` runs to fill it again.
"""

import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Sequence

from dplanner.domain.agents import AgentHarness, AgentLevel, AgentStatus, Shell

Which = Callable[[str], str | None]
ShellFor = Callable[[str], Shell]

PROBE_TIMEOUT_S = 10.0
TTL_S = 60.0

_VERSION = re.compile(r"\d+(?:\.\d+)+")


def subprocess_shell(path: str) -> Shell:
    """A shell that runs the CLI at ``path``, stdout and stderr together, never waiting
    longer than :data:`PROBE_TIMEOUT_S` and never reading a keyboard."""

    def run(arguments: Sequence[str]) -> tuple[int, str]:
        try:
            done = subprocess.run(
                [path, *arguments],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as expired:
            raise TimeoutError(f"no answer in {PROBE_TIMEOUT_S:g} s") from expired
        return done.returncode, done.stdout + done.stderr

    return run


def version_of(said: str) -> str:
    """``2.1.280`` from "2.1.280 (Claude Code)", ``0.160.0`` from "codex-cli 0.160.0"."""
    first = next((line.strip() for line in said.splitlines() if line.strip()), "")
    found = _VERSION.search(first)
    return found.group(0) if found else first


def _failure(error: Exception) -> str:
    return str(error) if isinstance(error, TimeoutError) else type(error).__name__


def probe(
    harness: AgentHarness, which: Which = shutil.which, shell_for: ShellFor = subprocess_shell
) -> AgentStatus:
    def status(level: AgentLevel, detail: str, version: str = "") -> AgentStatus:
        return AgentStatus(harness.id, harness.label, level, version, detail)

    path = which(harness.binary) if harness.binary else None
    if path is None:
        return status(AgentLevel.MISSING, "not on PATH")
    shell = shell_for(path)
    try:
        code, said = shell(("--version",))
    except (OSError, TimeoutError) as error:
        return status(AgentLevel.BROKEN, f"`--version` failed: {_failure(error)}")
    version = version_of(said) if code == 0 else ""
    if not version:
        return status(AgentLevel.BROKEN, "would not say its version")
    if harness.sign_in is None:
        return status(AgentLevel.USABLE, "sign-in not checked", version)
    try:
        signed = harness.sign_in.probe(shell)
    except (OSError, TimeoutError) as error:
        return status(AgentLevel.SIGNED_OUT, f"sign-in check failed: {_failure(error)}", version)
    level = AgentLevel.USABLE if signed.ok else AgentLevel.SIGNED_OUT
    return status(level, signed.detail, version)


class Availability:
    """Every harness's last status, kept briefly."""

    def __init__(
        self,
        harnesses: Sequence[AgentHarness],
        *,
        which: Which = shutil.which,
        shell_for: ShellFor = subprocess_shell,
        clock: Callable[[], float] = time.monotonic,
        ttl_s: float = TTL_S,
    ) -> None:
        self._harnesses = {harness.id: harness for harness in harnesses}
        self._which = which
        self._shell_for = shell_for
        self._clock = clock
        self._ttl_s = ttl_s
        self._lock = threading.Lock()
        self._read: dict[str, tuple[float, AgentStatus]] = {}

    def check(self, harness_id: str) -> AgentStatus:
        """Probe it now and keep the answer. Off the UI thread: this runs the CLI."""
        found = probe(self._harnesses[harness_id], self._which, self._shell_for)
        with self._lock:
            self._read[harness_id] = (self._clock(), found)
        return found

    def cached(self, harness_id: str) -> AgentStatus | None:
        """The last answer if it is fresh enough, else None. Never probes."""
        with self._lock:
            kept = self._read.get(harness_id)
        if kept is None or self._clock() - kept[0] > self._ttl_s:
            return None
        return kept[1]

    def refresh_stale(self) -> None:
        """Probe every harness whose answer is missing or old — a ``TaskRunner`` body."""
        for harness_id in self._harnesses:
            if self.cached(harness_id) is None:
                self.check(harness_id)

    def why_not(self, harness_ids: Iterable[str]) -> str:
        """Why these agents cannot all run here — "" when they can. Never probes.

        The question a playbook asks of its roles' agents, so Run Playbook can disable an
        entry and say why; an answer not read yet says so rather than guessing.
        """
        for harness_id in dict.fromkeys(harness_ids):
            harness = self._harnesses.get(harness_id)
            if harness is None:
                return f"no agent CLI named {harness_id!r} in this build"
            status = self.cached(harness_id)
            if status is None:
                return f"checking {harness.label}…"
            if status.usable:
                continue
            if status.level is AgentLevel.SIGNED_OUT and harness.sign_in is not None:
                return f"{status.reason} — `{harness.sign_in.command}`"
            return status.reason
        return ""
