import time

from mtg_forge_engine.decklist import parse_decklist


def duel_seats(deck_a, deck_b, names=("A", "B"), commander=False):
    from mtg_forge_engine.decks import build_deck
    from mtg_forge_engine.session import SeatSpec

    return [SeatSpec(name, build_deck(name, parse_decklist(deck), commander=commander).deck)
            for name, deck in zip(names, (deck_a, deck_b))]


def pod_seats(count, decklist):
    """A Commander pod of `count` seats named A, B, C, D, all playing `decklist`."""
    from mtg_forge_engine.decks import build_deck
    from mtg_forge_engine.session import SeatSpec

    return [SeatSpec(name, build_deck(name, parse_decklist(decklist), commander=True).deck)
            for name in "ABCD"[:count]]


def wait_for(condition, timeout=60, what="condition"):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.05)
