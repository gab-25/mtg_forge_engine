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
