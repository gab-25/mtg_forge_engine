import threading

import pytest

from forge_bridge.decklist import parse_decklist
from forge_bridge.formats import FORMATS
from forge_bridge.queue import DecisionQueue
from forge_bridge.registry import unique_names
from forge_bridge.settings import Settings
from tests.decks import GREEN, RED


def test_unique_names():
    assert unique_names(["Red", "Red"]) == ["Red (seat 1)", "Red (seat 2)"]
    assert unique_names(["Red", "Green"]) == ["Red", "Green"]


@pytest.fixture
def registry(forge):
    from forge_bridge.registry import GameRegistry

    settings = Settings(max_concurrent_games=4, decision_timeout=30, max_turns=50, game_ttl=3600, forge_home=forge)
    return GameRegistry(settings, DecisionQueue(settings.decision_timeout))


def seats(controller_a="forge_ai", controller_b="forge_ai", deck_a=RED, deck_b=GREEN, names=("Red", "Green")):
    from forge_bridge.decks import build_deck
    from forge_bridge.session import SeatSpec

    return [
        SeatSpec(names[0], build_deck(names[0], parse_decklist(deck_a), commander=False).deck, controller_a),
        SeatSpec(names[1], build_deck(names[1], parse_decklist(deck_b), commander=False).deck, controller_b),
    ]


@pytest.mark.jvm
def test_ai_vs_ai_game_finishes(registry):
    session = registry.create(FORMATS["modern"], 7, seats())
    session.join(300)
    assert session.status == "finished", session.error
    kinds = {e["kind"] for e in session.events_since(0)}
    assert {"log", "game_over"} <= kinds
    assert session.winner in (0, 1, None)
    assert session.end_reason
    assert [e["seq"] for e in session.events_since(0)] == list(range(len(session.events_since(0))))


@pytest.mark.jvm
def test_log_events_carry_the_turn_they_happened_in(registry):
    session = registry.create(FORMATS["modern"], 8, seats())
    session.join(300)
    logs = [e for e in session.events_since(0) if e["kind"] == "log"]
    first_turn = next(e for e in logs if e["text"].startswith("Turn 1 "))
    assert first_turn["turn"] == 1
    assert logs[0]["turn"] == 0  # mulligans happen before turn 1
    turns = [e["turn"] for e in logs]
    assert turns == sorted(turns)


@pytest.mark.jvm
def test_mirror_match_winner_maps_to_a_seat(registry):
    session = registry.create(FORMATS["modern"], 3, seats(deck_b=RED, names=("Red", "Red")))
    session.join(300)
    assert [s.name for s in session.seats] == ["Red (seat 1)", "Red (seat 2)"]
    assert session.status == "finished", session.error
    if session.winner is not None:
        assert session.events_since(0)[-1]["payload"]["winner"] == session.winner


@pytest.mark.jvm
def test_registry_get_and_abort_before_start(registry):
    blocked = threading.BoundedSemaphore(1)
    blocked.acquire()  # no free slot: the game stays queued
    registry._slots = blocked
    session = registry.create(FORMATS["modern"], 1, seats())
    assert registry.get(session.id) is session
    assert session.status == "queued"
    assert registry.abort(session.id)
    blocked.release()
    session.join(30)
    assert session.status == "aborted"
    assert registry.get("missing") is None
