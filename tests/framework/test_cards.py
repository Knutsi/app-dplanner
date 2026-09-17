"""Cards flow into as many columns as the width allows, and back into one."""

import pytest
from PySide6.QtWidgets import QLabel

from dplanner.framework.cards import CARD_MIN_WIDTH, STACK_MARGIN, STACK_SPACING, CardFlow, ToolCard


def settle(flow: CardFlow) -> None:
    """Lay the grid out now, as a shown widget would on its next paint."""
    content = flow.widget()
    assert content is not None
    layout = content.layout()
    assert layout is not None
    layout.activate()


@pytest.fixture
def flow(app):
    made = CardFlow()
    for title in ("One", "Two", "Three", "Four"):
        made.add_card(ToolCard(title, QLabel(title)))
    made.show()  # A hidden widget's resize is only delivered when it is shown.
    yield made
    made.deleteLater()


def test_a_panels_width_is_one_column(flow):
    flow.resize(CARD_MIN_WIDTH + 2 * STACK_MARGIN, 600)
    assert flow.columns() == 1


def test_a_wide_page_is_as_many_columns_as_fit(flow):
    flow.resize(3 * CARD_MIN_WIDTH + 2 * STACK_SPACING + 2 * STACK_MARGIN, 600)
    assert flow.columns() == 3
    # One pixel short of the third column's room, and it is two again.
    flow.resize(3 * CARD_MIN_WIDTH + 2 * STACK_SPACING + 2 * STACK_MARGIN - 1, 600)
    assert flow.columns() == 2


def test_a_card_that_grows_takes_the_leftover_height_and_its_neighbour_does_not(app):
    """A prose editor wants the page; a list of facts beside it must not become a tall
    empty box. The row stretches, and only the growing card fills it."""
    from PySide6.QtWidgets import QPlainTextEdit

    flow = CardFlow()
    facts = ToolCard("Facts", QLabel("three lines"))
    prose = ToolCard("Prose", QPlainTextEdit())
    flow.add_card(facts)
    flow.add_card(prose, grows=True)
    flow.show()
    try:
        flow.resize(2 * CARD_MIN_WIDTH + STACK_SPACING + 2 * STACK_MARGIN, 700)
        settle(flow)
        assert prose.height() > 400
        assert facts.height() < 200
    finally:
        flow.deleteLater()


def test_the_cards_keep_their_order_across_a_reflow(flow):
    flow.resize(2 * CARD_MIN_WIDTH + STACK_SPACING + 2 * STACK_MARGIN, 600)
    settle(flow)
    cards = [card for card, _grows in flow._cards]
    # Row by row, left to right: the third card starts the second row.
    assert cards[2].geometry().top() > cards[0].geometry().top()
    assert cards[1].geometry().left() > cards[0].geometry().left()
    assert cards[2].geometry().left() == cards[0].geometry().left()
