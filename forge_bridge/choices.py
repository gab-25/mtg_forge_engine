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


def playable(player) -> list:
    """What the player can do with priority right now: land plays, spells and
    non-mana activated abilities whose costs Forge says can be paid."""
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
                                      and mana_util.canPayManaCost(sa, player, 0, False)):
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
