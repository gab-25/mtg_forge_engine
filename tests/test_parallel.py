import random
import threading
import time

import pytest

from forge_bridge.formats import FORMATS
from forge_bridge.queue import DecisionQueue
from forge_bridge.settings import Settings
from tests.decks import GREEN, RED
from tests.helpers import external_seats, play_randomly

pytestmark = pytest.mark.jvm


def make_registry(forge, **overrides):
    from forge_bridge.registry import GameRegistry

    values = dict(max_concurrent_games=8, decision_timeout=30, max_turns=50, game_ttl=3600, forge_home=forge)
    values.update(overrides)
    settings = Settings(**values)
    return GameRegistry(settings, DecisionQueue(settings.decision_timeout))


def test_eight_games_four_workers(forge):
    registry = make_registry(forge)
    sessions = [registry.create(FORMATS["modern"], 100 + i, external_seats(RED, GREEN)) for i in range(8)]
    rngs = {s.id: random.Random(s.seed) for s in sessions}
    lock = threading.Lock()

    def worker():
        deadline = time.monotonic() + 600
        while any(s.status in ("queued", "running") for s in sessions) and time.monotonic() < deadline:
            decision = registry.queue.lease(0.2)
            if decision is None:
                continue
            with lock:
                choice = rngs[decision.game_id].randrange(len(decision.options))
            registry.queue.answer(decision.id, choice)

    workers = [threading.Thread(target=worker) for _ in range(4)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    assert [s.status for s in sessions] == ["finished"] * 8, [s.error for s in sessions]
    for s in sessions:
        events = s.events_since(0)
        assert events[-1]["kind"] == "game_over"
        assert [e["seq"] for e in events] == list(range(len(events)))


def test_same_seed_and_answers_replay_the_same_game(forge):
    def run(seed):
        registry = make_registry(forge)
        session = registry.create(FORMATS["modern"], seed, external_seats(RED, GREEN))
        play_randomly(registry.queue, session, random.Random(4242))
        return [(e["kind"], e["text"]) for e in session.events_since(0)]

    first = run(4242)
    assert first == run(4242)
    assert first != run(4243)  # the seed matters: same answers, another shuffle


def test_turn_limit_ends_in_a_draw(forge):
    registry = make_registry(forge, max_turns=2)
    session = registry.create(FORMATS["modern"], 7, external_seats(RED, GREEN))
    play_randomly(registry.queue, session, random.Random(7))
    assert session.status == "finished"
    assert session.end_reason == "turn_limit"
    assert session.winner is None
