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


def test_priority_options(registry):
    record = []
    session = registry.create(FORMATS["modern"], 21, external_seats(RED, GREEN))
    play_randomly(registry.queue, session, random.Random(3), record=record)
    assert session.status == "finished", session.error
    priority = [d for d in record if d.kind == "priority"]
    assert priority
    assert all(d.options[0]["label"] == "Pass priority" for d in priority)
    labels = [o["label"] for d in priority for o in d.options[1:]]
    assert any(label.startswith("Play ") for label in labels)
    assert any(label.startswith("Cast ") for label in labels)
    played = [e for e in session.events_since(0) if e["kind"] == "decision" and e["payload"]["kind"] == "priority"
              and e["payload"]["choice"] > 0]
    assert played


def test_targets_modes_and_confirm_come_up(registry):
    """Random clients over a few games meet targeting, modes and confirmations."""
    seen = set()
    for seed in range(30, 40):
        record = []
        session = registry.create(FORMATS["modern"], seed, external_seats(RED, GREEN))
        play_randomly(registry.queue, session, random.Random(seed), record=record)
        assert session.status == "finished", session.error
        seen |= {d.kind for d in record}
        if {"target", "mode", "confirm"} <= seen:
            break
    assert {"target", "mode", "confirm"} <= seen, seen


def test_target_decision_shape(registry):
    record = []
    for seed in range(40, 46):
        session = registry.create(FORMATS["modern"], seed, external_seats(RED, GREEN))
        play_randomly(registry.queue, session, random.Random(seed), record=record)
        if any(d.kind == "target" for d in record):
            break
    target = next(d for d in record if d.kind == "target")
    assert target.prompt.startswith("Choose a target for ")
    assert all(o["label"] for o in target.options)
