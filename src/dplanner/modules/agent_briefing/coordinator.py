"""The coordinator's briefing: a squad's Actual working a selection of one project's graph.

A coordinator carries out no step of its own. It takes the selection as its squad's claim,
starts each ready step as a member of the squad (``agent run --playbook --callsign``), watches
the runs, answers what it may and escalates the rest, verifies and merges, and releases what
it finished — with the verbs every other surface uses, so nothing here is a second engine.
What the 4 October run's director learned by hand is in the loop, one sentence each.

``dplanner agent coordinate`` prints it, and Autonomous work ▸ Local launches a coordinator
with the same text.
"""

from collections.abc import Callable, Sequence

from dplanner.domain.claims import WATCH, member, spoken
from dplanner.domain.locations import LocationRole
from dplanner.domain.model import Library, Step
from dplanner.domain.repositories import RepositoryFacts
from dplanner.domain.store import FilesFor
from dplanner.modules.agent_briefing.blocks import project_sections
from dplanner.modules.agent_briefing.prompt import (
    AssembledPrompt,
    PromptPart,
    PromptSegment,
    quoted,
    section_lines,
)
from dplanner.modules.agent_briefing.protocol import (
    NEVER_KILL,
    locations_told,
    plan_whereabouts,
)
from dplanner.modules.notes.aspect import project_ref
from dplanner.planning.agent import read_project
from dplanner.planning.kinds import key_of
from dplanner.planning.progression import outstanding
from dplanner.planning.status import Status

# The share of any usage window past which the coordinator launches nothing: under the
# supervisor's own hold, so the coordinator — on the same account — keeps room to work.
LAUNCH_CEILING = 90


def members(squad: str, steps: Sequence[Step]) -> dict[str, str]:
    """Each selected step's member callsign, by the selection's order: the first is Two."""
    return {step.id: member(squad, number) for number, step in enumerate(steps, start=2)}


def coordinate(
    library: Library,
    steps: Sequence[Step],
    *,
    squad: str,
    files: FilesFor,
    facts: RepositoryFacts | None,
    roles: Sequence[LocationRole],
    merges_into: Callable[[Step], str],
    status_for: Callable[[Step], Status],
    at_once: int,
) -> AssembledPrompt:
    """The briefing for ``squad``'s coordinator over ``steps`` — one project's, in the order
    the squad takes them. ``merges_into`` names the feature branch a step's PR merges
    into, "" for the mainline; ``status_for``
    reads a status as readiness does, and ``at_once`` is how many runs may be live."""
    project = library.project_of(steps[0].id)
    actual = member(squad)
    ref = project_ref(project)
    keys = [key_of(step) or step.title for step in steps]
    called = members(squad, steps)
    standing = read_project(project)
    parts: list[tuple[str, PromptPart]] = [
        ("protocol", _before(squad, keys, facts, roles)),
        ("context", _squad(squad, steps, called)),
        ("context", _selection(library, steps, called, merges_into, status_for)),
        *(
            [("project", PromptPart("What every worker is told", standing))]
            if standing.strip()
            else []
        ),
        *(("project", part) for part in project_sections(library, steps[0], files)),
        ("instruction", _loop(ref, actual, at_once)),
        ("protocol", _done(ref, actual)),
    ]
    blocks = [
        ("header", "Coordinate", [f"# Coordinate: {project.title}", "", f"Squad: {squad}", ""]),
        *((origin, part.heading, section_lines(part)) for origin, part in parts),
    ]
    segments = tuple(
        PromptSegment(origin, "\n".join(lines) + ("\n" if index < len(blocks) - 1 else ""), head)
        for index, (origin, head, lines) in enumerate(blocks)
    )
    return AssembledPrompt(
        text="".join(segment.text for segment in segments), files=(), segments=segments
    )


def _before(
    squad: str,
    keys: Sequence[str],
    facts: RepositoryFacts | None,
    roles: Sequence[LocationRole],
) -> PromptPart:
    lines = [
        "First, confirm you can drive DPlanner: run `dplanner skill status`. If the command is"
        " missing or the skill is not installed, STOP and tell the developer this needs the"
        " DPlanner skill (`dplanner skill install`).",
        f"Then say you are on the net: `dplanner agent-work start '{spoken(member(squad))}:"
        f" coordinating {', '.join(keys)}' --of {len(keys)}`.",
        "This run outlives your attention: before a long stretch, make sure the machine will"
        " not suspend (on Omarchy, the stay-awake toggle) — a suspended machine freezes every"
        " agent of the squad, you included.",
    ]
    if facts is not None:
        lines.append(plan_whereabouts(facts))
        if told := locations_told(facts, roles):
            lines.append(told)
    lines += [
        "Take the selection before you start any of it:"
        f" `dplanner claim take {' '.join(quoted(key) for key in keys)} --callsign {squad}`."
        " If it refuses a step, another squad holds it: leave that step out and say so —"
        " never take it over by hand.",
        NEVER_KILL,
    ]
    return PromptPart("Before you start", "\n\n".join(lines))


def _squad(squad: str, steps: Sequence[Step], called: dict[str, str]) -> PromptPart:
    actual, watch = member(squad), f"{squad}-{WATCH}"
    roster = [f"- **{spoken(actual)}** (`{actual}`) — you, the coordinator"]
    roster += [
        f"- **{spoken(called[step.id])}** (`{called[step.id]}`) — works"
        f" {key_of(step) or step.title}, through every stage of its playbook"
        for step in steps
    ]
    roster.append(f"- **{spoken(watch)}** (`{watch}`) — your own verifier, when you send one")
    body = "\n".join(
        [
            f"You are {spoken(actual)}. Squad {squad.capitalize()} is unique among the squads"
            " running now; the roster is fixed for this selection:",
            "",
            *roster,
            "",
            f"A member's own sub-agent adds a number: {spoken(member(squad, 2, 1))}"
            f" (`{member(squad, 2, 1)}`). A callsign is lowercase-kebab wherever a machine reads"
            " it and spoken capitalised in prose. Use yours in every message, log line and note"
            f" title you write (`{spoken(actual)}: …`), end every commit you make with the"
            f" trailer `Callsign: {actual}`, and name the branches and worktrees you make"
            f" yourself `{actual}/<what>`. Workers' branches are DPlanner's (`agent/<run>`):"
            " leave them as they are. Crisp, cheerful and exact — the net is read by people.",
        ]
    )
    return PromptPart("Your squad", body)


def _selection(
    library: Library,
    steps: Sequence[Step],
    called: dict[str, str],
    merges_into: Callable[[Step], str],
    status_for: Callable[[Step], Status],
) -> PromptPart:
    lines = []
    for step in steps:
        waits = [key_of(each) or each.title for each in outstanding(library, step, status_for)]
        status = status_for(step)
        moves = "ready" if status is Status.PENDING and not waits else ""
        if waits:
            moves = "waits on " + ", ".join(waits)
        base = merges_into(step)
        lands = f"PR into `{base}`" if base else "PR into the mainline, which a person merges"
        facts = [status.value, moves, f"`{called[step.id]}`", lands]
        lines.append(
            f"- **{key_of(step)}** {step.title} — " + " · ".join(fact for fact in facts if fact)
        )
    lines += [
        "",
        "Address every step by its key as listed — never by a title, which may match a step"
        " in another project.",
    ]
    return PromptPart("The selection", "\n".join(lines))


def _loop(project: str, actual: str, at_once: int) -> PromptPart:
    said = spoken(actual)
    body = "\n".join(
        [
            "Work the selection until every step is done, blocked, or waiting on a person."
            " Each round:",
            "",
            "1. **Launch what is ready.** For each ready step with no run under way:"
            " `dplanner agent run <key> --playbook --callsign <its member>` — at most"
            f" {at_once} runs live at once. Steps that would touch the same files run one after"
            " the other even where the graph allows both; read two plans side by side before"
            " you pass either.",
            "2. **Mind the quota.** You share the account with your squad: read `dplanner"
            " agent limits` before every launch and start nothing while a window reads"
            f" {LAUNCH_CEILING} % or more. A run that hits its limit parks and its supervisor"
            " waits out the reset — never wait for one in your own session.",
            "3. **Watch.** Check in about every ten minutes — `dplanner question list --open`,"
            f" `dplanner claim list`, `dplanner progression show {project}`, and `dplanner usage"
            " show <key>` for a run you are unsure of; every check renews your claim. Wait"
            " between checks with your harness's own scheduled wake-up, never a background"
            " watcher or a sleep loop. A quiet terminal or exit 0 is not done: the step's status"
            " and its runs say what happened.",
            "4. **Answer or escalate.** You may answer a coordinator gate, a round cap, and a"
            " worker's decision, plan approval or block: `dplanner question answer Q-…"
            f" '<label>' --by {actual}`, with a choice's exact label — any other words are read"
            " as changes. Never stand in for a review gate or a person gate, and never answer"
            " what DPlanner refuses you. When the answer would change what the product *is*,"
            f" escalate: `dplanner question escalate Q-… --why '<why>' --by {actual}`.",
            "5. **Review where it pays.** A cross-vendor review (Codex) is worth its cost on"
            " core changes; cap it at two rounds, then rule on what is left yourself.",
            "6. **Fix small things fresh.** For a small fix after a long session, a fresh run"
            " briefed with the findings costs a fraction of resuming the old one ($2 against"
            " $35, once).",
            "7. **Verify and merge.** When a step reads ready-for-review and no `progress` stage"
            " merged it: read the diff, and check its PR goes from the step's branch into the"
            " base listed above — never the mainline, which a person merges. GitHub reads"
            " `mergeable` as UNKNOWN for a few seconds after any push or merge: poll `gh pr view"
            " <n> --json mergeable` until it settles, since UNKNOWN is not a conflict; then `gh"
            " pr merge <n> --merge`. Run the project's checks on the integrated branch in your"
            f" own worktree (`{actual}/verify`), in the foreground under a timeout — the ratchet"
            " tests first (an architecture or rule-size ceiling): two PRs that each fit a"
            " ceiling can exceed it together. Rerun a lone failure alone before you believe it.",
            "8. **Release.** `dplanner github refresh <key>` lets the merge accept the step;"
            " then `dplanner claim release <key> --why merged`, and back to 1 — what it"
            " unblocked may be ready now.",
            "",
            "A run parked on a limit is its supervisor's; `dplanner agent retry <key>` is for a"
            " block you understand; a step that cannot go on is `dplanner status set <key>"
            " blocked`, with a note saying why. Record each ruling you make:"
            f" `dplanner note add {project} decision '{said}: <what>' --step <key> --text"
            " '<why>'`.",
        ]
    )
    return PromptPart("The loop", body)


def _done(project: str, actual: str) -> PromptPart:
    said = spoken(actual)
    body = (
        "When every step is done, blocked, or waiting on a person: end the claim with"
        " `dplanner claim end C-… --why done` (`claim take` printed its id) — unless a step"
        " still waits on a person, since ending stops its run: then leave the claim standing"
        " and say so. Leave a handoff,"
        f" `dplanner note add {project} handoff '{said}: <one line>' --file -`, naming what is"
        " open, what you escalated and what you ruled; run `dplanner agent-work end`; and"
        f" close with a short report signed {said}."
    )
    return PromptPart("When you are done", body)
