import pytest

from mtg_forge_engine.formats import FORMATS
from mtg_forge_engine.settings import Settings
from tests.decks import COMMANDER
from tests.helpers import pod_seats, wait_for

pytestmark = pytest.mark.jvm


def make_registry(forge, max_turns=15):
    from mtg_forge_engine.registry import GameRegistry

    return GameRegistry(Settings(max_concurrent_games=4, max_turns=max_turns, game_ttl=3600, forge_home=forge))


def test_ai_pod_records_every_elimination(forge):
    registry = make_registry(forge)
    for seed in range(30, 40):
        session = registry.create(FORMATS["commander"], seed, pod_seats(4, COMMANDER))
        session.join(600)
        assert session.status == "finished", session.error
        if session.winner is not None:
            break
    assert session.winner is not None, "no seed in 30-39 produced a winner"
    eliminated = [e["seat"] for e in session.eliminations]
    assert sorted(eliminated) == sorted(set(range(4)) - {session.winner})
    turns = [e["turn"] for e in session.eliminations]
    assert turns == sorted(turns)
    assert 1 <= turns[0] and turns[-1] <= session.turn
    assert all(e["reason"] for e in session.eliminations)
    game_over = session.events_since(0)[-1]
    assert game_over["kind"] == "game_over"
    assert game_over["payload"]["eliminations"] == session.eliminations
    assert session.summary()["eliminations"] == session.eliminations


def test_three_seat_pod_plays_to_the_end(forge):
    registry = make_registry(forge)
    session = registry.create(FORMATS["commander"], 40, pod_seats(3, COMMANDER))
    session.join(900)
    assert session.status == "finished", session.error
    assert session.winner is not None or session.end_reason == "turn_limit"
    eliminated = [e["seat"] for e in session.eliminations]
    assert len(eliminated) == len(set(eliminated))
    assert session.winner not in eliminated
    if session.winner is not None:
        assert len(eliminated) == 2


def test_turn_cap_counts_rounds_in_a_pod(forge):
    registry = make_registry(forge, max_turns=2)  # 6 game turns for 3 seats
    session = registry.create(FORMATS["commander"], 23, pod_seats(3, COMMANDER))
    session.join(300)
    assert session.status == "finished", session.error
    assert session.end_reason == "turn_limit"
    assert session.winner is None
    assert 6 <= session.turn <= 7


def test_abort_ends_a_pod(forge):
    registry = make_registry(forge, max_turns=50)
    session = registry.create(FORMATS["commander"], 24, pod_seats(4, COMMANDER))
    wait_for(lambda: session.status not in ("queued", "running")
             or (session.status == "running" and session.turn >= 2), what="turn 2")
    assert session.status == "running"
    turn = session.turn
    session.abort()
    session.join(60)
    assert session.status == "aborted", session.error
    assert session.end_reason == "aborted"
    assert session.turn <= turn + 1
