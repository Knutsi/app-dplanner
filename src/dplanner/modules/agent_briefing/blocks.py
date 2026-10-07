"""The step's own facts and the project's, as the blocks a briefing carries.

What a step is, why it exists, where its work lands, the work it lands, the notes that
reach it, and the project's topology — each read
from the module that owns the fact, through its ``aspect.py``. An empty fact contributes no
block, and :func:`~dplanner.modules.agent_briefing.prompt.assemble` renders the blocks
without knowing what any of them is.
"""

from dplanner.domain.assets import assets
from dplanner.domain.model import Library, Step
from dplanner.domain.repositories import RepositoryFacts
from dplanner.domain.store import FilesFor
from dplanner.modules.agent_briefing.prompt import PromptPart
from dplanner.modules.agent_briefing.worktree import run_name_of, workdir, worktree_path
from dplanner.modules.github.aspect import pr_label
from dplanner.modules.github.aspect import read as github_read
from dplanner.modules.notes.aspect import briefing_blocks, note_files, reaching
from dplanner.modules.spec.aspect import attachment_paths, read_topology
from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
from dplanner.modules.step_description.aspect import read as description_read
from dplanner.planning.agent import read as instruction_read
from dplanner.planning.agent import uses_worktree
from dplanner.planning.branches import is_land, reading
from dplanner.planning.feature import FeatureSource, is_feature
from dplanner.planning.feature import read as feature_read
from dplanner.planning.kinds import flows_into, key_of
from dplanner.planning.status import is_done, phrase, stored


def module_asset_paths(files: FilesFor, node_id: str, module_id: str) -> tuple[str, ...]:
    """A node's module files as absolute paths; a never-flushed node has none."""
    try:
        area = files(node_id, module_id)
    except KeyError:
        return ()
    return tuple(str(area.absolute(name)) for name in assets(area))


def note_parts(library: Library, step: Step, files: FilesFor) -> list[PromptPart]:
    """The briefing's blocks after the instructions: the notes addressed to this step in
    full, and the index of everything else that reaches it — the notes module's own
    blocks, made prompt parts here. Both surfaces and ``dplanner note index`` read the same
    blocks, so the window, the verb and the CLI cannot brief a step two ways."""
    project = library.project_of(step.id)
    return [
        PromptPart(
            heading=block.heading,
            body=block.body,
            files=tuple(
                path for note in block.carried for path in note_files(files, project.id, note)
            ),
        )
        for block in briefing_blocks(project, reaching(library, step), key_of)
    ]


def _passage_place(source: FeatureSource) -> str:
    page = f" p.{source.page}" if source.page is not None else ""
    return f"{source.document}{page}"


def step_sections(
    library: Library,
    step: Step,
    files: FilesFor,
    facts: RepositoryFacts | None,
) -> list[PromptPart]:
    """The step's own facts as briefing sections: what it is, why it exists, where the
    work lands, and the work it reviews or lands. An empty fact contributes no section.
    """
    sections: list[PromptPart] = []
    # Without a separate instruction the description IS the ## Instructions block (see
    # instruction), so a Description section here would say everything twice.
    description = description_read(step)
    description_files = module_asset_paths(files, step.id, DESCRIPTION_ID)
    if instruction_read(step) and (description or description_files):
        sections.append(
            PromptPart(heading="Description", body=description, files=description_files)
        )
    project = library.project_of(step.id)

    def passage_lines(holder: Step) -> list[str]:
        """Where one feature was read from — its step's title, then each passage."""
        cites = feature_read(holder) or ()
        where = f", from {_passage_place(cites[0])}" if len(cites) == 1 else ""
        lines = [f"- **{holder.title}**{where}"]
        for source in cites:
            if len(cites) > 1:
                lines.append(f"  from {_passage_place(source)}:")
            lines += [f"  > {quoted}" for quoted in source.quote.splitlines()]
        return lines

    if is_feature(step):
        # The feature's name and its prose are this step's own — already the title of the
        # briefing and its ## Instructions block — so what is left to say is where in the
        # specification it was read from.
        cites = feature_read(step) or ()
        if cites:
            sections.append(
                PromptPart(heading="Read from the spec", body="\n".join(passage_lines(step)))
            )
    else:
        # A work step reaches the spec through the feature it flows into: the graph's
        # answer, the same walk the Covers tab and `scope show` read.
        holders = flows_into(library, project, step.id)
        lines = [line for holder in holders for line in passage_lines(holder)]
        if lines:
            sections.append(PromptPart(heading="Flows into", body="\n".join(lines)))
    figures = attachment_paths(files, step.id)
    if figures:
        sections.append(
            PromptPart(
                heading="Figures from the spec",
                body="Rendered from the specification for this step — look at them.",
                files=figures,
            )
        )
    refs = github_read(step)
    if refs is not None:
        lines = []
        if refs.branch:
            lines.append(f"Branch: {refs.branch}")
        if refs.has_pr():
            pr = pr_label(refs)
            if refs.pr_title:
                pr += f" — {refs.pr_title}"
            if refs.pr_state:
                pr += f" ({refs.pr_state})"
            if refs.pr_base:
                pr += f" into {refs.pr_base}"
            if refs.pr_url:
                pr += f" {refs.pr_url}"
            lines.append(pr)
        if lines:
            sections.append(PromptPart(heading="Where the work lands", body="\n".join(lines)))
    landed = _landed_work(library, step, facts)
    if landed:
        sections.append(PromptPart(heading="Work you land", body=landed))
    return sections


def _landed_work(library: Library, step: Step, facts: RepositoryFacts | None) -> str:
    """What a landing is handed about the branch it lands: each step on it where it stands.
    Empty for a step that lands nothing."""
    if not is_land(step):
        return ""
    stretch = reading(library.project_of(step.id), is_done).of_land(step.id)
    if stretch is None:
        return ""
    return "\n".join(_source_line(member, facts) for member in stretch.members)


def _source_line(source: Step, facts: RepositoryFacts | None) -> str:
    """One step a landing takes the work of, where it stands: its status, its branch and
    PR, and its worktree on this machine — a line of *Work you land*.

    The worktree is named from the same rule the launcher prepared it by (``run_name_of``),
    under the checkout of the code location the step works in; whether it is *here* is the
    one thing only this machine can say, so it is asked.
    """
    refs = github_read(source)
    facts_of = [phrase(stored(source))]
    facts_of.append(
        f"branch `{refs.branch}`" if refs is not None and refs.branch else "no branch recorded"
    )
    if refs is not None and refs.has_pr():
        pr = pr_label(refs)
        if refs.pr_base:
            pr += f" into `{refs.pr_base}`"
        if refs.pr_url:
            pr += f" {refs.pr_url}"
        facts_of.append(pr)
    if not uses_worktree(source):
        facts_of.append("worked in the checkout itself, no worktree")
    else:
        root = workdir(facts, source) if facts is not None else None
        path = worktree_path(root, run_name_of(source)) if root is not None else None
        here = path is not None and path.is_dir()
        facts_of.append(f"worktree `{path}`" if here else "no worktree of it on this machine")
    return f"- **{key_of(source)}** {source.title} — " + " · ".join(facts_of)


def project_sections(library: Library, step: Step, _files: FilesFor) -> list[PromptPart]:
    """The project's own facts as briefing sections: its topology — how the graph is
    shaped, which every step is read against. (What the project recorded along the way
    — decisions included — is the notes index after the instructions, ``note_parts``.)"""
    project = library.project_of(step.id)
    sections: list[PromptPart] = []
    topology = read_topology(project)
    if topology.strip():
        sections.append(
            PromptPart(heading="Topology — how this project's graph is shaped", body=topology)
        )
    return sections
