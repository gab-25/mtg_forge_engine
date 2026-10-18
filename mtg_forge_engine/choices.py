"""Each exposed Forge decision as a sequence of single choices.

Every function returns the value Forge expects (Python side) or None, which
hands the decision to Forge's AI. Multi-selects ask one pick at a time, with a
"Done" option (index 0) once the minimum is reached.

``ai`` is Forge's AI's whole answer to the decision (a ForgeAi). Each question
tells the client which option leads there: the first pick of that answer not yet
made, or "Done" once there is none left.
"""

import jpype

from .candidates import attack_plans, block_plans
from .labels import ability_label, attack_plan_label, block_plan_label, card_label, entity_label, target_label
from .session import Option


class ForgeAi:
    """What Forge's AI would answer, asked of the Java shim once, on first use: the
    AI evaluates the game as it is at the first question put to the client."""

    def __init__(self, supplier):
        self._supplier = supplier
        self._asked = False
        self._answer = None

    def get(self):
        if not self._asked:
            self._asked = True
            self._answer = self._supplier.get() if self._supplier is not None else None
        return self._answer


def _next_pick(answer, chosen, candidates, offset: int, can_stop: bool) -> int | None:
    """The question's option for the first item of ``answer`` not in ``chosen``
    (an item repeats as often as the answer has it). ``candidates`` are the
    options from ``offset`` on; option 0 is "Done" when ``can_stop``."""
    if answer is None:
        return None
    pending = list(answer)
    for item in chosen:
        if item in pending:
            pending.remove(item)
    for item in pending:
        if item in candidates:
            return candidates.index(item) + offset
    return 0 if can_stop else None


def _yes_no(answer, yes: int, no: int) -> int | None:
    return None if answer is None else (yes if bool(answer.booleanValue()) else no)


def _zone(name: str):
    return getattr(jpype.JClass("forge.game.zone.ZoneType"), name)


def mulligan(session, seat: int, player, cards_to_return: int, ai: ForgeAi) -> bool | None:
    hand = ", ".join(card_label(c) for c in player.getCardsIn(_zone("Hand")))
    keep = "Keep this hand" + (f" (then put {cards_to_return} on the bottom)" if cards_to_return else "")
    choice = session.ask(seat, "mulligan", f"Mulligan? Your hand: {hand}", [Option(keep), Option("Mulligan")],
                         lambda: _yes_no(ai.get(), yes=0, no=1))
    return None if choice is None else choice == 0


def bottom(session, seat: int, player, hand, count: int, ai: ForgeAi) -> list | None:
    remaining = list(hand)
    chosen = []
    while len(chosen) < count and remaining:
        choice = session.ask(seat, "bottom",
                             f"Put a card on the bottom of your library ({len(chosen) + 1} of {count})",
                             [Option(card_label(c)) for c in remaining],
                             lambda: _next_pick(ai.get(), chosen, remaining, 0, False))
        if choice is None:
            return None
        chosen.append(remaining.pop(choice))
    return chosen


def _targets_stack(restrictions) -> bool:
    return restrictions.getZone().contains(_zone("Stack"))


def _stack_candidates(sa) -> list:
    """The spells and abilities on the stack ``sa`` can target, as Forge's own UI
    lists them: its candidate lists hold players and cards only."""
    return [si.getSpellAbility() for si in sa.getHostCard().getGame().getStack()
            if sa.canTargetSpellAbility(si.getSpellAbility())]


def _candidates(sa) -> list:
    """Every legal target of ``sa``: players, cards and, for a spell that targets
    the stack, the spells and abilities on it (not their cards)."""
    restrictions = sa.getTargetRestrictions()
    candidates = list(restrictions.getAllCandidates(sa, False))
    if _targets_stack(restrictions):
        on_stack = [c for c in candidates
                    if isinstance(c, jpype.JClass("forge.game.card.Card")) and c.isInZone(_zone("Stack"))]
        candidates = [c for c in candidates if c not in on_stack]
        candidates += _stack_candidates(sa)
    return candidates


def _targets_available(sa) -> bool:
    """Whether every targeting part of the ability has enough legal targets
    (Forge's canPlay does not check targets). Forge's hasCandidates always says
    yes for a spell that targets the stack (Stifle, Spell Snare…): those are
    counted here."""
    part = sa
    while part is not None:
        if part.usesTargeting() and part.getMinTargets() > 0:
            restrictions = part.getTargetRestrictions()
            if _targets_stack(restrictions):
                if len(_candidates(part)) < part.getMinTargets():
                    return False
            elif not restrictions.hasCandidates(part):
                return False
        part = part.getSubAbility()
    return True


def playable(player) -> list:
    """What the player can do with priority right now: land plays, and spells and
    non-mana activated abilities whose costs can be paid and whose targets exist."""
    J = jpype.JClass
    ability_util = J("forge.ai.ComputerUtilAbility")
    cost_util = J("forge.ai.ComputerUtilCost")
    mana_util = J("forge.ai.ComputerUtilMana")
    result = []
    for card in ability_util.getAvailableCards(player.getGame(), player):
        for sa in card.getAllPossibleAbilities(player, True):
            if sa.isManaAbility():
                continue
            sa.setActivatingPlayer(player)
            if sa.isLandAbility() or (cost_util.canPayCost(sa, player, False)
                                      and mana_util.canPayManaCost(sa, player, 0, False)
                                      and _targets_available(sa)):
                result.append(sa)
    return result


def _priority_prompt(player) -> str:
    game = player.getGame()
    phases = game.getPhaseHandler()
    prompt = f"Turn {phases.getTurn()}, {phases.getPhase()}: you have priority"
    if not game.getStack().isEmpty():
        prompt += f". Top of the stack: {game.getStack().peekAbility().getStackDescription()}"
    return prompt


def _same_ability(a, b) -> bool:
    """Forge makes a new copy of some abilities (alternative costs) each time it lists them."""
    return bool(a.equals(b)) or (bool(a.getHostCard().equals(b.getHostCard())) and str(a) == str(b))


def _priority_pick(answer, abilities) -> int | None:
    if answer is None:
        return None
    if answer.isEmpty():
        return 0
    return next((i + 1 for i, sa in enumerate(abilities) if _same_ability(sa, answer.get(0))), None)


def priority(session, seat: int, player, ai: ForgeAi) -> list | None:
    abilities = playable(player)
    if not abilities:
        return []
    options = [Option("Pass priority")] + [Option(ability_label(sa)) for sa in abilities]
    choice = session.ask(seat, "priority", _priority_prompt(player), options,
                         lambda: _priority_pick(ai.get(), abilities))
    if choice is None:
        return None
    return [] if choice == 0 else [abilities[choice - 1]]


def targets(session, seat: int, player, sa, ai: ForgeAi) -> bool | None:
    restrictions = sa.getTargetRestrictions()
    if restrictions is None or sa.isDividedAsYouChoose():
        return None
    sa.resetTargets()
    source = card_label(sa.getHostCard())
    while not sa.isMaxTargetChosen():
        chosen = sa.getTargets()
        candidates = [c for c in _candidates(sa) if not chosen.contains(c)]
        if not candidates:
            break
        can_stop = bool(sa.isMinTargetChosen())
        options = ([Option("Done (no more targets)")] if can_stop else []) + [
            Option(target_label(c, player)) for c in candidates]
        prompt = (f"Choose a target for {source}: {sa.getDescription()} "
                  f"({chosen.size()} chosen, {sa.getMinTargets()}-{sa.getMaxTargets()})")
        choice = session.ask(seat, "target", prompt, options,
                             lambda: _next_pick(ai.get(), list(chosen), candidates, 1 if can_stop else 0, can_stop))
        if choice is None:
            sa.resetTargets()
            return None
        if can_stop and choice == 0:
            break
        chosen.add(candidates[choice - (1 if can_stop else 0)])
    return bool(sa.isTargetNumberValid())


def confirm(session, seat: int, message: str, ai: ForgeAi) -> bool | None:
    choice = session.ask(seat, "confirm", message or "Confirm?", [Option("No"), Option("Yes")],
                         lambda: _yes_no(ai.get(), yes=1, no=0))
    return None if choice is None else choice == 1


def modes(session, seat: int, sa, possible, minimum: int, num: int, allow_repeat: bool, ai: ForgeAi) -> list | None:
    remaining = list(possible)
    chosen = []
    while len(chosen) < num and remaining:
        can_stop = len(chosen) >= minimum
        options = ([Option("Done (no more modes)")] if can_stop else []) + [
            Option(str(mode.getDescription())) for mode in remaining]
        prompt = f"Choose a mode for {card_label(sa.getHostCard())} ({len(chosen)} chosen, {minimum}-{num})"
        choice = session.ask(seat, "mode", prompt, options,
                             lambda: _next_pick(ai.get(), chosen, remaining, 1 if can_stop else 0, can_stop))
        if choice is None:
            return None
        if can_stop and choice == 0:
            break
        mode = remaining[choice - (1 if can_stop else 0)]
        chosen.append(mode)
        if not allow_repeat:
            remaining.remove(mode)
    return chosen


def _combat_util():
    return jpype.JClass("forge.game.combat.CombatUtil")


def _ai_combat():
    return jpype.JClass("forge.ai.ComputerUtilCombat")


def attack_facts(attacker, defender, combat, player) -> tuple[str, ...]:
    is_player = isinstance(defender, jpype.JClass("forge.game.player.Player"))
    damage = int(_ai_combat().damageIfUnblocked(attacker, defender, combat, False))
    facts = [f"deals {damage} damage if unblocked"]
    if is_player and damage >= defender.getLife():
        facts.append("lethal if unblocked")
    defending = defender if is_player else defender.getController()
    blockers = [b for b in defending.getCreaturesInPlay() if _combat_util().canBlock(attacker, b)]
    if not blockers:
        facts.append("no creature can block it")
        return tuple(facts)
    facts.append("can be blocked by: " + ", ".join(card_label(b) for b in blockers))
    killers = [b for b in blockers if _ai_combat().canDestroyAttacker(player, attacker, b, combat, False)]
    if killers:
        facts.append("dies if blocked by: " + ", ".join(card_label(b) for b in killers))
    return tuple(facts)


def block_facts(blocker, attacker, combat, player) -> tuple[str, ...]:
    blocker_dies = _ai_combat().canDestroyBlocker(player, blocker, attacker, combat, False)
    attacker_dies = _ai_combat().canDestroyAttacker(player, attacker, blocker, combat, False)
    return ("your blocker dies" if blocker_dies else "your blocker survives",
            "kills the attacker" if attacker_dies else "the attacker survives")


def _undo(combat, cards) -> None:
    for card in cards:
        combat.removeFromCombat(card)


def _attack_pick(answer, pairs, declared) -> int | None:
    if answer is None:
        return None
    wanted = [(e.getKey(), e.getValue()) for e in answer.entrySet() if e.getKey() not in declared]
    return next((i + 1 for i, pair in enumerate(pairs) if pair in wanted), 0)


def _plan_pick(answer_pairs, plans) -> int | None:
    """The index of the plan with exactly the pairs Forge's AI would declare, else None."""
    if answer_pairs is None:
        return None
    wanted = frozenset(answer_pairs)
    return next((i for i, plan in enumerate(plans) if frozenset(plan) == wanted), None)


def _legal_attack(util, combat, plan) -> bool:
    for attacker, defender in plan:
        combat.addAttacker(attacker, defender)
    try:
        return bool(util.validateAttackers(combat))
    finally:
        _undo(combat, [a for a, _ in plan])


def _attack_plan_facts(plan, combat, player) -> tuple[str, ...]:
    return tuple(f"{card_label(a)}: " + "; ".join(attack_facts(a, d, combat, player)) for a, d in plan)


def _simulated_attackers(session, seat: int, player, combat, ai: ForgeAi, available, defenders) -> bool | None:
    from .simulation import Simulator

    util = _combat_util()
    players = [d for d in defenders if isinstance(d, jpype.JClass("forge.game.player.Player"))]
    legal = [(a, d) for a in available for d in defenders if util.canAttack(a, d)]
    plans = [plan for plan in attack_plans(available, defenders, players, session.settings.max_candidates)
             if all(pair in legal for pair in plan) and _legal_attack(util, combat, plan)]
    simulator = Simulator(session, seat, player)
    options = [Option(attack_plan_label(plan, player), _attack_plan_facts(plan, combat, player),
                      simulator.attack(combat, plan)) for plan in plans]

    def forge_ai():
        answer = ai.get()
        return _plan_pick(None if answer is None else [(e.getKey(), e.getValue()) for e in answer.entrySet()], plans)

    choice = session.ask(seat, "attack", "Declare your attack", options, forge_ai, simulated=True)
    if choice is None:
        return None
    for attacker, defender in plans[choice]:
        combat.addAttacker(attacker, defender)
    if not util.validateAttackers(combat):
        _undo(combat, [a for a, _ in plans[choice]])
        session.fallback(seat, "attack", "invalid_attack")
        return None
    return True


def attackers(session, seat: int, player, combat, ai: ForgeAi) -> bool | None:
    util = _combat_util()
    available = [c for c in player.getCreaturesInPlay() if util.canAttack(c)]
    defenders = list(combat.getDefenders())
    if session.settings.simulate and available:
        return _simulated_attackers(session, seat, player, combat, ai, available, defenders)
    declared = []
    while True:
        pairs = [(a, d) for a in available if a not in declared for d in defenders if util.canAttack(a, d)]
        if not pairs:
            break
        options = [Option("Done (no more attackers)")] + [
            Option(f"Attack with {card_label(a)} -> {entity_label(d, player)}", attack_facts(a, d, combat, player))
            for a, d in pairs]
        prompt = "Declare attackers" + (
            f" (attacking: {', '.join(card_label(a) for a in declared)})" if declared else "")
        choice = session.ask(seat, "attack", prompt, options, lambda: _attack_pick(ai.get(), pairs, declared))
        if choice is None:
            _undo(combat, declared)
            return None
        if choice == 0:
            break
        attacker, defender = pairs[choice - 1]
        combat.addAttacker(attacker, defender)
        declared.append(attacker)
    if not util.validateAttackers(combat):
        _undo(combat, declared)
        session.fallback(seat, "attack", "invalid_attack")
        return None
    return True


def _block_pick(answer, pairs, declared) -> int | None:
    if answer is None:
        return None
    wanted = [(e.getKey(), a) for e in answer.entrySet() if e.getKey() not in declared for a in e.getValue()]
    return next((i + 1 for i, pair in enumerate(pairs) if pair in wanted), 0)


def _incoming(combat, player) -> int:
    unblocked = jpype.JClass("java.util.ArrayList")()
    for a in combat.getAttackersOf(player):
        if combat.getBlockers(a).isEmpty():
            unblocked.add(a)
    return int(_ai_combat().sumDamageIfUnblocked(unblocked, player))


def _legal_blocks(util, combat, player, plan) -> bool:
    for blocker, attacker in plan:
        combat.addBlocker(attacker, blocker)
    try:
        return util.validateBlocks(combat, player) is None
    finally:
        _undo(combat, [b for b, _ in plan])


def _simulated_blockers(session, seat: int, player, combat, ai: ForgeAi, pairs) -> bool | None:
    from .simulation import Simulator

    util = _combat_util()
    plans = [plan for plan in block_plans(pairs, session.settings.max_candidates)
             if _legal_blocks(util, combat, player, plan)]
    simulator = Simulator(session, seat, player)
    options = [Option(block_plan_label(plan),
                      tuple(f"{card_label(b)}: " + "; ".join(block_facts(b, a, combat, player)) for b, a in plan),
                      simulator.blocks(combat, plan)) for plan in plans]

    def forge_ai():
        answer = ai.get()
        if answer is None:
            return None
        return _plan_pick([(e.getKey(), a) for e in answer.entrySet() for a in e.getValue()], plans)

    prompt = f"Declare your blocks (unblocked attackers deal {_incoming(combat, player)}, your life {player.getLife()})"
    choice = session.ask(seat, "block", prompt, options, forge_ai, simulated=True)
    if choice is None:
        return None
    for blocker, attacker in plans[choice]:
        combat.addBlocker(attacker, blocker)
    if util.validateBlocks(combat, player) is not None:
        _undo(combat, [b for b, _ in plans[choice]])
        session.fallback(seat, "block", "invalid_block")
        return None
    return True


def blockers(session, seat: int, player, combat, ai: ForgeAi) -> bool | None:
    util = _combat_util()
    # Only attackers attacking this player, or its planeswalkers and battles:
    # CombatUtil.canBlock does not check the defender.
    attacking = [a for a in combat.getAttackers() if player.equals(combat.getDefenderPlayerByAttacker(a))]
    available = [b for b in player.getCreaturesInPlay() if util.canBlock(b, combat)]
    if session.settings.simulate:
        pairs = [(b, a) for b in available for a in attacking if util.canBlock(a, b, combat)]
        if pairs:
            return _simulated_blockers(session, seat, player, combat, ai, pairs)
    declared = []
    while True:
        pairs = [(b, a) for b in available if b not in declared for a in attacking if util.canBlock(a, b, combat)]
        if not pairs:
            break
        incoming = _incoming(combat, player)
        options = [Option("Done (no more blockers)")] + [
            Option(f"Block {card_label(a)} with {card_label(b)}", block_facts(b, a, combat, player))
            for b, a in pairs]
        prompt = f"Declare blockers (unblocked attackers deal {incoming}, your life {player.getLife()})"
        choice = session.ask(seat, "block", prompt, options, lambda: _block_pick(ai.get(), pairs, declared))
        if choice is None:
            _undo(combat, declared)
            return None
        if choice == 0:
            break
        blocker, attacker = pairs[choice - 1]
        combat.addBlocker(attacker, blocker)
        declared.append(blocker)
    if util.validateBlocks(combat, player) is not None:
        _undo(combat, declared)
        session.fallback(seat, "block", "invalid_block")
        return None
    return True


def entities(session, seat: int, player, title, options, minimum: int, maximum: int, ai: ForgeAi) -> list | None:
    remaining = list(options)
    chosen = []
    title = str(title) if title else "Choose"
    while len(chosen) < maximum and remaining:
        can_stop = len(chosen) >= minimum
        labels = ([Option("Done")] if can_stop else []) + [Option(entity_label(e, player)) for e in remaining]
        choice = session.ask(seat, "choose_cards", f"{title} ({len(chosen)} chosen, {minimum}-{maximum})", labels,
                             lambda: _next_pick(ai.get(), chosen, remaining, 1 if can_stop else 0, can_stop))
        if choice is None:
            return None
        if can_stop and choice == 0:
            break
        chosen.append(remaining.pop(choice - (1 if can_stop else 0)))
    return chosen
