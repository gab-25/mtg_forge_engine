"""Carries a complete action out on a copy of the game and reports the position it leads to.

Forge's own classes do the work: ``GameCopier`` copies the game (its stack
included), ``ComputerUtil.handlePlayingSpellAbility`` casts the copied ability
with the same targets, ``GameSimulator.resolveStack`` resolves the copied
stack, the phase handler advances a copied combat to its damage. Before anything runs on
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
    """The pure position of :mod:`.outcome` for every player of ``game``, seen by ``viewer``.

    Over the registered players: a player who just lost leaves ``getPlayers()``,
    and a lethal attack must read as one.
    """
    lost = game.getLostPlayers()
    return {
        str(player.getName()): {
            "life": int(player.getLife()),
            "hand": int(player.getCardsIn(_zone("Hand")).size()),
            "graveyard": int(player.getCardsIn(_zone("Graveyard")).size()),
            "permanents": {int(c.getId()): _label(c, viewer) for c in player.getCardsIn(_zone("Battlefield"))},
            "lost_game": bool(lost.contains(player)),
        }
        for player in game.getRegisteredPlayers()
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
                copy, copier, me = self._copy()
                if not self._stack_mirrored(copy):
                    return None
                silence(copy, me)
                before = position(copy, me)
                if not self._play(copy, copier, me, sa):
                    return None
                self._resolve_stack(copy, me)
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
            copy, copier, me = self._copy()
            if not self._stack_mirrored(copy):
                return None
            silence(copy, me)
            before = position(copy, me)
            self._resolve_stack(copy, me)
            return outcome(before, position(copy, me), str(me.getName()))

        return self._run(run)

    # -- internals ----------------------------------------------------------------

    def _run(self, fn):
        if time.monotonic() > self.deadline:
            return None
        self.session.simulating += 1
        try:
            return isolated(fn)
        except Exception:  # noqa: BLE001 - a failing simulation never costs the decision.
            logger.exception("game %s seat %s: simulation failed", self.session.id, self.seat)
            return None
        finally:
            self.session.simulating -= 1

    def _copy(self):
        """``(copy, copier, me)``: one copy of the game, its stack included (COPY_STACK)."""
        copier = _cls("forge.ai.simulation.GameCopier")(self.game)
        copy = copier.makeCopy()
        return copy, copier, copier.find(self.player)

    def _stack_mirrored(self, copy) -> bool:
        """Forge copies only the spells of the stack: with an ability on it the copy is
        not the game, and no outcome is better than a confident wrong one."""
        return int(copy.getStack().size()) == int(self.game.getStack().size())

    def _resolve_stack(self, copy, me) -> None:
        _cls("forge.ai.simulation.GameSimulator").resolveStack(copy, me.getWeakestOpponent())

    def _find_ability(self, copier, me, sa):
        """The copy of ``sa`` on the copied host card, matched by description like Forge's
        own simulator does."""
        host = copier.find(sa.getHostCard())
        wanted = str(sa)
        for candidate in list(host.getSpellAbilities()) + list(host.getAllPossibleAbilities(me, True)):
            if str(candidate) == wanted:
                return candidate
        return None

    def _map_target(self, copy, copier, target):
        """A target's copy: a spell or ability on the stack through the copied stack, anything else through the copier."""
        if isinstance(target, _cls("forge.game.spellability.SpellAbility")):
            host_id = int(target.getHostCard().getId())
            for item in copy.getStack():
                if int(item.getSourceCard().getId()) == host_id:
                    return item.getSpellAbility()
            raise LookupError(f"no copy of {target} on the copied stack")
        return copier.find(target)

    def _copy_targets(self, copy, copier, source, destination) -> None:
        """Maps the targets of ``source`` and its sub-abilities onto ``destination``'s."""
        while source is not None and destination is not None:
            if source.usesTargeting():
                destination.resetTargets()
                for target in source.getTargets():
                    destination.getTargets().add(self._map_target(copy, copier, target))
            source, destination = source.getSubAbility(), destination.getSubAbility()

    def _play(self, copy, copier, me, sa) -> bool:
        """Plays the copy of ``sa`` on the copy of the game: a land drop, or a cast with the
        same targets, costs paid by Forge's AI."""
        if sa.isLandAbility():
            return bool(me.playLand(copier.find(sa.getHostCard()), sa))
        copied = self._find_ability(copier, me, sa)
        if copied is None:
            return False
        copied.setActivatingPlayer(me)
        choose = jpype.JProxy("java.util.function.Consumer",
                              dict={"accept": lambda playing: self._copy_targets(copy, copier, sa, playing)})
        return bool(_cls("forge.ai.ComputerUtil").handlePlayingSpellAbility(me, copied, choose))

    def _combat_outcome(self, copied):
        copy, copier, me = copied
        silence(copy, me)
        before = position(copy, me)
        phases = copy.getPhaseHandler()
        phase_type = _cls("forge.game.phase.PhaseType")
        combat = copy.getCombat()
        if phases.getPhase() == phase_type.COMBAT_DECLARE_ATTACKERS:
            self._finish_attack_declaration(copy, combat)
        elif phases.getPhase() == phase_type.COMBAT_DECLARE_BLOCKERS:
            # Copied mid-declaration: finish what Forge does once every blocker is
            # declared, or the damage step finds attackers neither blocked nor unblocked.
            combat.orderBlockersForDamageAssignment()
            combat.orderAttackersForDamageAssignment()
            combat.removeAbsentCombatants()
            combat.fireTriggersForUnblockedAttackers(copy)
        phases.devAdvanceToPhase(phase_type.COMBAT_DAMAGE)
        return outcome(before, position(copy, me), str(me.getName()))

    @staticmethod
    def _finish_attack_declaration(copy, combat) -> None:
        """What Forge does once the attackers are declared (PhaseHandler.declareAttackersTurnBasedAction):
        tap them, run the AttackersDeclared and Attacks triggers."""
        attackers = list(combat.getAttackers())
        for attacker in attackers:
            if not attacker.attackVigilance():
                attacker.setTapped(False)
                attacker.tap(True, True, None, None)
        ability_key = _cls("forge.game.ability.AbilityKey")
        attacked = _cls("java.util.ArrayList")()
        for defender in combat.getDefenders():
            if not combat.getAttackersOf(defender).isEmpty():
                attacked.add(defender)
        params = ability_key.newMap()
        params.put(ability_key.Attackers, combat.getAttackers())
        params.put(ability_key.AttackingPlayer, combat.getAttackingPlayer())
        params.put(ability_key.AttackedTarget, attacked)
        copy.getTriggerHandler().runTrigger(_cls("forge.game.trigger.TriggerType").AttackersDeclared, params, False)
        util = _cls("forge.game.combat.CombatUtil")
        for attacker in attackers:
            util.checkDeclaredAttacker(copy, attacker, combat, True)
