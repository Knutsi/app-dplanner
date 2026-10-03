"""A playbook: a template of stages wrapped around one plan step. Research spike, not product.

The shape it tests:

- The plan step is the `work` stage, done by the `implementer` role. Every other stage is a
  gate. A gate that answers *changes* sends the work back to `work` (or to `on_changes`), so
  the stage graph is a star around the work rather than a free graph.
- The ledger is the only truth. `due()` is level-triggered: given the playbook, the ledger and
  the time, it says what happens next, exactly as `rounds.due_turns` does for a review today.
  Processes are disposable; nothing here remembers anything a restart would lose.
- A failure is not a verdict. `error` runs are retried, parked or handed to a person, and
  never spend a review round.

Everything is pure; `simulate.py` drives it with scripted outcomes.
"""

from __future__ import annotations

import dataclasses
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import tomllib

Kind = Literal["work", "criteria", "checklist", "judgement", "person"]
Driver = Literal["engine", "lead"]
VerdictKind = Literal["pass", "changes"]
Source = Literal["agent", "dplanner", "person", "lead"]
FailureClass = Literal["retry", "park", "person", "abandon"]

KNOWN_AGENTS = frozenset({"claude", "codex", "opencode"})
DEFAULT_ROUNDS = 2
MAX_ROUNDS = 5
MAX_ERRORS = 3  # failed runs of one stage in a row before a person is asked
CACHE_TTL_S = 3600.0  # subscription default; an API-key worker sets the 1 h TTL explicitly
WARM_CONTEXT_LIMIT = 100_000
STALL_S = 300.0  # no stream event for this long is a hang (Symphony's default)
BACKOFF_S = (30.0, 120.0, 600.0)


# ── the definition ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Role:
    name: str
    agent: str | None = None  # a harness id; None for a person
    model: str | None = None
    person: bool = False
    fresh: bool = True  # a gate role always starts a new session; see evidence.md

    @property
    def account(self) -> str:
        return "person" if self.person else (self.agent or "?")


@dataclass(frozen=True)
class Stage:
    id: str
    kind: Kind
    by: str  # a role name
    rounds: int = DEFAULT_ROUNDS  # how many times this gate may see the work; changes on the last escalates
    run: tuple[str, ...] = ()  # criteria: commands whose exit codes decide
    items: tuple[str, ...] = ()  # checklist: yes/no questions
    lenses: tuple[str, ...] = ()  # judgement: what to look at
    when: tuple[str, ...] = ()  # only when the diff touches one of these globs
    on_changes: str = "work"


@dataclass(frozen=True)
class Playbook:
    name: str
    stages: tuple[Stage, ...]  # stages[0] is always `work`
    roles: dict[str, Role]
    driver: Driver = "engine"
    budget_usd: float | None = None
    source: str = ""

    @property
    def gates(self) -> tuple[Stage, ...]:
        return self.stages[1:]

    def stage(self, stage_id: str) -> Stage:
        return next(s for s in self.stages if s.id == stage_id)

    def role_of(self, stage: Stage) -> Role:
        return self.roles[stage.by]


def load(path: Path) -> Playbook:
    raw = tomllib.loads(path.read_text())
    if "extends" in raw:
        base = load(path.parent / raw["extends"])
        roles = dict(base.roles)
        roles.update(_roles(raw.get("roles", {})))
        stages = base.stages if "stage" not in raw else _stages(raw)
        return dataclasses.replace(
            base,
            name=raw.get("name", base.name),
            driver=raw.get("driver", base.driver),
            budget_usd=raw.get("budget_usd", base.budget_usd),
            roles=roles,
            stages=stages,
            source=path.name,
        )
    return Playbook(
        name=raw["name"],
        driver=raw.get("driver", "engine"),
        budget_usd=raw.get("budget_usd"),
        roles=_roles(raw.get("roles", {})),
        stages=_stages(raw),
        source=path.name,
    )


def _roles(raw: dict[str, dict[str, object]]) -> dict[str, Role]:
    roles = {"person": Role("person", person=True)}
    for name, spec in raw.items():
        roles[name] = Role(
            name,
            agent=_opt_str(spec.get("agent")),
            model=_opt_str(spec.get("model")),
            person=bool(spec.get("person", False)),
            fresh=bool(spec.get("fresh", name != "implementer")),
        )
    return roles


def _stages(raw: dict[str, object]) -> tuple[Stage, ...]:
    work = Stage("work", "work", by="implementer")
    gates = []
    for spec in raw.get("stage", []):  # type: ignore[attr-defined]
        kind = spec["kind"]
        gates.append(
            Stage(
                id=spec["id"],
                kind=kind,
                by=spec.get("by", "dplanner" if kind == "criteria" else "person" if kind == "person" else "reviewer"),
                rounds=int(spec.get("rounds", DEFAULT_ROUNDS)),
                run=tuple(spec.get("run", ())),
                items=tuple(spec.get("items", ())),
                lenses=tuple(spec.get("lenses", ())),
                when=tuple(spec.get("when", ())),
                on_changes=spec.get("on_changes", "work"),
            )
        )
    return (work, *gates)


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)


# ── the static check ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Problems:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def check(pb: Playbook) -> Problems:
    errors: list[str] = []
    warnings: list[str] = []
    ids = [s.id for s in pb.stages]
    if len(set(ids)) != len(ids):
        errors.append("two stages share an id")
    if pb.budget_usd is None:
        errors.append("no budget_usd: a playbook nobody watches needs a ceiling")
    if "implementer" not in pb.roles:
        errors.append("no implementer role: who does the work?")
    if pb.driver == "lead" and "lead" not in pb.roles:
        errors.append("driver = lead, but there is no lead role to run it")
    implementer = pb.roles.get("implementer")
    seen_person = False
    for index, stage in enumerate(pb.gates, start=1):
        where = f"stage {stage.id!r}"
        if seen_person:
            errors.append(f"{where} comes after a person's approval: it would change work the person never saw")
        if stage.kind == "person":
            seen_person = True
        if stage.kind == "criteria":
            if not stage.run:
                errors.append(f"{where} is a criteria gate with nothing to run")
        elif stage.by not in pb.roles:
            errors.append(f"{where} is done by {stage.by!r}, which is not a role")
        else:
            role = pb.roles[stage.by]
            if not role.person and role.agent not in KNOWN_AGENTS:
                errors.append(f"{where}: unknown agent {role.agent!r} (known: {', '.join(sorted(KNOWN_AGENTS))})")
            if stage.kind == "person" and not role.person:
                errors.append(f"{where} is a person gate given to an agent role")
            if (
                stage.kind == "judgement"
                and implementer is not None
                and role.agent == implementer.agent
                and role.model == implementer.model
            ):
                warnings.append(
                    f"{where}: same agent and model as the implementer, so it only gains a fresh context"
                    " — fine for a cheap preset, weak for a careful one"
                )
        if not 1 <= stage.rounds <= MAX_ROUNDS:
            errors.append(f"{where}: rounds = {stage.rounds}; a loop must be bounded at 1–{MAX_ROUNDS}")
        if stage.on_changes not in ids[:index]:
            errors.append(f"{where}: on_changes = {stage.on_changes!r} must name an earlier stage")
        if stage.kind == "checklist" and not stage.items:
            errors.append(f"{where} is a checklist with no items")
    if not pb.gates:
        warnings.append("no gates: this is a plain agent step")
    elif all(s.kind in ("judgement", "checklist") for s in pb.gates):
        warnings.append("no criteria gate: nothing runs the tests, so every gate is opinion")
    return Problems(tuple(errors), tuple(warnings))


# ── the ledger ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Run:
    id: str
    stage: str
    role: str
    mode: str  # fresh | resume | nudge
    started: float
    sha_in: str
    ended: float | None = None
    outcome: str = "live"  # live | ok | retry | park | person | abandon | lost
    detail: str = ""
    session: str = ""
    tokens: int = 0
    last_event: float = 0.0
    sha_out: str = ""


@dataclass(frozen=True)
class Verdict:
    stage: str
    sha: str
    verdict: VerdictKind
    run: str
    at: float
    source: Source
    findings: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class Ledger:
    head: str = "base"
    runs: tuple[Run, ...] = ()
    verdicts: tuple[Verdict, ...] = ()
    parked: tuple[tuple[str, float], ...] = ()  # (account, until)
    dead: frozenset[str] = frozenset()  # accounts whose login is gone
    log: tuple[str, ...] = ()  # what the engine refused or noticed, for people to read
    touched: tuple[str, ...] = ()  # paths the diff touches; `when` reads these
    resets: tuple[tuple[str, float], ...] = ()  # (stage, at): a person said "try that stage again"

    def live(self) -> Run | None:
        return next((r for r in reversed(self.runs) if r.ended is None), None)

    def runs_of(self, stage: str) -> list[Run]:
        return [r for r in self.runs if r.stage == stage]

    def verdicts_of(self, stage: str) -> list[Verdict]:
        return [v for v in self.verdicts if v.stage == stage]

    def parked_until(self, account: str) -> float:
        return max((until for acct, until in self.parked if acct == account), default=0.0)


# ── intake: what the engine accepts into the ledger ───────────────────────────────────


def accept(pb: Playbook, ledger: Ledger, verdict: Verdict) -> Ledger:
    """Take a verdict in, or refuse it with a note. Refusals are the fencing rules."""
    stage = pb.stage(verdict.stage)
    live = ledger.live()
    if stage.kind == "criteria" and verdict.source != "dplanner":
        return _note(
            ledger,
            f"refused a {verdict.verdict} on {stage.id!r} from the {verdict.source}: "
            "a criteria gate is recorded by DPlanner from exit codes, never reported",
        )
    if verdict.source in ("agent", "lead") and (live is None or live.id != verdict.run):
        return _note(
            ledger,
            f"refused {verdict.run}'s {verdict.verdict} on {stage.id!r}: "
            "that run no longer holds the stage (killed or superseded)",
        )
    if verdict.sha != ledger.head:
        return _note(
            ledger,
            f"ignored a {verdict.verdict} on {stage.id!r} for {verdict.sha}: "
            f"the head is {ledger.head} now, so it judged stale work",
        )
    return dataclasses.replace(ledger, verdicts=(*ledger.verdicts, verdict))


def _note(ledger: Ledger, text: str) -> Ledger:
    return dataclasses.replace(ledger, log=(*ledger.log, text))


# ── what is due ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Launch:
    stage: str
    role: str
    mode: str  # fresh | resume | nudge
    reason: str
    round: int = 0


@dataclass(frozen=True)
class Wait:
    reason: str
    until: float | None = None


@dataclass(frozen=True)
class NeedsPerson:
    kind: str  # approve | login | decide | budget | stuck
    reason: str
    stage: str = ""


@dataclass(frozen=True)
class Reconcile:
    run: str
    reason: str


@dataclass(frozen=True)
class Done:
    reason: str = "every gate passed"


@dataclass(frozen=True)
class Escalate:
    stage: str
    reason: str


Decision = Launch | Wait | NeedsPerson | Reconcile | Done | Escalate


@dataclass(frozen=True)
class Facts:
    """What the engine knows that is not in the ledger: the time, and which runs are alive."""

    now: float
    alive: frozenset[str] = frozenset()
    spent_usd: float = 0.0
    events: dict[str, float] = field(default_factory=dict)  # run id → time of its last stream event


def due(pb: Playbook, ledger: Ledger, facts: Facts) -> Decision:
    live = ledger.live()
    if live is not None:
        if live.id not in facts.alive:
            return Reconcile(live.id, "no process holds this run any more (host restarted, or it was killed)")
        last = facts.events.get(live.id, live.started)
        if facts.now - last > STALL_S:
            return Reconcile(live.id, f"no stream event for {int(facts.now - last)} s: a hang")
        return Wait(f"{live.stage} is running ({live.id})")

    work = pb.stages[0]
    if not any(r.outcome == "ok" for r in ledger.runs_of("work")):
        return _launch_or_hold(pb, ledger, facts, work, "fresh", "the work has not been done", 0)

    fix = _owed_fix(pb, ledger)
    if fix is not None:
        verdict, target = fix
        prior = _last_ok(ledger, target.id)
        mode = _warmth(prior, facts.now) if target.id == "work" else "fresh"
        n = sum(1 for v in ledger.verdicts_of(verdict.stage) if v.verdict == "changes")
        return _launch_or_hold(pb, ledger, facts, target, mode, f"round {n} findings from {verdict.stage!r}", n)

    for stage in pb.gates:
        if stage.when and not _touches(ledger.touched, stage.when):
            continue
        if _passed(stage, ledger):
            continue
        if stage.kind == "person":
            return NeedsPerson("approve", "every agent gate has passed; a person approves the work", stage.id)
        changes = [v for v in ledger.verdicts_of(stage.id) if v.verdict == "changes"]
        if changes and len(changes) >= stage.rounds:
            return Escalate(stage.id, f"{len(changes)} of {stage.rounds} rounds used and still changes requested")
        return _launch_or_hold(pb, ledger, facts, stage, "fresh", f"{stage.kind} gate", len(changes) + 1)
    return Done()


def _launch_or_hold(
    pb: Playbook, ledger: Ledger, facts: Facts, stage: Stage, mode: str, reason: str, round_: int
) -> Decision:
    """Every launch goes through here, so the failure rules apply to every stage alike."""
    role = pb.role_of(stage) if stage.kind != "criteria" else Role("dplanner")
    if role.account in ledger.dead:
        return NeedsPerson(
            "login",
            f"{role.account} is logged out or its subscription lapsed; every stage on it waits (others go on)",
            stage.id,
        )
    until = ledger.parked_until(role.account)
    if until > facts.now:
        return Wait(f"{role.account} is out of quota; parked until its reset", until)
    since = _since_last_verdict_or_fix(ledger, stage.id)
    failures = [r for r in since if r.outcome in ("retry", "lost", "park")]
    if any(r.outcome in ("person", "abandon") for r in since[-1:]):
        last = since[-1]
        return NeedsPerson("stuck", f"{stage.id}: {last.detail}", stage.id)
    if len(failures) >= MAX_ERRORS:
        return NeedsPerson(
            "stuck", f"{stage.id} failed {len(failures)} times in a row: {failures[-1].detail}", stage.id
        )
    if failures and failures[-1].ended is not None:
        wait = BACKOFF_S[min(len(failures), len(BACKOFF_S)) - 1]
        if facts.now < failures[-1].ended + wait:
            return Wait(
                f"{stage.id} failed ({failures[-1].detail}); retrying after a backoff", failures[-1].ended + wait
            )
    if since and since[-1].outcome == "ok" and since[-1].sha_in != ledger.head:
        return Launch(stage.id, stage.by, "fresh", "the head moved while it ran: judge the new work", round_)
    if since and since[-1].outcome == "ok" and stage.kind != "work":
        # it ran to the end and gave no verdict: nudge it once, then ask a person
        if since[-1].mode == "nudge":
            return NeedsPerson("stuck", f"{stage.id} finished twice without a verdict", stage.id)
        return Launch(stage.id, stage.by, "nudge", "finished without a verdict: asked for the verdict only", round_)
    if stage.kind == "criteria":
        return Launch(stage.id, "dplanner", mode, reason, round_)
    # only a launch that spends is held by the budget: a person's approval or `done` never is
    if pb.budget_usd is not None and facts.spent_usd >= pb.budget_usd:
        return NeedsPerson(
            "budget", f"spent ${facts.spent_usd:.2f} of ${pb.budget_usd:.2f}; raise it or stop", stage.id
        )
    if pb.budget_usd is not None and facts.spent_usd >= 0.8 * pb.budget_usd:
        reason += f" (warning: ${facts.spent_usd:.2f} of ${pb.budget_usd:.2f} spent)"
    return Launch(stage.id, stage.by, mode, reason, round_)


def _since_last_verdict_or_fix(ledger: Ledger, stage_id: str) -> list[Run]:
    """The stage's runs since it last produced a verdict (or, for work, since the last fix asked)."""
    marks = [v.at for v in ledger.verdicts if v.stage == stage_id or stage_id == "work"]
    marks += [at for stage, at in ledger.resets if stage == stage_id]
    after = max(marks, default=-1.0)
    return [r for r in ledger.runs_of(stage_id) if r.started > after]


def _owed_fix(pb: Playbook, ledger: Ledger) -> tuple[Verdict, Stage] | None:
    """The latest `changes` verdict whose fix has not yet run to completion."""
    for verdict in reversed(ledger.verdicts):
        if verdict.verdict != "changes":
            continue
        target = pb.stage(pb.stage(verdict.stage).on_changes)
        fixed = any(r.outcome == "ok" and r.started >= verdict.at for r in ledger.runs_of(target.id))
        if fixed:
            return None
        rounds_used = sum(1 for v in ledger.verdicts_of(verdict.stage) if v.verdict == "changes")
        if rounds_used >= pb.stage(verdict.stage).rounds:
            return None  # the gate's last round asked for changes: that is an escalation, not a fix
        return verdict, target
    return None


def _passed(stage: Stage, ledger: Ledger) -> bool:
    """Criteria are re-run on every new head; an agent's or person's pass stands once given."""
    verdicts = ledger.verdicts_of(stage.id)
    if not verdicts or verdicts[-1].verdict != "pass":
        return False
    return stage.kind != "criteria" or verdicts[-1].sha == ledger.head


def _last_ok(ledger: Ledger, stage_id: str) -> Run | None:
    return next((r for r in reversed(ledger.runs_of(stage_id)) if r.outcome == "ok"), None)


def _warmth(prior: Run | None, now: float) -> str:
    """Resume the implementer while its prompt cache is warm and its context is small; else fresh."""
    if prior is None or not prior.session:
        return "fresh"
    if now - prior.last_event > CACHE_TTL_S or prior.tokens > WARM_CONTEXT_LIMIT:
        return "fresh"
    return "resume"


def _touches(paths: tuple[str, ...], globs: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(p, g) for p in paths for g in globs)


def round_label(pb: Playbook, ledger: Ledger, decision: Decision) -> str:
    """The canvas ring's text: where the step stands, in a few words."""
    match decision:
        case Launch(stage=stage_id, round=n) if stage_id != "work" and n:
            s = pb.stage(stage_id)
            return f"{stage_id.capitalize()} {n}/{s.rounds}" if s.kind != "criteria" else stage_id.capitalize()
        case Launch(stage="work", round=n) if n:
            return f"Fixing (round {n})"
        case Launch():
            return "Working"
        case Wait(until=until) if until is not None:
            return "Parked" if "quota" in decision.reason else "Retrying"
        case Wait():
            return "Running"
        case NeedsPerson(kind="approve"):
            return "Waits for you"
        case NeedsPerson():
            return "Needs you"
        case Reconcile():
            return "Recovering"
        case Escalate():
            return "Escalated"
        case Done():
            return "Done"


# ── one definition, two drivers: the lead agent's briefing ─────────────────────────────


def lead_briefing(pb: Playbook) -> str:
    """The same playbook, rendered as instructions for a lead agent that drives it itself."""
    lines = [
        f'You are the lead for one plan step, running the playbook "{pb.name}".',
        "You do not write code. You start the other agents, read what they report, and decide",
        "what runs next, following the stages below exactly.",
        "",
        "Rules that DPlanner enforces whatever you say:",
        "- Report every verdict with `dplanner review post|approve --run <your run id>`. A verdict",
        "  from a run that no longer holds the stage is refused.",
        "- Criteria gates are run and recorded by DPlanner (`dplanner playbook check-gate <stage>`);",
        "  your report of a test result is not accepted as one.",
        f"- Budget: ${pb.budget_usd} for the whole step. Check `dplanner playbook spend` before each",
        "  launch; at the limit, stop and run `dplanner review escalate`.",
        "- An agent that fails to start, times out or hits a quota is not a round. Never count it.",
        "",
        "Roles (start each as its own headless process; never reuse a reviewer's session):",
    ]
    for role in pb.roles.values():
        if role.name in ("person", "lead"):
            continue
        how = "a person" if role.person else f"`{role.agent}`" + (f" ({role.model})" if role.model else "")
        lines.append(f"- {role.name}: {how}{'' if role.person else ', fresh session' if role.fresh else ''}")
    lines += ["", "Stages, in order:", "1. work — the implementer does the step, then reports ready."]
    for n, stage in enumerate(pb.gates, start=2):
        lines.append(f"{n}. {_describe(stage)}")
    lines += [
        "",
        "When a gate asks for changes, send its findings back to the implementer (resume its session",
        "if it ended under an hour ago, else start it fresh with the findings), then run that gate",
        "again. Earlier criteria gates run again on the new commit; earlier agent passes stand.",
        "When a gate's rounds are used up and it still asks for changes, escalate. Never approve",
        "on a gate's behalf, and never approve for the person.",
    ]
    return "\n".join(lines)


def _describe(stage: Stage) -> str:
    when = f" Only when the diff touches {', '.join(stage.when)}." if stage.when else ""
    match stage.kind:
        case "criteria":
            return f"{stage.id} — DPlanner runs: {'; '.join(stage.run)}. Any failure is changes.{when}"
        case "checklist":
            items = "; ".join(stage.items)
            return f"{stage.id} — {stage.by} answers yes/no, with evidence, to: {items}.{when}"
        case "judgement":
            lenses = ", ".join(stage.lenses) or "correctness"
            rounds = f"{stage.rounds} round{'s' if stage.rounds != 1 else ''}"
            return f"{stage.id} — {stage.by} reviews ({lenses}), up to {rounds}.{when}"
        case "person":
            return f"{stage.id} — wait for a person's approval. Do nothing until it arrives."
    return stage.id


# ── the stage graph, drawn ────────────────────────────────────────────────────────────


def diagram(pb: Playbook) -> str:
    """ASCII: the pipeline, and under it every gate's way back to the work."""
    boxes = [f"[{s.id}]" for s in pb.stages] + ["(done)"]
    top = " → ".join(boxes)
    lines = [top]
    for stage in pb.gates:
        if stage.kind == "criteria":
            back = "fail"
        elif stage.kind == "person":
            back = "changes"
        else:
            back = f"changes ×{stage.rounds}"
        cond = f"   (only if {', '.join(stage.when)})" if stage.when else ""
        lines.append(f"  {stage.id:<10} ─{back}→ {stage.on_changes}{cond}")
    return "\n".join(lines)


def mermaid(pb: Playbook) -> str:
    out = ["flowchart LR"]
    ids = [s.id for s in pb.stages] + ["done"]
    for a, b in zip(ids, ids[1:], strict=False):
        out.append(f"  {a} -->|pass| {b}" if a != "work" else f"  {a} --> {b}")
    for stage in pb.gates:
        out.append(f"  {stage.id} -.->|changes| {stage.on_changes}")
    return "\n".join(out)


def main(paths: list[str]) -> None:
    for path in paths:
        pb = load(Path(path))
        problems = check(pb)
        print(f"══ {pb.name} ({pb.source}, driver = {pb.driver}, budget ${pb.budget_usd})")
        print("\n".join(f"  error:   {e}" for e in problems.errors) or "  check: ok")
        print("\n".join(f"  warning: {w}" for w in problems.warnings))
        if problems.errors:
            continue
        print("\n" + diagram(pb) + "\n\n" + mermaid(pb) + "\n")
        if pb.driver == "lead":
            print(lead_briefing(pb) + "\n")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
