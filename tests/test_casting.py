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


def test_cards_are_never_stranded_in_the_stack_zone(registry):
    """A spell the client cannot target (Giant Growth with no creature) must not vanish."""
    import jpype

    stack_zone = jpype.JClass("forge.game.zone.ZoneType").Stack
    for seed in (1, 2, 11, 14):
        session = registry.create(FORMATS["modern"], seed, external_seats(RED, GREEN))
        rng = random.Random(seed)
        while session.status in ("queued", "running"):
            decision = registry.queue.lease(0.2, session.id)
            if decision is None:
                continue
            if decision.kind != "priority":
                # While targets are chosen the spell's card is already in the stack zone.
                registry.queue.answer(decision.id, rng.randrange(len(decision.options)))
                continue
            game = session.game  # the game thread is parked on this decision
            stranded = game.getCardsIn(stack_zone).size() - game.getStack().size()
            assert stranded <= 0, f"seed {seed}: {stranded} card(s) in the Stack zone but not on the stack"
            registry.queue.answer(decision.id, rng.randrange(len(decision.options)))
        assert session.status == "finished", session.error


def test_spells_without_legal_targets_are_not_offered(registry):
    offered_without_target = []
    for seed in (1, 2, 11, 14):
        record = []
        session = registry.create(FORMATS["modern"], seed, external_seats(RED, GREEN))
        play_randomly(registry.queue, session, random.Random(seed), record=record)
        for decision in record:
            if decision.kind != "priority":
                continue
            creatures = [p for perms in decision.view["battlefield"].values() for p in perms if "power" in p]
            if not creatures:
                offered_without_target += [o["label"] for o in decision.options
                                           if o["label"].startswith("Cast Giant Growth")]
    assert offered_without_target == []


# Forge's AI casts Izzet Charm readily (it never casts Fiery Confluence).
IZZET_CHARMS = """
12 Mountain
12 Island
36 Izzet Charm
"""


def test_modes_of_a_spell_forge_casts_stay_with_forge(registry):
    """When Forge's AI casts a modal spell (a delegated priority), it has already
    picked and targeted the modes: the client must not be asked for them."""
    record = []
    session = registry.create(FORMATS["modern"], 18, external_seats(IZZET_CHARMS, GREEN))
    rng = random.Random(18)
    while session.status in ("queued", "running"):
        decision = registry.queue.lease(0.2, session.id)
        if decision is None:
            continue
        record.append(decision)
        if decision.seat == 0 and decision.kind == "priority":
            registry.queue.answer(decision.id, delegate=True)
        else:
            registry.queue.answer(decision.id, rng.randrange(len(decision.options)))
    assert session.status == "finished", session.error
    cast = [e for e in session.events_since(0) if e["kind"] == "log" and "cast Izzet Charm" in e["text"]]
    assert cast, "the AI never cast Izzet Charm: the test proves nothing"
    assert [d.prompt for d in record if d.seat == 0 and d.kind == "mode"] == []
