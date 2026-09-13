"""The briefing an agent is handed to compile one collector's documentation.

**The docs module words this, not the agent module.** What a fragment is, what the
compilation instructions are and which verb finishes the job are this module's vocabulary;
the agent module wraps whatever it is handed with the header and its own preflight
(``step_agent_instruction/prompt.py``'s ``handover_prompt``) and knows none of it. Same seam
as the launch callbacks on ``DocsDeps``, one level up.

Qt-free, and the same function for both callers there will ever be: the window's *Compile
with Agent…* and a test. There is no ``docs compile`` verb — an agent reading this briefing
*is* the compiler, and the loop it runs is ``docs collect`` → write → ``compiled set``.
"""

from collections.abc import Sequence

from dplanner.modules.docs.collect import Source, as_markdown

# What kind of writing this is. It was the LLM call's system prompt, addressed to a model
# with no other context; an agent reads it as the brief for one deliverable among the
# project's own instructions, so it says the same things in the second person.
BRIEF = (
    "You are writing **end-user documentation** for this product — the words somebody using"
    " it would read, not the words the plan used. Below are the fragments the people who did"
    " the work wrote as they went, and sometimes documentation already compiled for part of"
    " it. Turn them into one coherent document.\n\n"
    "Write markdown. Describe what the product does and how to use it, never the plan that"
    " produced it: no step titles, no task language, no mention of these notes or of this"
    " briefing. Merge what overlaps, order it so a reader meets a thing before it is used,"
    " and keep every concrete detail the fragments give — names, options, limits. Where they"
    " are thin, say less rather than inventing."
)

# A fragment's images live in its own step's file area, and a compiled document renders them
# by asking each source step's area in turn (``aspect.asset_source``). A rewritten link
# therefore points at nothing, and an invented one at nothing at all.
IMAGES = (
    "Keep every `![](assets/…)` link exactly as it is written, in the text it belongs to."
    " Do not rename one, do not move one to another path, and do not invent one: the image"
    " is found by that name beside the step whose fragment carried it."
)

# The deliverable is a plan entry, not a file in the repository the shell opened in.
NOTHING_TO_COMMIT = (
    "Write nothing in this checkout and commit nothing: the whole output of this run is the"
    " document you hand to `dplanner`."
)


def compile_body(
    *,
    key: str,
    kind: str,
    instructions: str,
    about: str,
    sources: Sequence[Source],
) -> str:
    """The briefing's body: what to write, what to follow, what to read, how to land it.

    ``kind`` is the collector's own word ("feature", "milestone") — it heads the block that
    says what this collector *is*, which is the collector's description. That block is not a
    writing brief: on a feature step the description is the work's instructions (*The
    description is the instructions*), so it is offered as context and named as such, and the
    brief every document follows is the project's ``instructions``.

    Each block is dropped when it is empty rather than announced as absent, so a project with
    no compilation instructions does not tell the agent there are none.
    """
    blocks = [f"## What to do\n\n{BRIEF}\n\n{IMAGES}\n\n{NOTHING_TO_COMMIT}"]
    if instructions.strip():
        blocks.append(f"## Compilation instructions\n\n{instructions.strip()}")
    if about.strip():
        blocks.append(f"## What this {kind or 'collector'} is\n\n{about.strip()}")
    # Level three: the wrapper's header is the only `#` and the blocks here are the `##`, so
    # each fragment sits under the one that introduces them.
    gathered = as_markdown(sources, level=3).strip()
    blocks.append(
        "## What the work documented\n\n"
        + (gathered or "(nothing yet — say so rather than inventing a document)")
    )
    blocks.append(
        "## When you are done\n\n"
        "Hand the document to the plan — from a file, or straight in:\n\n"
        f"```\ndplanner compiled set {key} --file - <<'EOF'\n"
        "…the document…\nEOF\n```\n\n"
        "That stamps what it was compiled from, so it reads as up to date until somebody"
        f" edits a fragment behind it; `dplanner compiled show {key}` reads it back. Write the"
        " document nowhere else, and do not change the step's status."
    )
    return "\n\n".join(blocks)
