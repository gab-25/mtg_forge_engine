import random

import pytest

from mtg_forge_engine.formats import FORMATS
from mtg_forge_engine.queue import DecisionQueue
from mtg_forge_engine.settings import Settings
from tests.decks import GREEN, RED
from tests.helpers import external_seats, play_randomly

pytestmark = pytest.mark.jvm


@pytest.fixture
def registry(forge):
    from mtg_forge_engine.registry import GameRegistry

    settings = Settings(max_concurrent_games=4, decision_timeout=30, max_turns=50, game_ttl=3600, forge_home=forge)
    return GameRegistry(settings, DecisionQueue(settings.decision_timeout))


@pytest.fixture
def simulating_registry(forge):
    from mtg_forge_engine.registry import GameRegistry

    settings = Settings(max_concurrent_games=4, decision_timeout=30, max_turns=50, game_ttl=3600, forge_home=forge,
                        simulate=True)
    return GameRegistry(settings, DecisionQueue(settings.decision_timeout))


def play_until(registry, kinds, seeds):
    record = []
    for seed in seeds:
        session = registry.create(FORMATS["modern"], seed, external_seats(RED, GREEN))
        play_randomly(registry.queue, session, random.Random(seed), record=record)
        assert session.status == "finished", session.error
        if kinds <= {d.kind for d in record}:
            break
    return record


def test_attack_and_block_decisions(registry):
    record = play_until(registry, {"attack", "block"}, range(50, 60))
    attack = next(d for d in record if d.kind == "attack")
    assert attack.options[0]["label"] == "Done (no more attackers)"
    assert all(o["label"].startswith("Attack with ") for o in attack.options[1:])
    assert all(any(f.startswith("deals ") for f in o["facts"]) for o in attack.options[1:])
    block = next(d for d in record if d.kind == "block")
    assert block.options[0]["label"] == "Done (no more blockers)"
    assert all(len(o["facts"]) == 2 for o in block.options[1:])


def test_card_choices(registry):
    record = play_until(registry, {"choose_cards"}, range(60, 70))
    choose = next(d for d in record if d.kind == "choose_cards")
    assert choose.options


def test_every_exposed_kind_comes_up(registry):
    record = play_until(registry, {"mulligan", "bottom", "priority", "target", "attack", "block",
                                   "choose_cards", "confirm", "mode"}, range(70, 85))
    assert {"mulligan", "bottom", "priority", "target", "attack", "block", "choose_cards", "confirm",
            "mode"} <= {d.kind for d in record}


def test_simulated_attack_decisions_are_whole_plans_with_outcomes(simulating_registry):
    record = play_until(simulating_registry, {"attack"}, range(50, 60))
    attack = next(d for d in record if d.kind == "attack")
    assert attack.as_dict()["simulated"] and attack.options[0]["label"] == "No attack"
    assert all(o["label"].startswith("Attack with ") for o in attack.options[1:])
    assert any(o["outcome"] and o["outcome"]["opponents"][0]["life"][1] < o["outcome"]["opponents"][0]["life"][0]
               for o in attack.options[1:])
    assert attack.options[0]["outcome"]["summary"] == "no change"
    assert len(attack.options) <= 8
    assert all(len(d.options) > 1 for d in record if d.kind == "attack")  # one question per combat, never a follow-up


def test_simulated_block_decisions_are_whole_plans(simulating_registry):
    record = play_until(simulating_registry, {"block"}, range(50, 70))
    block = next(d for d in record if d.kind == "block")
    assert block.options[0]["label"] == "No block" and block.as_dict()["simulated"]
    assert all(o["label"].startswith("Block ") for o in block.options[1:])
    assert block.prompt.startswith("Declare your blocks (unblocked attackers deal ")
    no_block = block.options[0]["outcome"]
    assert no_block["you"]["life"][1] <= no_block["you"]["life"][0]  # unblocked damage lands in the outcome
    assert all(len(d.options) > 1 for d in record if d.kind == "block")
