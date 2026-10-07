"""The briefing's opening and closing words: the preflight, and how the agent reports back.

Both name other modules' verbs — ``status set``, ``note add``, ``agent-state``, ``github set``
— and every one addresses the step by its key, which is what its branch and PR are named
after.
"""

from collections.abc import Sequence
from pathlib import Path

from dplanner.core.storage.pointer import WORKTREES_DIR
from dplanner.domain.locations import CODE, LocationRole, roles_by_id
from dplanner.domain.model import Library, Step
from dplanner.domain.repositories import UNSET, RepositoryFacts
from dplanner.modules.agent_briefing.prompt import quoted
from dplanner.modules.agent_briefing.worktree import run_name_of
from dplanner.modules.notes.aspect import project_ref
from dplanner.planning.branches import BranchPlan, reading
from dplanner.planning.kinds import key_of
from dplanner.planning.status import is_done


def preamble(
    step: Step,
    in_worktree: bool,
    facts: RepositoryFacts | None,
    branches: BranchPlan,
    roles: Sequence[LocationRole],
) -> str:
    """The briefing's preflight: the agent proves it can report back, that it is where
    this run said it would be, and knows where the plan lives, before it starts.

    An agent without the DPlanner skill would do the work and leave the plan blind — no
    status, no handoff — so the briefing makes the check the first move and stopping the
    honest fallback. The second check is the worktree: two agents once "launched into
    fresh worktrees" and did their work on the same branch, so an agent whose step asks
    for a worktree confirms it is in one — by the name the launcher prepared — and stops
    if it is not. ``in_worktree`` is the caller's word on *this run* — the step's own choice
    for Run Agent and ``agent prompt``, never for a conflict the window hands over.
    ``facts`` says where the plan lives: apart from the code, or inside it — the shape that
    drifts, so the agent is warned to leave the plan files alone and let the verbs write.
    ``branches`` names the branch the worktree is on, the one the launcher prepared, and
    ``roles`` the kinds of place a project can name, which every module declares.
    """
    lines = [
        "First, confirm you can drive DPlanner: run `dplanner skill status`. If the"
        " command is missing or the skill is not installed, STOP — do not carry out the"
        " step — and tell the developer this step needs the DPlanner skill"
        " (`dplanner skill install`)."
    ]
    key = key_of(step) or step.title or "this step"
    ref = quoted(key)
    lines.append(
        "Then say you are working, before you touch anything: `dplanner agent-work start"
        f" '<what you are about to do>' --step {ref}`. A developer may have a DPlanner"
        " window open on this plan, and that is what tells them somebody else is editing"
        " it — without it they will edit the same steps you are rewriting and be asked to"
        " settle collisions they did not cause. Keep it current as you go"
        f" (`dplanner agent-work set '<what now>' --done N --of M`); setting the step's"
        " status when you finish ends it, and if you stop without one, end it yourself"
        f" (`dplanner agent-work end --step {ref}`)."
    )
    if in_worktree:
        name = run_name_of(step)
        lines.append(
            "Second, confirm you are in this step's own git worktree: `git rev-parse"
            f" --show-toplevel` must end in `{WORKTREES_DIR}/{name}` and `git branch"
            f" --show-current` must print `{branches.branch_for(name)}`. If either differs, STOP"
            " — do not touch the main checkout — and tell the developer the worktree"
            " was not prepared. Commit on that branch; every `dplanner` command still"
            " reaches the plan the window shows."
        )
    else:
        lines.append(
            "This step works in the checkout itself (its worktree option is off), on the"
            " branch that is checked out — take care: other agents may be in worktrees"
            " beside you, but this one shares the developer's working tree."
        )
    if facts is not None:
        lines.append(_plan_whereabouts(facts))
        told = _locations_told(facts, roles)
        if told:
            lines.append(told)
    lines.append(
        "Other agents may be working beside you in this repository, each in a worktree"
        " of its own, and their processes carry the same names and paths as yours. Never"
        " kill a process by name or pattern (`pkill -f`, `killall`, `kill $(pgrep …)`):"
        " kill only by a pid your own shell started."
    )
    return "\n\n".join(lines)


def _locations_told(facts: RepositoryFacts, roles_known: Sequence[LocationRole]) -> str:
    """The project's locations, told to the agent: which repositories it is about and
    where each stands on this machine, so an agent never guesses a path."""
    if not facts.placements:
        return ""
    roles = roles_by_id(roles_known)
    told: list[str] = []
    for placement in facts.placements:
        location = placement.location
        role = roles.get(location.role)
        inside = f" at `{location.path}/`" if location.path else ""
        if placement.root is None:
            where = "not checked out on this machine — do not look for it"
        elif placement.managed:
            where = "read-only, fetched by the window into the plan's spec documents"
        elif role is not None and role.writes and location.role != CODE.id:
            where = f"DPlanner exports report sites to `{placement.directory}` — do not write there"
        elif placement.kept:
            where = (
                f"`{placement.directory}` — a clone DPlanner keeps; work there as in any checkout"
            )
        else:
            where = f"`{placement.directory}`"
        told.append(f"{location.name(roles)}: {location.repository_label}{inside} — {where}")
    return (
        "The project's locations — which repositories it is about, and where each is on"
        " this machine (`dplanner location list` prints them again): " + "; ".join(told) + "."
    )


def _plan_whereabouts(facts: RepositoryFacts) -> str:
    """Where the plan lives, told to the agent: in a repository of its own, or — warned
    about unless the people on the project accepted it — inside the code it plans; or, before
    anybody named the code, in a repository of its own with nothing yet to work in."""
    if facts.state == UNSET:
        return (
            f"The plan is kept in its own repository, {facts.plan_label}, and no code"
            " repository is recorded for the project yet: the plan repository is not the"
            " code, so change nothing in it by hand. The developer records the code with"
            " `dplanner location add <project> --role code --repository URL`."
        )
    if not facts.plan_in_code:
        code = f" ({facts.code_label})" if facts.code_label else ""
        return (
            f"The plan is kept in its own repository, {facts.plan_label}, apart from the"
            f" code you are working in{code}: every `dplanner` command writes to the plan"
            " there, never to this checkout, so nothing you commit here carries a plan"
            " file and `git status` never shows one."
        )
    lead = (
        "WARNING: this plan lives inside the code repository it plans"
        if facts.warns
        else "This plan is kept inside the code repository it plans, by the developer's choice"
    )
    text = (
        f"{lead}: its files (`project.dproj`, `steps/`, `modules/`) sit in the checkout"
        " beside the code. Every `dplanner` command reaches the plan of record — the copy"
        " the window shows, in the main checkout — never a branch's copy, so do not edit"
        " those files by hand, and do not stage or commit them with your work."
    )
    if facts.warns:
        text += (
            " Do not move the plan on your own; when the developer asks for it,"
            " `dplanner project move <project> --into <plan repository>` (`--init-repo`"
            " to start one) moves it, commits both sides and re-points the library, and"
            " every verb keeps reaching the plan where it lands."
        )
    return text


def epilogue(library: Library, step: Step, branches: BranchPlan) -> str:
    """The briefing's closing words: how the agent reports back through the CLI.

    Every verb names the step by its key: a key is
    unambiguous where a title may match two steps, and it is what the branch and the
    PR are named after; the note verbs name the project too, since a note is the
    project's record.
    """
    key = key_of(step) or step.title or "Untitled step"
    ref = quoted(key)
    project = project_ref(library.project_of(step.id))
    base = (
        f" Open it against `{branches.pr_base}`: `gh pr create --base {branches.pr_base}`."
        if branches.pr_base
        else ""
    )
    found = reading(library.project_of(step.id), is_done)
    stretch = None if found.of_land(step.id) else found.innermost(step.id, open_only=True)
    if stretch is not None:
        cut, land = key_of(stretch.cut), key_of(stretch.land)
        base += (
            f" This step is on the feature branch `{stretch.branch}`, which {cut} cuts and"
            f" {land} lands: its PR merges into that branch, never into the mainline, and merged"
            " there it is accepted — the branch's own review comes when it lands."
        )
    return (
        f"This step is {key}. Its branch and worktree carry that key; open the PR title"
        f" with it (`{key}: …`) and record the branch and the PR on the step as they"
        f" exist: `dplanner github set {ref} --branch $(git branch --show-current)`,"
        f" then `dplanner github set {ref} --pr <number>`.{base} Once the PR is open, set"
        " the status (below) straight away: it takes the window's banner down with it.\n"
        "As you work, keep the run state current:\n"
        f"- `dplanner agent-state set {ref} plan-for-review` when your plan is ready"
        " to review\n"
        f"- `dplanner agent-state set {ref} working` while implementing\n"
        f"- `dplanner agent-state set {ref} pending-approval` while waiting on an"
        " approval\n"
        f"- `dplanner agent-state set {ref} needs-input` when you have a question the"
        " developer must answer before you can go on\n"
        + _notes_told(project, ref)
        + "When the work is finished, record it in DPlanner:\n"
        + f"- `dplanner status set {ref} ready-for-review` and `dplanner agent-state clear"
        f" {ref}` — ready for review, never done: a person or a reviewing agent looks next"
        " and sets it done. That is the step's work finished, not the mid-run"
        " `plan-for-review` above, which is your plan waiting for a look. If nothing needs"
        f" reviewing, `dplanner status set {ref} done --because '<why>'` keeps the reason"
        " as a decision note.\n"
        + _handoff_told(project, ref)
        + f"If you cannot finish, `dplanner status set {ref} blocked` and say why in the"
        " handoff note.\n"
        "Each of those statuses ends your working claim. If you stop without setting one,"
        f" end it yourself: `dplanner agent-work end --step {ref}` — a banner nobody ended"
        " is one nobody believes next time."
    )


def _notes_told(project: str, ref: str) -> str:
    """The notes an agent leaves as it goes, as the epilogue words them."""
    return (
        "As you go, leave notes — the project's record, indexed into the briefing of every"
        " step that comes after the one you made them on. That is the reach: add"
        " `--reach project` when what you settled belongs to the whole plan rather than"
        " this branch. `dplanner note add --help` lists the labels:\n"
        f"- `dplanner note add {project} decision '<what you chose>' --step {ref}"
        " --text '<why>'` for each choice the plan should remember (`--supersedes N3`"
        " when it reverses an earlier one)\n"
        f"- `dplanner note add {project} spec-change '<what differs>' --step {ref}"
        " --text '<what and why>'` where the work had to depart from the spec\n"
        f"- `dplanner note add {project} later '<what>' --step {ref}` for work you"
        " noticed and did not do\n"
    )


def _handoff_told(project: str, ref: str) -> str:
    """The handoff note an agent leaves when it stops, as every epilogue words it."""
    return (
        f"- `dplanner note add {project} handoff '<one line the next worker needs>'"
        f" --step {ref} --file -` with what whoever picks up after you must know —"
        " where things are, what is half done, what bit you. Title it as the fact it"
        " is; the body carries the detail. Add `--for S12` for a step that must read it"
        " in full, `--reach project` if every step should see it regardless;"
        f" `dplanner note attach {project} <id> <file>` for files.\n"
    )


def opening_prompt(prompt_file: Path) -> str:
    """The one line the agent starts with — a pointer at the briefing, never the briefing.

    The whole briefing in argv was what one agent's ``pkill -f`` matched on every other
    (``agent_launch/launcher.py``'s docstring); nothing the project is about appears in
    this line. Run Agent's terminal and the run supervisor's first turn both open with it.
    """
    return f"Read your briefing in {prompt_file} in full, then follow it."
