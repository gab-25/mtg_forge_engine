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
