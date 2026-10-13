import random
import re

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


BLOCK_LABEL = re.compile(r"^Block .*? #(\d+)")


def test_four_seat_pod_plays_to_the_end(registry):
    record = []
    session = registry.create(FORMATS["commander"], 40, pod_seats(4, COMMANDER))
    play_randomly(registry.queue, session, random.Random(40), record=record, timeout=900)
    assert session.status == "finished", session.error
    assert session.winner is not None or session.end_reason == "turn_limit"
    assert {d.seat for d in record} == {0, 1, 2, 3}
    eliminated = [e["seat"] for e in session.eliminations]
    assert len(eliminated) == len(set(eliminated))
    assert session.winner not in eliminated
    if session.winner is not None:
        assert len(eliminated) == 3
    first = record[0].view
    assert first["you"]["life"] == 40 and first["you"]["in_game"] is True
    assert len(first["opponents"]) == 3
    assert all(o["in_game"] is True and o["commander_damage"] == [] for o in first["opponents"])
    for elimination in session.eliminations:
        later = [d.view for d in record if d.view["turn"] > elimination["turn"]]
        for view in later:
            gone = next(o for o in view["opponents"] if o["seat"] == elimination["seat"])
            assert gone["in_game"] is False
            assert view["battlefield"][str(elimination["seat"])] == []


def test_blocks_only_offer_attackers_attacking_you(registry):
    blocks = []
    for seed in range(50, 60):
        record = []
        session = registry.create(FORMATS["commander"], seed, pod_seats(3, COMMANDER))
        play_randomly(registry.queue, session, random.Random(seed), record=record, timeout=900)
        blocks += [d for d in record if d.kind == "block"]
        if blocks:
            break
    assert blocks, "no block decision in seeds 50-59"
    for decision in blocks:
        attacking = {a["id"]: a["defender_seat"] for a in decision.view["combat"]["attackers"]}
        for option in decision.options[1:]:
            attacker = int(BLOCK_LABEL.match(option["label"]).group(1))
            assert attacking[attacker] == decision.seat


def test_commander_damage_in_the_view(registry):
    session = registry.create(FORMATS["commander"], 22, pod_seats(3, COMMANDER))
    rng = random.Random(22)
    dealt = False
    seen = None
    while session.status in ("queued", "running"):
        decision = registry.queue.lease(0.2, session.id)
        if decision is None:
            continue
        if dealt and decision.seat != 0:
            seen = decision.view
            session.abort()  # withdraws this decision
            break
        if not dealt and decision.kind == "priority":
            session.player(0).addCommanderDamage(list(session.player(1).getCommanders())[0], 7)
            dealt = True
        registry.queue.answer(decision.id, rng.randrange(len(decision.options)))
    session.join(60)
    target = next(o for o in seen["opponents"] if o["seat"] == 0)
    [entry] = target["commander_damage"]
    assert (entry["commander"], entry["seat"], entry["damage"]) == ("Krenko, Mob Boss", 1, 7)


def test_first_mulligan_is_free_in_a_pod(registry):
    session = registry.create(FORMATS["commander"], 41, pod_seats(3, COMMANDER))
    rng = random.Random(41)
    mulligans = []
    while session.status in ("queued", "running") and len(mulligans) < 2:
        decision = registry.queue.lease(0.2, session.id)
        if decision is None:
            continue
        if decision.kind == "mulligan" and decision.seat == 0:
            mulligans.append(decision)
            registry.queue.answer(decision.id, 1 if len(mulligans) == 1 else 0)
        else:
            registry.queue.answer(decision.id, rng.randrange(len(decision.options)))
    session.abort()
    session.join(60)
    assert len(mulligans) == 2
    assert mulligans[1].options[0]["label"] == "Keep this hand"  # nothing to put on the bottom
    assert len(mulligans[1].view["you"]["hand"]) == 7
