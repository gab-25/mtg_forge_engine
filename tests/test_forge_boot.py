import pytest

from forge_bridge.decklist import parse_decklist
from tests.decks import DUEL_COMMANDER, RED

pytestmark = pytest.mark.jvm


def test_forge_loads_the_card_database(forge):
    from forge_bridge import jvm

    assert jvm.is_ready()
    assert jvm.card_count() > 20000


def test_build_deck(forge):
    from forge_bridge.decks import build_deck

    build = build_deck("Red", parse_decklist(RED), commander=False)
    assert build.unresolved == []
    assert build.deck.getMain().countAll() == 60


def test_unknown_cards_are_reported(forge):
    from forge_bridge.decks import build_deck

    build = build_deck("X", parse_decklist("4 Lightning Bolt\n2 Not A Real Card"), commander=False)
    assert build.unresolved == ["Not A Real Card"]


def test_split_and_double_faced_names_resolve(forge):
    from forge_bridge.decks import build_deck

    build = build_deck("X", parse_decklist("1 Fire // Ice\n1 Brazen Borrower // Petty Theft"), commander=False)
    assert build.unresolved == []
    assert build.deck.getMain().countAll() == 2


def test_commander_section(forge):
    from forge_bridge.decks import build_deck

    build = build_deck("Krenko", parse_decklist(DUEL_COMMANDER), commander=True)
    assert build.unresolved == []
    assert build.deck.getCommanders().size() == 1
    assert build.deck.getMain().countAll() == 100 - 1
