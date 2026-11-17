import pytest

from mtg_forge_engine.formats import FORMATS
from mtg_forge_engine.settings import Settings
from tests.decks import GREEN, RED
from tests.helpers import duel_seats

pytestmark = pytest.mark.jvm


def make_registry(forge, **overrides):
    from mtg_forge_engine.registry import GameRegistry

    values = dict(max_concurrent_games=4, max_turns=50, game_ttl=3600, forge_home=forge)
    values.update(overrides)
    return GameRegistry(Settings(**values))


def test_eight_games_four_slots(forge):
    registry = make_registry(forge)
    sessions = [registry.create(FORMATS["modern"], 100 + i, duel_seats(RED, GREEN)) for i in range(8)]
    for s in sessions:
        s.join(600)
    assert [s.status for s in sessions] == ["finished"] * 8, [s.error for s in sessions]
    for s in sessions:
        events = s.events_since(0)
        assert events[-1]["kind"] == "game_over"
        assert [e["seq"] for e in events] == list(range(len(events)))


def test_same_seed_replays_the_same_game(forge):
    def run(seed):
        registry = make_registry(forge)
        session = registry.create(FORMATS["modern"], seed, duel_seats(RED, GREEN))
        session.join(300)
        return [(e["kind"], e["text"]) for e in session.events_since(0)]

    first = run(4242)
    assert first == run(4242)
    assert first != run(4243)


def test_turn_limit_ends_in_a_draw(forge):
    registry = make_registry(forge, max_turns=2)
    session = registry.create(FORMATS["modern"], 7, duel_seats(RED, GREEN))
    session.join(300)
    assert session.status == "finished"
    assert session.end_reason == "turn_limit"
    assert session.winner is None
    assert session.turn <= 3
