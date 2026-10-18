"""Simulating a plan on a copy of the game: the outcome, the budget, the real game untouched."""

import json
import random

import pytest

from mtg_forge_engine import choices
from mtg_forge_engine.formats import FORMATS
from mtg_forge_engine.queue import DecisionQueue
from mtg_forge_engine.settings import Settings
from tests.decks import GREEN, RED
from tests.helpers import external_seats, play_randomly
from tests.test_forge_ai_choice import follow_forge_ai

pytestmark = pytest.mark.jvm


def make_registry(forge, **overrides):
    from mtg_forge_engine.registry import GameRegistry

    settings = Settings(max_concurrent_games=4, decision_timeout=30, max_turns=50, game_ttl=3600, forge_home=forge,
                        **overrides)
    return GameRegistry(settings, DecisionQueue(settings.decision_timeout))


@pytest.fixture
def registry(forge):
    return make_registry(forge)


def at_first(registry, monkeypatch, kind, probe, seeds=range(50, 60), when=lambda *a: True):
    """Runs games until ``probe(session, seat, player, combat)`` ran once at a ``kind``
    decision where ``when(session, player, combat)`` holds; returns what it returned."""
    result = {}
    original = getattr(choices, "attackers" if kind == "attack" else "priority")

    def attackers(session, seat, player, combat, ai):
        if "value" not in result and when(session, player, combat):
            result["value"] = probe(session, seat, player, combat)
        return original(session, seat, player, combat, ai)

    def priority(session, seat, player, ai):
        if "value" not in result and when(session, player, None):
            result["value"] = probe(session, seat, player, None)
        return original(session, seat, player, ai)

    monkeypatch.setattr(choices, "attackers" if kind == "attack" else "priority",
                        attackers if kind == "attack" else priority)
    for seed in seeds:
        session = registry.create(FORMATS["modern"], seed, external_seats(RED, GREEN))
        play_randomly(registry.queue, session, random.Random(seed))
        assert session.status == "finished", session.error
        if "value" in result:
            return result["value"]
    raise AssertionError(f"no {kind} decision met the condition")


def _player_defender(combat):
    import jpype

    return next(d for d in combat.getDefenders() if isinstance(d, jpype.JClass("forge.game.player.Player")))


def _attackers(player):
    import jpype

    util = jpype.JClass("forge.game.combat.CombatUtil")
    return [c for c in player.getCreaturesInPlay() if util.canAttack(c)]


def test_attack_outcome_is_the_damage_dealt_and_the_real_game_unchanged(registry, monkeypatch):
    from mtg_forge_engine.simulation import Simulator, position

    def probe(session, seat, player, combat):
        attackers = _attackers(player)
        defender = _player_defender(combat)
        before = position(session.game, player)
        result = Simulator(session, seat, player).attack(combat, [(a, defender) for a in attackers])
        assert position(session.game, player) == before and combat.getAttackers().isEmpty()
        return result, int(defender.getLife()), sum(int(a.getNetPower()) for a in attackers)

    result, life, power = at_first(registry, monkeypatch, "attack", probe,
                                   when=lambda s, p, c: bool(_attackers(p)) and c is not None)
    opponent = result["opponents"][0]
    assert opponent["life"] == [life, life - power]
    assert f"{life} → {life - power} life" in result["summary"]


def _castable_creature(player):
    return next((sa for sa in choices.playable(player)
                 if sa.isSpell() and not sa.usesTargeting() and sa.getHostCard().isCreature()), None)


def test_a_spell_outcome_resolves_the_whole_stack(registry, monkeypatch):
    from mtg_forge_engine.simulation import Simulator

    def probe(session, seat, player, combat):
        sa = _castable_creature(player)
        hand = int(player.getCardsIn(choices._zone("Hand")).size())
        return Simulator(session, seat, player).ability(sa), str(sa.getHostCard().getName()), hand

    result, name, hand = at_first(registry, monkeypatch, "priority", probe,
                                  when=lambda s, p, c: s.game.getStack().isEmpty() and _castable_creature(p) is not None)
    assert any(label.startswith(name) for label in result["you"]["gained"])
    assert result["you"]["hand"] == [hand, hand - 1]


def test_pass_with_an_empty_stack_is_no_change(registry, monkeypatch):
    from mtg_forge_engine.simulation import Simulator

    result = at_first(registry, monkeypatch, "priority",
                      lambda session, seat, player, combat: Simulator(session, seat, player).pass_priority(),
                      when=lambda s, p, c: s.game.getStack().isEmpty())
    assert result["summary"] == "no change"


def _opponents_spell_on_top(session, player):
    stack = session.game.getStack()
    return not stack.isEmpty() and not stack.peekAbility().getActivatingPlayer().equals(player)


def test_pass_resolves_an_opponents_spell(registry, monkeypatch):
    from mtg_forge_engine.simulation import Simulator

    result = at_first(registry, monkeypatch, "priority",
                      lambda session, seat, player, combat: Simulator(session, seat, player).pass_priority(),
                      seeds=range(50, 80), when=lambda s, p, c: _opponents_spell_on_top(s, p))
    assert result["summary"] != "no change"


def _draw_spell(player):
    return next((sa for sa in choices.playable(player)
                 if sa.isSpell() and not sa.usesTargeting() and "draw" in str(sa.getDescription()).lower()), None)


def test_outcomes_never_name_cards_drawn_from_the_library(registry, monkeypatch):
    from mtg_forge_engine.simulation import Simulator

    def probe(session, seat, player, combat):
        visible = {str(c.getName()) for p in session.game.getPlayers()
                   for zone in ("Hand", "Battlefield", "Graveyard", "Exile") for c in p.getCardsIn(choices._zone(zone))}
        hidden = {str(c.getName()) for c in player.getCardsIn(choices._zone("Library"))} - visible
        return Simulator(session, seat, player).ability(_draw_spell(player)), hidden

    result, hidden = at_first(registry, monkeypatch, "priority", probe, seeds=range(50, 80),
                              when=lambda s, p, c: _draw_spell(p) is not None and s.game.getStack().isEmpty())
    assert result is not None and all(isinstance(n, int) for n in result["you"]["hand"])
    assert hidden, "the test needs a card of the library that is nowhere to be seen"
    text = json.dumps(result)
    assert not [name for name in hidden if name in text]


def test_a_failing_simulation_leaves_outcome_null(registry, monkeypatch):
    from mtg_forge_engine import simulation

    real = simulation._cls

    def broken(name):
        if name.endswith("GameCopier"):
            raise RuntimeError("no copier today")
        return real(name)

    monkeypatch.setattr(simulation, "_cls", broken)
    result = at_first(registry, monkeypatch, "attack",
                      lambda session, seat, player, combat: simulation.Simulator(session, seat, player).attack(
                          combat, [(a, _player_defender(combat)) for a in _attackers(player)]),
                      when=lambda s, p, c: bool(_attackers(p)))
    assert result is None


def test_budget_leaves_later_candidates_without_outcome(forge, monkeypatch):
    from mtg_forge_engine.simulation import Simulator

    def probe(session, seat, player, combat):
        sim = Simulator(session, seat, player)
        return sim.pass_priority(), sim.pass_priority()

    first, second = at_first(make_registry(forge, simulation_budget_ms=0), monkeypatch, "priority", probe)
    assert first is None and second is None
    first, second = at_first(make_registry(forge), monkeypatch, "priority", probe)
    assert first is not None and second is not None


def test_simulations_leave_the_games_random_sequence_alone(registry, monkeypatch):
    from mtg_forge_engine.simulation import Simulator

    original = choices.attackers
    active = {"on": False, "ran": 0}

    def attackers(session, seat, player, combat, ai):
        if active["on"] and _attackers(player):
            active["ran"] += 1
            defender = _player_defender(combat)
            for a in _attackers(player):
                Simulator(session, seat, player).attack(combat, [(a, defender)])
        return original(session, seat, player, combat, ai)

    monkeypatch.setattr(choices, "attackers", attackers)
    runs = []
    for on in (True, False):
        active["on"] = on
        session = registry.create(FORMATS["modern"], 7, external_seats(RED, GREEN))
        answers = follow_forge_ai(registry.queue, session)
        assert session.status == "finished", session.error
        logs = [e["text"] for e in session.events_since(0)
                if e["kind"] == "log" and not e["text"].startswith("Match Duration")]
        runs.append((answers, logs, session.winner))
    assert active["ran"] > 0
    assert runs[0] == runs[1]


def test_the_handler_defers_to_forge_ai_while_simulating(registry, monkeypatch):
    """A copy's decisions must never reach Python: the client would be asked about a
    game that does not exist, and a simulated decision would start a simulation."""
    from mtg_forge_engine.handler import make_handler

    def never(*args, **kwargs):
        raise AssertionError("the client was asked during a simulation")

    monkeypatch.setattr(choices, "mulligan", never)
    monkeypatch.setattr(choices, "attackers", never)
    session = registry.create(FORMATS["modern"], 1, external_seats(RED, GREEN))
    session.simulating = 1
    handler = make_handler(session, 0)
    assert handler.mulliganKeepHand(None, 0, None) is None
    assert handler.declareAttackers(None, None, None) is None
    assert not [e for e in session.events_since(0) if e["kind"] == "fallback"]
    session.simulating = 0
    session.abort()


def _lethal_board(session, player, combat):
    if combat is None or not _attackers(player):
        return False
    defender = _player_defender(combat)
    return sum(int(a.getNetPower()) for a in _attackers(player)) >= int(defender.getLife())


def test_a_lethal_attack_says_the_opponent_loses(registry, monkeypatch):
    from mtg_forge_engine.simulation import Simulator

    def probe(session, seat, player, combat):
        defender = _player_defender(combat)
        return Simulator(session, seat, player).attack(combat, [(a, defender) for a in _attackers(player)]), int(defender.getLife())

    result, life = at_first(registry, monkeypatch, "attack", probe, seeds=range(50, 120), when=_lethal_board)
    opponent = result["opponents"][0]
    assert opponent["life"][0] == life and opponent["life"][1] <= 0 and opponent["lost_game"] is True
    assert "loses the game" in result["summary"]


def test_attackers_are_tapped_in_the_outcome(registry, monkeypatch):
    from mtg_forge_engine.simulation import Simulator

    def no_vigilance(session, player, combat):
        return combat is not None and any(not a.attackVigilance() for a in _attackers(player))

    def probe(session, seat, player, combat):
        attacker = next(a for a in _attackers(player) if not a.attackVigilance())
        return Simulator(session, seat, player).attack(combat, [(attacker, _player_defender(combat))]), str(attacker.getName())

    result, name = at_first(registry, monkeypatch, "attack", probe, when=no_vigilance)
    assert any(change.startswith(name) and "tapped)" in change for change in result["you"]["changed"]), result


def _bolt_at_me_on_top(session, player, combat=None):
    stack = session.game.getStack()
    if stack.isEmpty():
        return False
    top = stack.peekAbility()
    return (not top.getActivatingPlayer().equals(player) and str(top.getHostCard().getName()) == "Lightning Bolt"
            and any(t.equals(player) for t in top.getTargets() if hasattr(t, "getLife")))


def test_passing_on_a_bolt_at_your_face_costs_three_life(registry, monkeypatch):
    from mtg_forge_engine.simulation import Simulator

    def probe(session, seat, player, combat):
        return Simulator(session, seat, player).pass_priority(), int(player.getLife())

    result, life = at_first(registry, monkeypatch, "priority", probe, seeds=range(50, 120), when=_bolt_at_me_on_top)
    assert result["you"]["life"] == [life, life - 3]


def _own_creature_on_top(session, player, combat=None):
    stack = session.game.getStack()
    if stack.isEmpty():
        return False
    top = stack.peekAbility()
    return top.getActivatingPlayer().equals(player) and top.isSpell() and top.getHostCard().isCreature()


def test_passing_on_your_own_creature_spell_lets_it_resolve(registry, monkeypatch):
    from mtg_forge_engine.simulation import Simulator

    def probe(session, seat, player, combat):
        return Simulator(session, seat, player).pass_priority(), str(session.game.getStack().peekAbility().getHostCard().getName())

    result, name = at_first(registry, monkeypatch, "priority", probe, seeds=range(50, 120), when=_own_creature_on_top)
    assert any(label.startswith(name) for label in result["you"]["gained"]), result


def _ability_on_top(session, player, combat=None):
    stack = session.game.getStack()
    return not stack.isEmpty() and not stack.peekAbility().isSpell()


def test_a_stack_with_an_ability_gives_no_outcome(registry, monkeypatch):
    """Forge copies only spells of the stack: a copy missing an item would give a confident wrong outcome."""
    from mtg_forge_engine.simulation import Simulator

    try:
        result = at_first(registry, monkeypatch, "priority",
                          lambda session, seat, player, combat: Simulator(session, seat, player).pass_priority(),
                          seeds=range(50, 120), when=_ability_on_top)
    except AssertionError as exc:
        pytest.skip(f"no ability on the stack at a priority decision: {exc}")
    assert result is None


def _goblin_guide_can_attack(session, player, combat):
    return combat is not None and any(str(a.getName()) == "Goblin Guide" for a in _attackers(player))


def test_an_attack_with_a_trigger_still_has_an_outcome(registry, monkeypatch):
    """Goblin Guide's attack trigger lands on the copy's stack: it must resolve before the
    copy moves on, or Forge refuses to advance ("Stack isn't empty")."""
    from mtg_forge_engine.simulation import Simulator

    def probe(session, seat, player, combat):
        guide = next(a for a in _attackers(player) if str(a.getName()) == "Goblin Guide")
        defender = _player_defender(combat)
        return Simulator(session, seat, player).attack(combat, [(guide, defender)]), int(defender.getLife()), int(guide.getNetPower())

    result, life, power = at_first(registry, monkeypatch, "attack", probe, seeds=range(50, 120), when=_goblin_guide_can_attack)
    assert result is not None
    assert result["opponents"][0]["life"] == [life, life - power]
