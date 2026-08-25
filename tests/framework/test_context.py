"""The context graph: URIs in, questions out, scopes replaced wholesale."""

from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    SCOPE_SELECTION,
    Context,
    ContextNode,
    ContextService,
    activity_uri,
    entity_id_from_uri,
    entity_uri,
    parse_activity_uri,
    selection_uri,
)


def test_entity_uris_round_trip():
    uri = entity_uri("item", "abc")
    assert entity_id_from_uri(uri) == "abc"
    assert entity_id_from_uri(uri, kind="item") == "abc"
    assert entity_id_from_uri(uri, kind="task") is None


def test_activity_uris_round_trip():
    assert parse_activity_uri(activity_uri("editor", "abc")) == ("editor", "abc")
    assert parse_activity_uri(activity_uri("board")) == ("board", None)
    assert parse_activity_uri("app://entity/item/x") is None


def test_focus_prefers_the_selection_over_the_activity():
    context = Context(
        {
            SCOPE_ACTIVITY: (
                ContextNode(
                    activity_uri("editor", "open"),
                    edges=(("entity", entity_uri("item", "open")),),
                ),
            ),
            SCOPE_SELECTION: (ContextNode(selection_uri("item", "picked")),),
        }
    )
    assert context.focus_entity("item") == "picked"


def test_focus_falls_back_to_what_the_tab_is_about():
    """A menu item must work whether the user selected something or simply has it open."""
    context = Context(
        {
            SCOPE_ACTIVITY: (
                ContextNode(
                    activity_uri("editor", "open"),
                    edges=(("entity", entity_uri("item", "open")),),
                ),
            )
        }
    )
    assert context.focus_entity("item") == "open"


def test_focus_is_none_when_nothing_applies():
    assert Context({}).focus_entity("item") is None


def test_a_scope_is_replaced_not_merged():
    service = ContextService()
    service.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("item", "a")),))
    service.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("item", "b")),))
    assert service.current().selected_entities("item") == ["b"]


def test_clearing_an_empty_scope_emits_nothing():
    service = ContextService()
    seen: list[Context] = []
    service.changed.connect(seen.append)
    service.clear_scope(SCOPE_SELECTION)
    assert seen == []


def test_every_change_emits_a_fresh_snapshot():
    service = ContextService()
    seen = []
    service.changed.connect(lambda context: seen.append(context.selected_entities("item")))
    service.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("item", "a")),))
    service.clear_scope(SCOPE_SELECTION)
    assert seen == [["a"], []]
