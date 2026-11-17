import threading

import pytest

from mtg_forge_engine.formats import FORMATS
from mtg_forge_engine.registry import unique_names
from mtg_forge_engine.settings import Settings
from tests.decks import GREEN, RED
from tests.helpers import duel_seats, wait_for


def test_unique_names():
    assert unique_names(["Red", "Red"]) == ["Red (seat 1)", "Red (seat 2)"]
    assert unique_names(["Red", "Green"]) == ["Red", "Green"]


@pytest.fixture
def registry(forge):
    from mtg_forge_engine.registry import GameRegistry

    return GameRegistry(Settings(max_concurrent_games=4, max_turns=50, game_ttl=3600, forge_home=forge))


def seats(deck_a=RED, deck_b=GREEN, names=("Red", "Green")):
    return duel_seats(deck_a, deck_b, names=names)


@pytest.mark.jvm
def test_ai_vs_ai_game_finishes(registry):
    session = registry.create(FORMATS["modern"], 7, seats())
    session.join(300)
    assert session.status == "finished", session.error
    events = session.events_since(0)
    assert {e["kind"] for e in events} == {"log", "game_over"}
    assert events[-1]["kind"] == "game_over"
    assert events[-1]["payload"]["winner"] == session.winner
    assert session.winner in (0, 1, None)
    assert session.end_reason
    if session.winner is not None:
        assert [e["seat"] for e in session.eliminations] == [1 - session.winner]
    assert [e["seq"] for e in events] == list(range(len(events)))
    assert session.game is None  # released


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


@pytest.mark.jvm
def test_abort_ends_a_running_game_on_the_game_thread(forge):
    from mtg_forge_engine.registry import GameRegistry

    # Green against green: long games, still running when aborted.
    registry = GameRegistry(Settings(max_concurrent_games=4, max_turns=200, game_ttl=3600, forge_home=forge))
    for seed in (11, 12, 13):
        session = registry.create(FORMATS["modern"], seed, seats(deck_a=GREEN, names=("G1", "G2")))
        wait_for(lambda: session.status not in ("queued", "running")
                 or (session.status == "running" and session.turn >= 2), what="turn 2")
        if session.status == "running":
            break
    assert session.status == "running", "every game ended before turn 2: the test proves nothing"
    turn = session.turn
    assert registry.abort(session.id)
    session.join(60)
    assert session.status == "aborted", session.error
    assert session.end_reason == "aborted"
    assert session.winner is None
    assert session.turn <= turn + 1
    game_over = session.events_since(0)[-1]
    assert game_over["kind"] == "game_over" and game_over["payload"]["end_reason"] == "aborted"
