import time

from forge_bridge.decklist import parse_decklist


def external_seats(deck_a, deck_b, names=("A", "B"), controllers=("external", "external"), commander=False):
    from forge_bridge.decks import build_deck
    from forge_bridge.session import SeatSpec

    return [
        SeatSpec(names[0], build_deck(names[0], parse_decklist(deck_a), commander=commander).deck, controllers[0]),
        SeatSpec(names[1], build_deck(names[1], parse_decklist(deck_b), commander=commander).deck, controllers[1]),
    ]


def play_randomly(queue, session, rng, *, record=None, timeout=300):
    """A client that answers every decision of one game with a random option."""
    deadline = time.monotonic() + timeout
    while session.status in ("queued", "running"):
        assert time.monotonic() < deadline, f"game {session.id} did not finish"
        decision = queue.lease(0.2, session.id)
        if decision is None:
            continue
        if record is not None:
            record.append(decision)
        queue.answer(decision.id, rng.randrange(len(decision.options)))
    return session
