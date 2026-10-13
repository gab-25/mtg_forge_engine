import random

import pytest

from forge_bridge.formats import FORMATS
from forge_bridge.queue import DecisionQueue
from forge_bridge.settings import Settings
from tests.decks import GREEN, RED
from tests.helpers import external_seats, play_randomly

pytestmark = pytest.mark.jvm


@pytest.fixture
def registry(forge):
    from forge_bridge.registry import GameRegistry

    settings = Settings(max_concurrent_games=4, decision_timeout=30, max_turns=50, game_ttl=3600, forge_home=forge)
    return GameRegistry(settings, DecisionQueue(settings.decision_timeout))


def test_delegating_client_game_finishes(registry):
    session = registry.create(FORMATS["modern"], 11, external_seats(RED, GREEN))
    while session.status in ("queued", "running"):
        decision = registry.queue.lease(0.2, session.id)
        if decision is not None:
            registry.queue.answer(decision.id, delegate=True)
    assert session.status == "finished", session.error
    kinds = {e["kind"] for e in session.events_since(0)}
    assert {"fallback", "forge_ai", "game_over"} <= kinds


def test_mulligan_decisions_with_view(registry):
    record = []
    session = registry.create(FORMATS["modern"], 12, external_seats(RED, GREEN))
    play_randomly(registry.queue, session, random.Random(1), record=record)
    assert session.status == "finished", session.error
    mulligans = [d for d in record if d.kind == "mulligan"]
    assert mulligans
    first = mulligans[0]
    assert [o["index"] for o in first.options] == [0, 1]
    view = first.view
    assert view["you"]["seat"] == first.seat
    assert len(view["you"]["hand"]) == 7
    assert isinstance(view["opponents"][0]["hand"], int)  # hidden: only a count
    assert view["format"] == "Modern"
    cards = [c for d in mulligans for c in d.view["you"]["hand"]]
    assert all("\\n" not in c["text"] for c in cards)
    lands = [c for c in cards if "Land" in c["types"]]
    assert lands and all(c["mana_cost"] == "" for c in lands)


def test_bottom_follows_a_mulligan(registry):
    record = []
    session = registry.create(FORMATS["modern"], 13, external_seats(RED, GREEN))

    rng = random.Random(2)
    seen = set()
    while session.status in ("queued", "running"):
        decision = registry.queue.lease(0.2, session.id)
        if decision is None:
            continue
        record.append(decision)
        if decision.kind == "mulligan" and decision.seat not in seen:
            seen.add(decision.seat)
            registry.queue.answer(decision.id, 1)
        else:
            registry.queue.answer(decision.id, rng.randrange(len(decision.options)))
    assert any(d.kind == "bottom" for d in record)


def test_too_many_options_delegates(registry):
    import threading

    from forge_bridge.session import GameSession, Option

    # A session whose game has not started: ask() reaches the option-count check.
    session = GameSession("t", FORMATS["modern"], 1, [], registry.queue, 50, threading.BoundedSemaphore(1))
    assert session.ask(0, "priority", "p", [Option(str(i)) for i in range(256)]) is None
    assert session.events_since(0)[-1]["payload"]["reason"] == "too_many_options"


def test_ended_game_releases_forge_objects(registry):
    """A Python handler and the Forge game reference each other across the JVM
    boundary; neither garbage collector can break that cycle, so it is cut."""
    session = registry.create(FORMATS["modern"], 15, external_seats(RED, GREEN))
    play_randomly(registry.queue, session, random.Random(15))
    assert session.status == "finished"
    assert session.game is None
    assert session.handlers and all(h.session is None for h in session.handlers)
    assert session.summary()["turn"] > 0


def test_abort_ends_the_game_on_its_own_thread(registry):
    """Forge's Game is not thread-safe: an abort from a request thread must leave
    ending the game to the game thread."""
    import threading

    session = registry.create(FORMATS["modern"], 16, external_seats(RED, GREEN))
    decision = registry.queue.lease(30, session.id)
    callers = []

    class RecordingGame:
        def __init__(self, game):
            self._real = game

        def setGameOver(self, reason):
            callers.append(threading.current_thread().name)
            return self._real.setGameOver(reason)

        def __getattr__(self, name):
            return getattr(self._real, name)

    session._game = RecordingGame(session._game)  # the game thread is parked on `decision`
    session.abort()
    session.join(30)
    assert session.status == "aborted"
    assert callers and set(callers) == {f"game-{session.id}"}
    assert decision.answer.reason == "withdrawn"
