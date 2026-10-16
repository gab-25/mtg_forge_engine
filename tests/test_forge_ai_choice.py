import random

import pytest

from mtg_forge_engine.choices import ForgeAi, _next_pick
from mtg_forge_engine.formats import FORMATS
from mtg_forge_engine.queue import DecisionQueue
from mtg_forge_engine.settings import Settings
from tests.decks import GREEN, RED
from tests.helpers import external_seats, play_randomly


class Supplier:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def get(self):
        self.calls += 1
        return self.answer


def test_forge_ai_is_asked_once():
    supplier = Supplier(["a"])
    ai = ForgeAi(supplier)
    assert ai.get() == ["a"] and ai.get() == ["a"]
    assert supplier.calls == 1
    assert ForgeAi(None).get() is None


def test_next_pick_follows_the_answer_then_says_done():
    # options: 0 = Done, then the candidates
    assert _next_pick(["b", "c"], [], ["a", "b", "c"], 1, True) == 2
    assert _next_pick(["b", "c"], ["b"], ["a", "c"], 1, True) == 2
    assert _next_pick(["b", "c"], ["b", "c"], ["a"], 1, True) == 0


def test_next_pick_without_done():
    assert _next_pick(["c"], [], ["a", "b", "c"], 0, False) == 2
    # The client went elsewhere and what the AI wanted is gone: no answer.
    assert _next_pick(["c"], ["c"], ["a", "b"], 0, False) is None
    assert _next_pick(None, [], ["a"], 0, False) is None


def test_next_pick_counts_repeats():
    assert _next_pick(["m", "m"], ["m"], ["m", "n"], 1, True) == 1
    assert _next_pick(["m", "m"], ["m", "m"], ["m", "n"], 1, True) == 0


@pytest.fixture
def registry(forge):
    from mtg_forge_engine.registry import GameRegistry

    settings = Settings(max_concurrent_games=4, decision_timeout=30, max_turns=50, game_ttl=3600, forge_home=forge)
    return GameRegistry(settings, DecisionQueue(settings.decision_timeout))


@pytest.mark.jvm
def test_isolated_draws_leave_the_game_random_alone(forge):
    import jpype
    from jpype import JImplements, JOverride

    J = jpype.JClass
    J("forge.bridge.GameRandom").bindThisThread(42)
    game_random = J("forge.util.MyRandom").getRandom()

    @JImplements("java.util.function.Supplier")
    class Draw:
        @JOverride
        def get(self):
            return J("java.lang.Integer").valueOf(game_random.nextInt())

    reference = J("java.util.Random")(42)
    first = reference.nextInt()
    assert int(J("forge.bridge.GameRandom").isolated(Draw())) == first
    assert int(game_random.nextInt()) == first
    assert int(game_random.nextInt()) == int(reference.nextInt())


@pytest.mark.jvm
def test_decisions_carry_forge_ai_choice(registry):
    record = []
    for seed in (1, 2, 3):
        session = registry.create(FORMATS["modern"], seed, external_seats(RED, GREEN))
        play_randomly(registry.queue, session, random.Random(seed), record=record)
        assert session.status == "finished", session.error
        assert not [e for e in session.events_since(0)
                    if e["kind"] == "fallback" and e["payload"]["reason"] == "error"]
    for d in record:
        assert "forge_ai_choice" in d.as_dict()
        assert d.forge_ai_choice is None or 0 <= d.forge_ai_choice < len(d.options), d
    answered = {d.kind for d in record if d.forge_ai_choice is not None}
    assert {"mulligan", "priority", "attack", "block"} <= answered
    priority = [d for d in record if d.kind == "priority"]
    assert sum(d.forge_ai_choice is not None for d in priority) == len(priority)


@pytest.mark.jvm
def test_asking_the_ai_leaves_combat_alone(registry):
    """The view of a decision is built after the AI was asked: the first attack
    question shows no attackers, the first block question no blockers."""
    record = []
    for seed in (4, 5, 6):
        session = registry.create(FORMATS["modern"], seed, external_seats(RED, GREEN))
        play_randomly(registry.queue, session, random.Random(seed), record=record)
    first_attacks = [d for d in record if d.kind == "attack" and "(attacking:" not in d.prompt]
    assert any(d.forge_ai_choice not in (None, 0) for d in first_attacks)
    for d in first_attacks:
        assert not (d.view["combat"] or {}).get("attackers"), d.view["combat"]
    first_blocks = [d for previous, d in zip([None] + record, record)
                    if d.kind == "block" and (previous is None or previous.kind != "block")]
    assert any(d.forge_ai_choice not in (None, 0) for d in first_blocks)
    for d in first_blocks:
        assert not any(a["blocked_by"] for a in d.view["combat"]["attackers"]), d.view["combat"]


def follow_forge_ai(queue, session, timeout=300):
    """A client that picks what Forge's AI would, or the first option."""
    import time

    answers = []
    deadline = time.monotonic() + timeout
    while session.status in ("queued", "running"):
        assert time.monotonic() < deadline, f"game {session.id} did not finish"
        decision = queue.lease(0.2, session.id)
        if decision is None:
            continue
        choice = decision.forge_ai_choice or 0
        answers.append((decision.seat, decision.kind, decision.prompt, choice))
        queue.answer(decision.id, choice)
    return answers


@pytest.mark.jvm
def test_a_seed_replays_the_same_game(registry):
    runs = []
    for _ in range(2):
        session = registry.create(FORMATS["modern"], 7, external_seats(RED, GREEN))
        answers = follow_forge_ai(registry.queue, session)
        assert session.status == "finished", session.error
        logs = [e["text"] for e in session.events_since(0)
                if e["kind"] == "log" and not e["text"].startswith("Match Duration")]
        runs.append((answers, logs, session.winner))
    assert runs[0] == runs[1]
