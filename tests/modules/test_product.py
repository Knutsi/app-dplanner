"""The product tab: three fields, each an undoable command, and the window title."""


def activity(services):
    return services.tabs.open("product")


def test_the_action_opens_the_tab(services):
    services.actions.run("product.open", services.context.current())
    assert [a.uri for a in services.tabs.activities()] == ["app://activity/product"]


def test_editing_a_field_is_undoable(services):
    tab = activity(services)
    tab._fields["repository"].setText("git@example.com:widget.git")
    tab._fields["repository"].editingFinished.emit()
    assert services.document.repository == "git@example.com:widget.git"

    services.undo.undo()
    assert services.document.repository == ""


def test_a_change_made_elsewhere_reaches_the_field(services):
    """Origin is identity: the tab ignores its own echo and applies everyone else's."""
    tab = activity(services)
    services.document.set_field(services.document.id, "name", "Widget", origin=object())
    assert tab._fields["name"].text() == "Widget"


def test_the_field_ignores_its_own_echo(services):
    tab = activity(services)
    tab._fields["name"].setText("Typed")
    tab._fields["name"].editingFinished.emit()
    assert tab._fields["name"].text() == "Typed"


def test_the_window_says_which_product_it_holds(services):
    services.document.set_field(services.document.id, "name", "Widget")
    assert services.window.windowTitle() == "Widget — DPlanner"
