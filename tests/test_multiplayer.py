import random

import pytest

from mtg_forge_engine.formats import FORMATS
from mtg_forge_engine.queue import DecisionQueue
from mtg_forge_engine.settings import Settings
from tests.decks import COMMANDER
from tests.helpers import play_randomly, pod_seats

pytestmark = pytest.mark.jvm


@pytest.fixture
def registry(forge):
    from mtg_forge_engine.registry import GameRegistry

    settings = Settings(max_concurrent_games=4, decision_timeout=30, max_turns=15, game_ttl=3600, forge_home=forge)
    return GameRegistry(settings, DecisionQueue(settings.decision_timeout))


def test_commander_damage_eliminates(registry):
    session = registry.create(FORMATS["commander"], 21, pod_seats(3, COMMANDER))
    rng = random.Random(21)
    dealt = False
    while session.status in ("queued", "running"):
        decision = registry.queue.lease(0.2, session.id)
        if decision is None:
            continue
        if not dealt and decision.kind == "priority":
            # The game thread is parked on this decision: Forge is not running.
            commander = list(session.player(1).getCommanders())[0]
            session.player(0).addCommanderDamage(commander, 21)
            dealt = True
        registry.queue.answer(decision.id, rng.randrange(len(decision.options)))
    assert session.status == "finished", session.error
    first = session.eliminations[0]
    assert (first["seat"], first["reason"]) == (0, "CommanderDamage")
    assert first["turn"] >= 1
    game_over = session.events_since(0)[-1]
    assert game_over["kind"] == "game_over"
    assert game_over["payload"]["eliminations"] == session.eliminations
    assert session.summary()["eliminations"] == session.eliminations


def test_ai_pod_records_every_elimination(registry):
    for seed in range(30, 40):
        session = registry.create(FORMATS["commander"], seed, pod_seats(4, COMMANDER, controller="forge_ai"))
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
