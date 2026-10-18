"""Carries a complete action out on a copy of the game and reports the position it leads to.

Forge's own simulation classes do the work: ``GameCopier`` copies the game,
``GameSimulator`` casts an ability on the copy and resolves the stack, the
phase handler advances a copied combat to its damage. Before anything runs on
the copy, every opponent is silenced (all their permanents tapped, attacking
creatures excepted): the outcome is what happens if the opponent cannot
respond. The real game is never touched, the real ``Combat`` edits are undone
in ``finally``, and everything draws its random numbers from an isolated copy
of the game's generator (``GameRandom.isolated``), so the game stays
reproducible from its seed.

Every method of :class:`Simulator` returns an outcome dict (:mod:`.outcome`)
or ``None``: over budget, or a failure logged here and never raised.
"""

import logging
import time

import jpype

from .labels import card_label
from .outcome import outcome

logger = logging.getLogger(__name__)

INT_MIN = -(2**31)


def _cls(name: str):
    return jpype.JClass(name)


def _zone(name: str):
    return getattr(_cls("forge.game.zone.ZoneType"), name)


def _label(card, viewer) -> str:
    if card.isFaceDown() and not card.getController().equals(viewer):
        return "Face-down card"
    label = card_label(card).split(" #")[0]
    if card.isCreature():
        label += f" ({card.getNetPower()}/{card.getNetToughness()}"
    else:
        label += " ("
    extras = ["tapped"] if card.isTapped() else []
    extras += [f"{entry.getElement()} ×{entry.getCount()}" for entry in card.getCounters().entrySet()]
    if extras:
        label += (", " if card.isCreature() else "") + ", ".join(extras)
    label += ")"
    return label.replace(" ()", "")


def position(game, viewer) -> dict:
    """The pure position of :mod:`.outcome` for every player of ``game``, seen by ``viewer``."""
    return {
        str(player.getName()): {
            "life": int(player.getLife()),
            "hand": int(player.getCardsIn(_zone("Hand")).size()),
            "graveyard": int(player.getCardsIn(_zone("Graveyard")).size()),
            "permanents": {int(c.getId()): _label(c, viewer) for c in player.getCardsIn(_zone("Battlefield"))},
        }
        for player in game.getPlayers()
    }


def silence(copy, me) -> None:
    """Taps every permanent the other players control, attacking creatures excepted."""
    combat = copy.getCombat()
    attacking = set(int(a.getId()) for a in combat.getAttackers()) if combat is not None else set()
    for player in copy.getPlayers():
        if player.equals(me):
            continue
        for card in list(player.getCardsIn(_zone("Battlefield"))):
            if int(card.getId()) not in attacking:
                card.setTapped(True)


def isolated(fn):
    """Runs ``fn`` on a copy of this thread's game random generator.

    The Java ``Supplier`` cannot return a Python value, so the result (or the
    exception) travels through a closure and the supplier returns null.
    """
    box: dict = {}

    def get():
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below, with its Python traceback
            box["error"] = exc
        return None

    _cls("forge.bridge.GameRandom").isolated(jpype.JProxy("java.util.function.Supplier", dict={"get": get}))
    if "error" in box:
        raise box["error"]
    return box.get("value")


class Simulator:
    """Simulates plans for ``player`` (seat ``seat`` of ``session``) within the session's budget."""

    def __init__(self, session, seat: int, player):
        self.session = session
        self.seat = seat
        self.player = player
        self.game = session.game
        self.deadline = time.monotonic() + session.settings.simulation_budget_ms / 1000

    # -- public -------------------------------------------------------------------

    def attack(self, combat, plan: list) -> dict | None:
        """``plan``: (attacker, defender) pairs added to the real combat for the copy, then undone."""
        def copy_with_plan():
            for attacker, defender in plan:
                combat.addAttacker(attacker, defender)
            try:
                return self._copy()
            finally:
                for attacker, _ in plan:
                    combat.removeFromCombat(attacker)

        return self._run(lambda: self._combat_outcome(copy_with_plan()))

    def blocks(self, combat, plan: list) -> dict | None:
        """``plan``: (blocker, attacker) pairs."""
        def copy_with_plan():
            for blocker, attacker in plan:
                combat.addBlocker(attacker, blocker)
            try:
                return self._copy()
            finally:
                for blocker, _ in plan:
                    combat.removeFromCombat(blocker)

        return self._run(lambda: self._combat_outcome(copy_with_plan()))

    def ability(self, sa, target=None) -> dict | None:
        """Casts or activates ``sa`` (on ``target`` when given) on the copy and resolves the stack."""
        def run():
            if target is not None:
                sa.resetTargets()
                sa.getTargets().add(target)
            try:
                sim, copy, me = self._simulator()
                silence(copy, me)
                before = position(copy, me)
                score = sim.simulateSpellAbility(sa, True)
                if int(score.value) == INT_MIN:
                    return None
                return outcome(before, position(copy, me), str(me.getName()))
            finally:
                if target is not None:
                    sa.resetTargets()

        return self._run(run)

    def pass_priority(self) -> dict | None:
        """No change with an empty stack; otherwise the position once the stack has resolved."""
        def run():
            if self.game.getStack().isEmpty():
                here = position(self.game, self.player)
                return outcome(here, here, str(self.player.getName()))
            sim, copy, me = self._simulator()
            silence(copy, me)
            before = position(copy, me)
            _cls("forge.ai.simulation.GameSimulator").resolveStack(copy, me.getWeakestOpponent())
            return outcome(before, position(copy, me), str(me.getName()))

        return self._run(run)

    # -- internals ----------------------------------------------------------------

    def _run(self, fn):
        if time.monotonic() > self.deadline:
            return None
        try:
            return isolated(fn)
        except Exception:  # noqa: BLE001 - a failing simulation never costs the decision.
            logger.exception("game %s seat %s: simulation failed", self.session.id, self.seat)
            return None

    def _copy(self):
        copier = _cls("forge.ai.simulation.GameCopier")(self.game)
        copy = copier.makeCopy()
        return copy, copier.find(self.player)

    def _combat_outcome(self, copied):
        copy, me = copied
        silence(copy, me)
        before = position(copy, me)
        copy.getPhaseHandler().devAdvanceToPhase(_cls("forge.game.phase.PhaseType").COMBAT_DAMAGE)
        return outcome(before, position(copy, me), str(me.getName()))

    def _simulator(self):
        score = _cls("forge.ai.simulation.GameStateEvaluator$Score")(0)
        controller = _cls("forge.ai.simulation.SimulationController")(score)
        sim = _cls("forge.ai.simulation.GameSimulator")(controller, self.game, self.player, None)
        copy = sim.getSimulatedGameState()
        return sim, copy, sim.getGameCopier().find(self.player)
