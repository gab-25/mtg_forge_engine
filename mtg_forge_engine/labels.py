"""Human-readable names for Forge objects, used in prompts and option labels."""

import jpype


def card_label(card) -> str:
    label = f"{card.getName()} #{card.getId()}"
    if card.isCreature():
        label += f" ({card.getNetPower()}/{card.getNetToughness()})"
    return label


def entity_label(entity, viewer) -> str:
    if isinstance(entity, jpype.JClass("forge.game.player.Player")):
        if entity.equals(viewer):
            return f"You ({entity.getLife()} life)"
        return f"Player {entity.getName()} ({entity.getLife()} life)"
    controller = entity.getController()
    whose = "your" if controller is not None and controller.equals(viewer) else f"{controller.getName()}'s"
    zone = entity.getZone()
    where = str(zone.getZoneType()).lower() if zone is not None else "nowhere"
    return f"{card_label(entity)} ({whose}, {where})"


def ability_label(sa) -> str:
    card = sa.getHostCard()
    name = f"{card.getName()} #{card.getId()}"
    if sa.isLandAbility():
        return f"Play {name}"
    if sa.isSpell():
        return f"Cast {name} for {sa.getPayCosts().toSimpleString()}: {sa.getDescription()}"
    return f"Activate {name}: {sa.getDescription()}"


def stack_item_label(sa, viewer) -> str:
    controller = sa.getActivatingPlayer()
    whose = "your" if controller is not None and controller.equals(viewer) else f"{controller.getName()}'s"
    return f"{sa.getStackDescription()} ({card_label(sa.getHostCard())}, {whose}, on the stack)"


def target_label(target, viewer) -> str:
    """A target: a player, a card, or a spell or ability on the stack."""
    if isinstance(target, jpype.JClass("forge.game.spellability.SpellAbility")):
        return stack_item_label(target, viewer)
    return entity_label(target, viewer)


def attack_plan_label(plan, viewer) -> str:
    """A whole attack: ``"No attack"``, or the attackers grouped by defender."""
    if not plan:
        return "No attack"
    groups: dict = {}
    for attacker, defender in plan:
        groups.setdefault(defender, []).append(attacker)
    return "; ".join(
        f"Attack with {', '.join(card_label(a) for a in attackers)} -> {entity_label(defender, viewer)}"
        for defender, attackers in groups.items())


def block_plan_label(plan) -> str:
    """A whole set of blocks: ``"No block"``, or one clause per attacker blocked."""
    if not plan:
        return "No block"
    groups: dict = {}
    for blocker, attacker in plan:
        groups.setdefault(attacker, []).append(blocker)
    return "; ".join(f"Block {card_label(attacker)} with {' and '.join(card_label(b) for b in blockers)}"
                     for attacker, blockers in groups.items())


def ability_target_label(sa, target, viewer) -> str:
    """A play with its target chosen, or with the target left for the next question (``None``)."""
    if target is None:
        return f"{ability_label(sa)} (choose the target next)"
    return f"{ability_label(sa)} targeting {target_label(target, viewer)}"
