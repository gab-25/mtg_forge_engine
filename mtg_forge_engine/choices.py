"""Each exposed Forge decision as a sequence of single choices.

Every function returns the value Forge expects (Python side) or None, which
hands the decision to Forge's AI. Multi-selects ask one pick at a time, with a
"Done" option (index 0) once the minimum is reached.
"""

import jpype

from .labels import ability_label, card_label, entity_label
from .session import Option


def _zone(name: str):
    return getattr(jpype.JClass("forge.game.zone.ZoneType"), name)


def mulligan(session, seat: int, player, cards_to_return: int) -> bool | None:
    hand = ", ".join(card_label(c) for c in player.getCardsIn(_zone("Hand")))
    keep = "Keep this hand" + (f" (then put {cards_to_return} on the bottom)" if cards_to_return else "")
    choice = session.ask(seat, "mulligan", f"Mulligan? Your hand: {hand}", [Option(keep), Option("Mulligan")])
    return None if choice is None else choice == 0


def bottom(session, seat: int, player, hand, count: int) -> list | None:
    remaining = list(hand)
    chosen = []
    while len(chosen) < count and remaining:
        choice = session.ask(seat, "bottom",
                             f"Put a card on the bottom of your library ({len(chosen) + 1} of {count})",
                             [Option(card_label(c)) for c in remaining])
        if choice is None:
            return None
        chosen.append(remaining.pop(choice))
    return chosen


def _targets_available(sa) -> bool:
    """Whether every targeting part of the ability has enough legal targets
    (Forge's canPlay does not check targets)."""
    part = sa
    while part is not None:
        if part.usesTargeting() and part.getMinTargets() > 0 and not part.getTargetRestrictions().hasCandidates(part):
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


def priority(session, seat: int, player) -> list | None:
    abilities = playable(player)
    if not abilities:
        return []
    options = [Option("Pass priority")] + [Option(ability_label(sa)) for sa in abilities]
    choice = session.ask(seat, "priority", _priority_prompt(player), options)
    if choice is None:
        return None
    return [] if choice == 0 else [abilities[choice - 1]]


def targets(session, seat: int, player, sa) -> bool | None:
    restrictions = sa.getTargetRestrictions()
    if restrictions is None or sa.isDividedAsYouChoose():
        return None
    sa.resetTargets()
    source = card_label(sa.getHostCard())
    while not sa.isMaxTargetChosen():
        chosen = sa.getTargets()
        candidates = [c for c in restrictions.getAllCandidates(sa, False) if not chosen.contains(c)]
        if not candidates:
            break
        can_stop = bool(sa.isMinTargetChosen())
        options = ([Option("Done (no more targets)")] if can_stop else []) + [
            Option(entity_label(c, player)) for c in candidates]
        prompt = (f"Choose a target for {source}: {sa.getDescription()} "
                  f"({chosen.size()} chosen, {sa.getMinTargets()}-{sa.getMaxTargets()})")
        choice = session.ask(seat, "target", prompt, options)
        if choice is None:
            sa.resetTargets()
            return None
        if can_stop and choice == 0:
            break
        chosen.add(candidates[choice - (1 if can_stop else 0)])
    return bool(sa.isTargetNumberValid())


def confirm(session, seat: int, message: str) -> bool | None:
    choice = session.ask(seat, "confirm", message or "Confirm?", [Option("No"), Option("Yes")])
    return None if choice is None else choice == 1


def modes(session, seat: int, sa, possible, minimum: int, num: int, allow_repeat: bool) -> list | None:
    remaining = list(possible)
    chosen = []
    while len(chosen) < num and remaining:
        can_stop = len(chosen) >= minimum
        options = ([Option("Done (no more modes)")] if can_stop else []) + [
            Option(str(mode.getDescription())) for mode in remaining]
        prompt = f"Choose a mode for {card_label(sa.getHostCard())} ({len(chosen)} chosen, {minimum}-{num})"
        choice = session.ask(seat, "mode", prompt, options)
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


def attackers(session, seat: int, player, combat) -> bool | None:
    util = _combat_util()
    available = [c for c in player.getCreaturesInPlay() if util.canAttack(c)]
    defenders = list(combat.getDefenders())
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
        choice = session.ask(seat, "attack", prompt, options)
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


def blockers(session, seat: int, player, combat) -> bool | None:
    util = _combat_util()
    # Only attackers attacking this player, or its planeswalkers and battles:
    # CombatUtil.canBlock does not check the defender.
    attacking = [a for a in combat.getAttackers() if player.equals(combat.getDefenderPlayerByAttacker(a))]
    available = [b for b in player.getCreaturesInPlay() if util.canBlock(b, combat)]
    declared = []
    while True:
        pairs = [(b, a) for b in available if b not in declared for a in attacking if util.canBlock(a, b, combat)]
        if not pairs:
            break
        unblocked = jpype.JClass("java.util.ArrayList")()
        for a in combat.getAttackersOf(player):
            if combat.getBlockers(a).isEmpty():
                unblocked.add(a)
        incoming = int(_ai_combat().sumDamageIfUnblocked(unblocked, player))
        options = [Option("Done (no more blockers)")] + [
            Option(f"Block {card_label(a)} with {card_label(b)}", block_facts(b, a, combat, player))
            for b, a in pairs]
        prompt = f"Declare blockers (unblocked attackers deal {incoming}, your life {player.getLife()})"
        choice = session.ask(seat, "block", prompt, options)
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


def entities(session, seat: int, player, title, options, minimum: int, maximum: int) -> list | None:
    remaining = list(options)
    chosen = []
    title = str(title) if title else "Choose"
    while len(chosen) < maximum and remaining:
        can_stop = len(chosen) >= minimum
        labels = ([Option("Done")] if can_stop else []) + [Option(entity_label(e, player)) for e in remaining]
        choice = session.ask(seat, "choose_cards", f"{title} ({len(chosen)} chosen, {minimum}-{maximum})", labels)
        if choice is None:
            return None
        if can_stop and choice == 0:
            break
        chosen.append(remaining.pop(choice - (1 if can_stop else 0)))
    return chosen
