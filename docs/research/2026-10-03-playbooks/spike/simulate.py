"""Dry-run a playbook against scripted outcomes, failures included, and show what people would see.

No agent runs. Each time a stage is launched, the next token of its script decides what that
run does: `pass`, `changes`, `crash`, `hang`, `quota`… The engine in `playbook.py` decides
everything else. The output has the three layers of "chatter" a person would get:

1. the ring: one line per decision, as the canvas mark would read;
2. the round conversation: findings, fixes, verdicts;
3. the transcripts: one line per run, standing in for the run's stream-json log;

plus the *Needs you* inbox, what the engine refused, the cost per stage, and two invariants:
no round is ever spent on an infrastructure failure, and no stage ever runs twice at once.

    uv run python simulate.py                       # every named scenario
    uv run python simulate.py careful/full          # one
    uv run python simulate.py --playbook playbooks/review-loop.toml review=changes,pass
"""

from __future__ import annotations

import dataclasses
import json
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

from playbook import (
    STALL_S,
    Decision,
    Done,
    Escalate,
    Facts,
    Launch,
    Ledger,
    NeedsPerson,
    Playbook,
    Reconcile,
    Run,
    Verdict,
    VerdictKind,
    Wait,
    accept,
    due,
    load,
    round_label,
)

HERE = Path(__file__).resolve().parent

# Assumptions for the cost column, stated so they can be argued with: effective tokens per run
# (cache reads already discounted) and a blended $ per million tokens.
TOKENS = {
    "work": 150_000,
    "fix-resume": 25_000,
    "fix-fresh": 90_000,
    "judgement": 70_000,
    "checklist": 40_000,
    "nudge": 5_000,
    "lead-turn": 15_000,
}
USD_PER_MTOK = {"claude": 6.0, "codex": 4.0, "opencode": 4.0}
CONTEXT = {"work": 70_000, "fix": 20_000}  # the implementer's context: under 100k it is resumed
MINUTES = {"work": 25, "judgement": 9, "checklist": 5, "criteria": 3, "person": 50}
PARTIAL = {
    "crash": 0.1,
    "hang": 0.5,
    "timeout": 0.8,
    "garbled": 1.0,
    "quota": 0.3,
    "auth": 0.0,
    "lost": 0.5,
    "late": 0.6,
    "question": 0.4,
}

FINDINGS = [
    ("high", "src/app/cache.py:42", "the cache key ignores the user, so one user's rows leak to another"),
    ("medium", "src/app/cache.py:77", "an expired entry is returned once before eviction"),
    ("low", "tests/test_cache.py:12", "the test asserts on a repr, not the value"),
    ("high", "src/app/auth/session.py:30", "the token comparison is not constant-time"),
]


@dataclass
class Scenario:
    playbook: str
    script: dict[str, list[str]]
    touched: tuple[str, ...] = ("src/app/cache.py", "tests/test_cache.py")
    budget: float | None = None
    about: str = ""


SCENARIOS: dict[str, Scenario] = {
    "review-loop/first-pass": Scenario(
        "review-loop.toml", {"review": ["pass"]}, about="The reviewer is happy at once."
    ),
    "review-loop/changes-then-pass": Scenario(
        "review-loop.toml",
        {"review": ["changes", "pass"]},
        about="One round of findings; the fix resumes Claude while warm.",
    ),
    "review-loop/cap": Scenario(
        "review-loop.toml",
        {"review": ["changes", "changes"]},
        about="Still changes on the last round: escalate to a person, no third round.",
    ),
    "careful/full": Scenario(
        "careful-change.toml",
        {"tests": ["fail", "pass", "pass"], "review": ["changes", "pass"], "security": ["pass"], "approve": ["pass"]},
        touched=("src/app/auth/session.py", "src/app/cache.py"),
        about="Tests fail once, review asks once, the diff touches auth so security runs.",
    ),
    "careful/person-sends-back": Scenario(
        "careful-change.toml",
        {"tests": ["pass", "pass"], "review": ["pass"], "approve": ["changes", "pass"]},
        about="Security skipped (no auth paths). The person asks for a change: "
        "tests re-run on the new commit, the review's pass stands.",
    ),
    "solo/flaky": Scenario(
        "solo.toml",
        {"tests": ["flaky"], "self-check": ["pass"]},
        about="A flaky test fails, is re-run once inside the gate, passes, and is recorded.",
    ),
    "solo/gamed": Scenario(
        "solo.toml",
        {"tests": ["gamed", "pass"], "self-check": ["pass"]},
        about="The implementer skipped a failing test; the gate counts tests and says no.",
    ),
    "fail/crash": Scenario(
        "review-loop.toml",
        {"review": ["crash", "pass"]},
        about="The reviewer crashes; retried after a backoff, no round spent.",
    ),
    "fail/hang": Scenario(
        "review-loop.toml",
        {"review": ["hang", "pass"]},
        about="The reviewer goes silent; killed after 5 min without an event, retried.",
    ),
    "fail/timeout": Scenario(
        "review-loop.toml",
        {"work": ["timeout", "timeout", "timeout"]},
        about="The work overruns its wall clock three times: a person is asked.",
    ),
    "fail/quota": Scenario(
        "review-loop.toml",
        {"review": ["quota", "pass"]},
        about="Codex hits its usage limit; the stage parks until the reset, then goes on.",
    ),
    "fail/auth": Scenario(
        "careful-change.toml",
        {"tests": ["pass"], "review": ["auth", "pass"], "approve": ["pass"]},
        about="Codex's login is gone mid-playbook: everything on Codex waits for a login.",
    ),
    "fail/no-verdict": Scenario(
        "review-loop.toml",
        {"review": ["none", "pass"]},
        about="The reviewer exits 0 without a verdict; nudged once for the verdict only.",
    ),
    "fail/no-verdict-twice": Scenario(
        "review-loop.toml", {"review": ["none", "none"]}, about="Nudged and still no verdict: a person is asked."
    ),
    "fail/garbled": Scenario(
        "review-loop.toml",
        {"review": ["garbled", "garbled", "garbled"]},
        about="Three malformed verdicts in a row: error, not changes, then a person.",
    ),
    "fail/stale": Scenario(
        "review-loop.toml",
        {"review": ["stale", "pass"]},
        about="Someone pushes during the review; the verdict on the old commit is ignored.",
    ),
    "fail/lost-host": Scenario(
        "review-loop.toml",
        {"work": ["lost", "ok"]},
        about="The machine reboots mid-work; on restart the run is reconciled, not relaunched blind.",
    ),
    "fail/late-verdict": Scenario(
        "review-loop.toml",
        {"review": ["late", "pass"]},
        about="A hung reviewer is killed, then posts its verdict anyway: fenced out.",
    ),
    "fail/question": Scenario(
        "review-loop.toml",
        {"review": ["question", "pass"]},
        about="The reviewer stops to ask something only a person can answer.",
    ),
    "fail/env-missing": Scenario(
        "solo.toml",
        {"tests": ["envmissing", "envmissing", "envmissing"]},
        about="The test command cannot even start: an error, never 'changes'.",
    ),
    "fail/budget": Scenario(
        "careful-change.toml",
        {"tests": ["pass"] * 4, "review": ["changes", "changes"]},
        budget=1.2,
        about="The budget runs out before the second review round: a person "
        "decides. The last run overshoots: a pre-launch check alone "
        "cannot stop a run mid-way; the CLI's own cap must.",
    ),
    "lead/lies-about-tests": Scenario(
        "careful-change-lead.toml",
        {"tests": ["lie", "pass"], "review": ["pass"], "approve": ["pass"]},
        about="The lead agent reports the tests green; DPlanner's own run says red.",
    ),
}


@dataclass
class Out:
    ring: list[str] = field(default_factory=list)
    talk: list[str] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    inbox: list[str] = field(default_factory=list)
    cost: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    invariants: list[str] = field(default_factory=list)
    outcome: str = ""


def clock(t: float) -> str:
    m = int(t // 60)
    return f"+{m // 60}:{m % 60:02d}"


class Sim:
    def __init__(self, pb: Playbook, sc: Scenario) -> None:
        self.pb = pb
        self.sc = sc
        self.script = {k: deque(v) for k, v in sc.script.items()}
        self.ledger = Ledger(touched=sc.touched)
        self.t = 0.0
        self.alive: set[str] = set()
        self.events: dict[str, float] = {}
        self.spent = 0.0
        self.n = 0
        self.sha_n = 0
        self.out = Out()
        self.verdict_tokens: dict[str, int] = defaultdict(int)  # changes the script asked for, per stage
        self.pending_late: tuple[str, str] | None = None
        self.context = 0
        self.limit = {"work": 45 * 60.0, "judgement": 20 * 60.0, "checklist": 15 * 60.0}

    # ── the loop ──
    def run(self) -> Out:
        for _ in range(80):
            decision = due(self.pb, self.ledger, Facts(self.t, frozenset(self.alive), self.spent, self.events))
            self.out.ring.append(
                f"{clock(self.t):>6}  {round_label(self.pb, self.ledger, decision):<16} {describe(decision)}"
            )
            if not self.step(decision):
                break
        self.out.cost = dict(self.out.cost)
        self.check_invariants()
        return self.out

    def step(self, d: Decision) -> bool:
        match d:
            case Launch():
                self.launch(d)
            case Wait(until=until, reason=why):
                if until is not None and "quota" in why and not any(why in i for i in self.out.inbox):
                    self.out.inbox.append(
                        f"[notify] {why} ({clock(until)}); nothing to do unless you want to "
                        "switch the stage to another profile"
                    )
                if until is None:  # a run is live and silent: let time pass to the stall detector
                    self.t += STALL_S + 1
                else:
                    self.t = until
            case Reconcile(run=run_id, reason=reason):
                self.reconcile(run_id, reason)
            case NeedsPerson():
                return self.person(d)
            case Escalate(stage=stage, reason=reason):
                self.out.inbox.append(f"[decide] {stage}: {reason}. Both positions are in the conversation.")
                self.out.outcome = f"escalated at {stage}"
                return False
            case Done():
                self.out.outcome = "done"
                return False
        return True

    # ── launching a run and playing its token ──
    def launch(self, d: Launch) -> None:
        assert self.ledger.live() is None, "invariant: a stage was launched while another run was live"
        stage = self.pb.stage(d.stage)
        token = self.next_token(stage.id, stage.kind)
        self.n += 1
        rid = f"r{self.n}"
        role = self.pb.roles.get(d.role)
        agent = role.agent if role and role.agent else "dplanner"
        run = Run(rid, stage.id, d.role, d.mode, self.t, self.ledger.head, session=f"s-{rid}")
        self.ledger = dataclasses.replace(self.ledger, runs=(*self.ledger.runs, run))
        self.alive.add(rid)
        self.events[rid] = self.t
        if self.pb.driver == "lead" and stage.kind != "work":
            self.charge("lead", "claude", TOKENS["lead-turn"])
        if stage.kind == "criteria":
            self.criteria(run, token)
        elif stage.kind == "work":
            self.work(run, token, agent, d)
        else:
            self.gate(run, token, agent, d)

    def next_token(self, stage_id: str, kind: str) -> str:
        queue = self.script.get(stage_id)
        if queue:
            return queue.popleft()
        return "ok" if kind == "work" else "pass"

    def work(self, run: Run, token: str, agent: str, d: Launch) -> None:
        kind = "work" if d.round == 0 else f"fix-{d.mode}"
        minutes = MINUTES["work"] if d.round == 0 else 10
        if self.fail(run, token, agent, TOKENS[kind], minutes):
            return
        self.sha_n += 1
        sha = f"c{self.sha_n}"
        self.t += minutes * 60
        tokens = TOKENS[kind]
        self.charge("work", agent, tokens)
        # the run's context size is what decides resume-or-fresh next time, not what it was billed
        context = CONTEXT["work"] if d.mode != "resume" else self.context + CONTEXT["fix"]
        self.context = context
        self.end(run, "ok", sha_out=sha, tokens=context)
        self.ledger = dataclasses.replace(self.ledger, head=sha)
        what = "did the step" if d.round == 0 else f"fixed round {d.round} ({d.mode}: {d.reason})"
        self.out.talk.append(f"{clock(self.t):>6}  implementer ({agent}) {what} → {sha}, ready for review")

    def criteria(self, run: Run, token: str) -> None:
        self.t += MINUTES["criteria"] * 60
        stage = self.pb.stage(run.stage)
        cmds = " && ".join(stage.run)
        if token == "envmissing":
            self.end(run, "retry", detail="the test command could not start: `uv` found no project environment")
            self.out.runs.append(f"{run.id} dplanner `{cmds}` → exit 127 before any test ran (error, not changes)")
            return
        if token == "lie":
            # the lead says green; DPlanner's own run is what counts
            claim = Verdict(stage.id, self.ledger.head, "pass", run.id, self.t, "lead")
            self.ledger = accept(self.pb, self.ledger, claim)
            token = "fail"
        verdict: VerdictKind = "pass" if token in ("pass", "flaky") else "changes"
        findings: tuple[str, ...] = ()
        note = ""
        if token == "fail":
            findings = ("tests/test_cache.py::test_isolation FAILED: assert rows == []",)
        if token == "gamed":
            findings = (
                "312 tests collected, 315 on the base: three tests disappeared; "
                "tests/test_cache.py::test_isolation is now marked skip",
            )
        if token == "flaky":
            note = "tests/test_net.py::test_retry failed, passed on the one re-run: recorded as a flake"
        if verdict == "changes":
            self.verdict_tokens[stage.id] += 1
        self.ledger = accept(
            self.pb,
            self.ledger,
            Verdict(stage.id, self.ledger.head, verdict, run.id, self.t, "dplanner", findings, note),
        )
        self.end(run, "ok")
        self.out.runs.append(f"{run.id} dplanner `{cmds}` @ {run.sha_in} → {verdict}" + (f" ({note})" if note else ""))
        self.out.talk.append(
            f"{clock(self.t):>6}  {stage.id}: {verdict}"
            + "".join(f"\n          · {f}" for f in findings)
            + (f"\n          · {note}" if note else "")
        )

    def gate(self, run: Run, token: str, agent: str, d: Launch) -> None:
        stage = self.pb.stage(run.stage)
        tokens = TOKENS["nudge"] if d.mode == "nudge" else TOKENS[stage.kind]
        minutes = 1 if d.mode == "nudge" else MINUTES[stage.kind]
        if self.fail(run, token, agent, tokens, minutes):
            return
        self.t += minutes * 60
        self.charge(stage.id, agent, tokens)
        if token == "none":
            self.end(run, "ok", tokens=tokens)
            self.out.runs.append(f"{run.id} {agent} {stage.id} ({d.mode}) → exited 0, posted no verdict")
            return
        if token == "stale":
            self.sha_n += 1
            moved = f"c{self.sha_n}"
            self.ledger = dataclasses.replace(self.ledger, head=moved)
            self.out.talk.append(
                f"{clock(self.t - 120):>6}  (a person pushed {moved} to the branch while {stage.id} ran)"
            )
            token = "pass"
        verdict: VerdictKind = "pass" if token == "pass" else "changes"
        findings: tuple[str, ...] = ()
        if verdict == "changes":
            self.verdict_tokens[stage.id] += 1
            k = self.verdict_tokens[stage.id]
            findings = tuple(
                f"[{sev}] {where} — {text}" for sev, where, text in FINDINGS[(k - 1) % 3 : (k - 1) % 3 + 2]
            )
        v = Verdict(stage.id, run.sha_in, verdict, run.id, self.t, "agent", findings)
        before = len(self.ledger.log)
        self.ledger = accept(self.pb, self.ledger, v)
        self.end(run, "ok", tokens=tokens)
        self.out.runs.append(
            f"{run.id} {agent} {stage.id} ({d.mode}) @ {run.sha_in} → {verdict}, {tokens // 1000}k tokens"
        )
        if len(self.ledger.log) == before:
            self.out.talk.append(
                f"{clock(self.t):>6}  {stage.by} ({agent}) on {stage.id}, round {d.round}: {verdict}"
                + "".join(f"\n          · {f}" for f in findings)
            )

    def fail(self, run: Run, token: str, agent: str, tokens: int, minutes: int) -> bool:
        """Play an infrastructure failure. True when the token was one."""
        if token not in PARTIAL:
            return False
        spent = int(tokens * PARTIAL[token])
        self.charge(run.stage, agent, spent)
        account = self.pb.roles[run.role].account if run.role in self.pb.roles else agent
        match token:
            case "crash":
                self.t += 40
                self.end(run, "retry", detail="exited 1 after 40 s (the CLI crashed)", tokens=spent)
            case "timeout":
                self.t += self.limit.get(self.pb.stage(run.stage).kind, 1800)
                self.end(run, "retry", detail="ran past its wall-clock limit; killed", tokens=spent)
            case "garbled":
                self.t += minutes * 60
                self.end(run, "retry", detail="its final message did not match the verdict schema", tokens=spent)
            case "quota":
                self.t += 90
                reset = self.t + 2 * 3600
                self.end(run, "park", detail=f"usage limit reached; resets at {clock(reset)}", tokens=spent)
                self.ledger = dataclasses.replace(self.ledger, parked=(*self.ledger.parked, (account, reset)))
            case "auth":
                self.t += 5
                self.end(run, "park", detail="401 authentication_failed: logged out or subscription lapsed")
                self.ledger = dataclasses.replace(self.ledger, dead=self.ledger.dead | {account})
            case "question":
                self.t += minutes * 30
                self.end(run, "person", detail="asks: should a cached row expire per user or per tenant?", tokens=spent)
            case "hang" | "late":
                self.t += 120  # last event two minutes in, then silence; the run stays 'live'
                self.events[run.id] = self.t
                if token == "late":
                    self.pending_late = (run.id, run.stage)
            case "lost":
                self.t += 600
                self.alive.discard(run.id)  # the host rebooted: the run record says live, no process does
        self.out.runs.append(
            f"{run.id} {agent} {run.stage} → {token}"
            + (f": {self.ledger.runs[-1].detail}" if self.ledger.runs[-1].detail else "")
        )
        return True

    def end(self, run: Run, outcome: str, detail: str = "", sha_out: str = "", tokens: int = 0) -> None:
        runs = tuple(
            dataclasses.replace(
                r, ended=self.t, outcome=outcome, detail=detail, sha_out=sha_out, tokens=tokens, last_event=self.t
            )
            if r.id == run.id
            else r
            for r in self.ledger.runs
        )
        self.ledger = dataclasses.replace(self.ledger, runs=runs)
        self.alive.discard(run.id)

    def reconcile(self, run_id: str, reason: str) -> None:
        stalled = run_id in self.alive
        self.alive.discard(run_id)
        run = next(r for r in self.ledger.runs if r.id == run_id)
        self.end(run, "retry" if stalled else "lost", detail=("killed: " if stalled else "lost: ") + reason)
        self.out.runs.append(
            f"{run_id} reconciled → {'killed (stall)' if stalled else 'marked lost'}; nothing relaunched blind"
        )
        if self.pending_late and self.pending_late[0] == run_id:
            self.t += 30
            late = Verdict(self.pending_late[1], run.sha_in, "pass", run_id, self.t, "agent")
            self.ledger = accept(self.pb, self.ledger, late)
            self.pending_late = None

    def person(self, d: NeedsPerson) -> bool:
        match d.kind:
            case "approve":
                token = self.next_token(d.stage, "person")
                self.out.inbox.append(f"[approve] {d.stage}: the diff, every gate's verdict and the cost so far")
                self.t += MINUTES["person"] * 60
                verdict: VerdictKind = "pass" if token == "pass" else "changes"
                findings = ("Rename the setting to cache_ttl_s; the docs call it that",) if verdict == "changes" else ()
                if verdict == "changes":
                    self.verdict_tokens[d.stage] += 1
                self.ledger = accept(
                    self.pb,
                    self.ledger,
                    Verdict(d.stage, self.ledger.head, verdict, "person", self.t, "person", findings),
                )
                self.out.talk.append(
                    f"{clock(self.t):>6}  a person on {d.stage}: {verdict}"
                    + "".join(f"\n          · {f}" for f in findings)
                )
                return True
            case "login":
                self.out.inbox.append(f"[login] {d.reason}")
                self.t += 3600
                self.ledger = dataclasses.replace(self.ledger, dead=frozenset())
                self.out.talk.append(f"{clock(self.t):>6}  (a person logged in again; the waiting stages go on)")
                return True
            case "stuck" if "asks:" in d.reason:
                self.out.inbox.append(f"[respond] {d.reason}")
                self.t += 1800
                self.ledger = dataclasses.replace(self.ledger, resets=(*self.ledger.resets, (d.stage, self.t)))
                self.out.talk.append(
                    f"{clock(self.t):>6}  a person answered: per tenant. {d.stage} runs again with the answer"
                )
                return True
            case _:
                self.out.inbox.append(f"[{d.kind}] {d.reason}")
                self.out.outcome = f"waiting for a person ({d.kind})"
                return False

    def charge(self, stage: str, agent: str, tokens: int) -> None:
        usd = tokens / 1e6 * USD_PER_MTOK.get(agent, 5.0)
        self.out.cost[stage] += usd
        self.spent += usd

    def check_invariants(self) -> None:
        for stage in self.pb.gates:
            spent = sum(1 for v in self.ledger.verdicts_of(stage.id) if v.verdict == "changes")
            asked = self.verdict_tokens[stage.id]
            ok = spent == asked and spent <= stage.rounds
            self.out.invariants.append(
                f"{'ok ' if ok else 'BROKEN'} {stage.id}: {spent} round(s) spent, {asked} asked for by a real verdict,"
                f" cap {stage.rounds}"
            )
        self.out.invariants.append("ok  never two runs live at once (asserted at every launch)")


def describe(d: Decision) -> str:
    match d:
        case Launch(stage=s, role=r, mode=m, reason=why):
            return f"launch {s} as {r} ({m}) — {why}"
        case Wait(reason=why, until=until):
            return f"wait — {why}" + (f" (until {clock(until)})" if until else "")
        case NeedsPerson(kind=k, reason=why):
            return f"needs a person ({k}) — {why}"
        case Reconcile(run=r, reason=why):
            return f"reconcile {r} — {why}"
        case Escalate(stage=s, reason=why):
            return f"escalate {s} — {why}"
        case Done(reason=why):
            return f"done — {why}"


def simulate(name: str, sc: Scenario) -> dict[str, object]:
    pb = load(HERE / "playbooks" / sc.playbook)
    if sc.budget is not None:
        pb = dataclasses.replace(pb, budget_usd=sc.budget)
    sim = Sim(pb, sc)
    out = sim.run()
    return {
        "name": name,
        "about": sc.about,
        "playbook": sc.playbook,
        "driver": pb.driver,
        "script": " ".join(f"{k}={','.join(v)}" for k, v in sc.script.items()),
        "touched": list(sc.touched),
        "outcome": out.outcome,
        "ring": out.ring,
        "talk": out.talk,
        "runs": out.runs,
        "inbox": out.inbox,
        "refused": list(sim.ledger.log),
        "cost": {k: round(v, 2) for k, v in out.cost.items()},
        "total_usd": round(sim.spent, 2),
        "budget_usd": pb.budget_usd,
        "invariants": out.invariants,
        "elapsed": clock(sim.t),
    }


def render(r: dict[str, object]) -> str:
    def block(title: str, lines: object) -> str:
        items = list(lines) if isinstance(lines, list) else []
        return f"\n  {title}\n" + ("\n".join(f"    {line}" for line in items) if items else "    —")

    cost = r["cost"]
    assert isinstance(cost, dict)
    head = (
        f"══ {r['name']} — {r['playbook']} [{r['driver']}]\n   {r['about']}\n   script: {r['script']}\n"
        f"   outcome: {r['outcome']} after {r['elapsed']}, ${r['total_usd']} of ${r['budget_usd']}"
    )
    return (
        head
        + "".join(
            [
                block("1 · ring (what the canvas mark says)", r["ring"]),
                block("2 · round conversation", r["talk"]),
                block("3 · transcripts (one line per run's stream log)", r["runs"]),
                block("needs you", r["inbox"]),
                block("refused or ignored by the engine", r["refused"]),
                block("cost by stage (assumed prices)", [f"{k:<12} ${v:.2f}" for k, v in cost.items()]),
                block("invariants", r["invariants"]),
            ]
        )
        + "\n"
    )


def main(argv: list[str]) -> None:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if argv and argv[0] == "--playbook":
        script: dict[str, list[str]] = {}
        for item in argv[2:]:
            stage, _, tokens = item.partition("=")
            script[stage] = tokens.split(",")
        results = [simulate("adhoc", Scenario(str(Path(argv[1]).resolve().relative_to(HERE / "playbooks")), script))]
    else:
        names = argv or list(SCENARIOS)
        results = [simulate(n, SCENARIOS[n]) for n in names]
    if as_json:
        print(json.dumps(results, indent=2))
    else:
        print("\n".join(render(r) for r in results))
    for r in results:
        invariants = r["invariants"]
        assert isinstance(invariants, list)
        if any("BROKEN" in line for line in invariants):
            sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
