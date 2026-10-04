"""Branch stretches in the window: Put on a Branch and Remove Branch from a right-click on
the picked steps, the Landing toggle, and what the root makes of a cut and of a merge."""

from datetime import date

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
from dplanner.modules.branches.aspect import (
    CUT_ID,
    LAND_ID,
    branch_of,
    cut_of,
    remap_for_paste,
    write_cut,
    write_land,
)
from dplanner.planning.status import Status

TODAY = date(2026, 9, 29)


@pytest.fixture
def plan(services, make_project):
    """Menu, then Card fanning out to Edit and Canvas and back into Drag, then Release."""
    services.clock.pin(TODAY)
    library = services.document
    project = make_project("Stacks")
    for title in ("Menu", "Card", "Edit", "Canvas", "Drag", "Release"):
        AddNodeCommand(project.id, Step(title=title)).redo(library)
    menu, card, edit, canvas, drag, release = project.steps
    library.set_edges(card.id, "requires", [menu.id])
    library.set_edges(edit.id, "requires", [card.id])
    library.set_edges(canvas.id, "requires", [card.id])
    library.set_edges(drag.id, "requires", [edit.id, canvas.id])
    library.set_edges(release.id, "requires", [drag.id])
    return project


def picked(*steps):
    return Context(
        {SCOPE_SELECTION: tuple(ContextNode(selection_uri("step", s.id)) for s in steps)}
    )


def titled(project, title):
    return next(step for step in project.steps if step.title == title)


def test_put_on_a_branch_brackets_the_pick_as_one_undo(services, plan, monkeypatch):
    from dplanner.framework.dialog import LinePrompt

    asked = []

    def answer(_parent, _title, _caption, _verb, *, text="", **_kwargs):
        asked.append(text)
        return "feature/stacks"

    monkeypatch.setattr(LinePrompt, "ask", answer)
    chosen = [titled(plan, t) for t in ("Card", "Edit", "Canvas", "Drag")]
    state = services.actions.spec("branch.put").state(picked(*chosen))
    assert state.enabled
    services.actions.run("branch.put", picked(*chosen))
    assert asked == ["feature/card"]  # Named for the pick, ready to accept.
    (cut,) = [s for s in plan.steps if branch_of(s)]
    (land,) = [s for s in plan.steps if cut_of(s)]
    assert branch_of(cut) == "feature/stacks" and cut_of(land) == cut.id
    assert titled(plan, "Card").edges["requires"] == [cut.id]
    assert titled(plan, "Release").edges["requires"] == [land.id]
    assert services.undo.undo_text() == "Put on a Branch"
    services.undo.undo()
    assert len(plan.steps) == 6
    assert titled(plan, "Card").edges["requires"] == [titled(plan, "Menu").id]


def test_put_on_a_branch_is_greyed_with_the_step_left_between(services, plan):
    state = services.actions.spec("branch.put").state(
        picked(titled(plan, "Card"), titled(plan, "Drag"))
    )
    assert not state.enabled and "comes between them" in state.label


def test_remove_branch_asks_then_takes_the_whole_bracket_away(services, plan, monkeypatch):
    from dplanner.modules import _branch_births
    from dplanner.modules.branches import module
    from dplanner.modules.branches.edits import put_command

    library = services.document
    chosen = [titled(plan, t).id for t in ("Card", "Edit", "Canvas", "Drag")]
    cut, land = _branch_births(plan, "feature/stacks")
    services.undo.push(put_command(library, chosen, cut, land))
    questions = []
    monkeypatch.setattr(
        module, "confirm", lambda _parent, _title, question, **_kw: questions.append(question)
    )
    edit = titled(plan, "Edit")
    state = services.actions.spec("branch.remove").state(picked(edit))
    assert state.enabled and "feature/stacks" in state.label
    services.actions.run("branch.remove", picked(edit))  # Declined: nothing changes.
    assert "not only the ones you picked" in questions[0]
    assert library.has(cut.id)
    monkeypatch.setattr(module, "confirm", lambda *_args, **_kw: True)
    services.actions.run("branch.remove", picked(edit))
    assert not library.has(cut.id) and not library.has(land.id)
    assert titled(plan, "Card").edges["requires"] == [titled(plan, "Menu").id]
    assert titled(plan, "Release").edges["requires"] == [titled(plan, "Drag").id]
    assert services.undo.undo_text() == "Remove Branch"


def test_remove_branch_is_greyed_on_a_step_on_no_branch(services, plan):
    state = services.actions.spec("branch.remove").state(picked(titled(plan, "Menu")))
    assert not state.enabled and "no picked step is on a branch" in state.label


def test_a_cut_is_nobodys_work_and_reads_done_once_what_it_waits_on_is(services, plan):
    from dplanner.modules import (
        _card_status,
        _counts_as_work,
        _primary_glyph,
        _status_in,
        _step_key,
    )
    from dplanner.planning.status import MODULE_ID as STATUS_ID
    from dplanner.planning.status import write as status_write

    library = services.document
    card = titled(plan, "Card")
    library.set_module_data(card.id, CUT_ID, write_cut("feature/x"))
    assert _step_key(card).startswith("B") and _primary_glyph(card) == ("branch", "")
    assert not _counts_as_work(card) and _card_status(card) is Status.PENDING
    status = _status_in(library, TODAY)
    assert status(card) is not Status.DONE
    library.set_module_data(
        titled(plan, "Menu").id, STATUS_ID, status_write(Status.DONE, today=TODAY)
    )
    assert _status_in(library, TODAY)(card) is Status.DONE


def test_a_merge_into_the_branch_accepts_a_member_under_review(services, plan):
    """Inside an open stretch, a PR merged into its branch is the acceptance — the review
    comes when the branch lands. A merge into anything else accepts nothing unreviewed."""
    from dplanner.modules import _merged_into_its_branch
    from dplanner.modules.github.aspect import MODULE_ID as GITHUB_ID
    from dplanner.modules.github.aspect import GithubRefs
    from dplanner.modules.github.aspect import write as github_write

    library = services.document
    card, edit = titled(plan, "Card"), titled(plan, "Edit")
    library.set_module_data(card.id, CUT_ID, write_cut("feature/x"))
    library.set_module_data(titled(plan, "Drag").id, LAND_ID, write_land(card.id))
    refs = GithubRefs(pr_number=7, pr_state="merged", pr_base="feature/x")
    library.set_module_data(edit.id, GITHUB_ID, github_write(refs))
    assert _merged_into_its_branch(library, edit)
    library.set_module_data(
        edit.id, GITHUB_ID, github_write(GithubRefs(pr_number=7, pr_base="main"))
    )
    assert not _merged_into_its_branch(library, edit)


def test_a_pasted_landing_lands_its_copied_cut_or_nothing():
    land = Step(title="Land")
    land.module_data[LAND_ID] = write_land("old-cut")
    remap_for_paste(None, [land], {"old-cut": "new-cut"})  # type: ignore[arg-type]
    assert cut_of(land) == "new-cut"
    remap_for_paste(None, [land], {})  # type: ignore[arg-type]
    assert LAND_ID not in land.module_data


# -- the canvas -----------------------------------------------------------------------------


def edge(tab, waiter, source):
    from dplanner.modules.project_editor.selection import EdgeRef

    return tab._scene._edges[EdgeRef(waiter=waiter.id, kind="requires", source=source.id)]


def test_the_work_on_a_branch_lies_on_its_lane_until_it_lands(services, plan):
    from dplanner.modules import _branch_births
    from dplanner.modules.branches.edits import put_command
    from dplanner.planning.status import MODULE_ID as STATUS_ID
    from dplanner.planning.status import write as status_write
    from dplanner.theme.palettes import LANES

    library = services.document
    chosen = [titled(plan, t).id for t in ("Card", "Edit", "Canvas", "Drag")]
    cut, land = _branch_births(plan, "feature/stacks")
    services.undo.push(put_command(library, chosen, cut, land))
    tab = services.tabs.open("project", plan.id)
    card, edit, drag = titled(plan, "Card"), titled(plan, "Edit"), titled(plan, "Drag")
    assert edge(tab, card, cut).accent().lane == LANES[0]
    assert edge(tab, edit, card).accent().lane == LANES[0]
    assert edge(tab, land, drag).accent().lane == LANES[0]
    assert not edge(tab, cut, titled(plan, "Menu")).accent().lane  # The way in is main's.
    assert not edge(tab, titled(plan, "Release"), land).accent().lane  # And the way out.
    assert "merge" in tab._scene._nodes[land.id]._accent.icons
    library.set_module_data(land.id, STATUS_ID, status_write(Status.DONE, today=TODAY))
    assert not edge(tab, edit, card).accent().lane  # Landed: on main now.


def test_a_card_on_a_branch_wears_its_name_underneath_and_stands_taller(services, plan):
    """The strip is part of the card — its size, what a sort spaces by — while the arrows
    still meet the middle of the body above it, and the step stores the body alone."""
    from dplanner.modules import _branch_births
    from dplanner.modules.branches.edits import put_command
    from dplanner.modules.project_editor.positions import NODE_H, STRIP_H

    library = services.document
    chosen = [titled(plan, t).id for t in ("Card", "Edit", "Canvas", "Drag")]
    cut, land = _branch_births(plan, "feature/stacks")
    services.undo.push(put_command(library, chosen, cut, land))
    tab = services.tabs.open("project", plan.id)
    nodes = tab._scene._nodes
    edit, menu = nodes[titled(plan, "Edit").id], nodes[titled(plan, "Menu").id]
    assert edit._accent.strip == "feature/stacks" and edit._accent.strip_tone
    assert nodes[land.id]._accent.strip == "feature/stacks"
    assert not menu._accent.strip and not nodes[cut.id]._accent.strip  # Main says nothing.
    assert edit.size()[1] == NODE_H + STRIP_H and menu.size()[1] == NODE_H
    assert edit.body_size()[1] == NODE_H  # What a resize stores.
    anchor = edit.anchor_toward(edit.scenePos() + edit.boundingRect().topRight())
    assert anchor.y() == edit.scenePos().y() + NODE_H / 2


def test_a_sort_leaves_a_card_on_a_branch_the_room_of_its_strip():
    from dplanner.domain.commands import SetEdgesCommand
    from dplanner.domain.model import Library, Project
    from dplanner.modules.project_editor.positions import STRIP_H, footprints, node_size
    from dplanner.modules.project_editor.sorts import layered_flow

    library = Library()
    project = Project(title="Sorted")
    library.add_child(library.id, project)
    for title in ("A", "B", "C"):
        library.add_child(project.id, Step(title=title))
    a, b, c = project.steps
    SetEdgesCommand(b.id, "requires", [a.id]).redo(library)
    SetEdgesCommand(c.id, "requires", [a.id]).redo(library)
    plain = layered_flow(library, project, node_size)
    stripped = layered_flow(library, project, footprints({b.id}))
    gap = abs(plain[c.id][1] - plain[b.id][1])
    assert abs(stripped[c.id][1] - stripped[b.id][1]) >= gap + STRIP_H
