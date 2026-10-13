"""What one seat can see of a Forge game. Hidden information stays hidden:
opponents' hands and every library are counts only, face-down cards are unnamed."""

import jpype


def _zone(name: str):
    return getattr(jpype.JClass("forge.game.zone.ZoneType"), name)


def _card(card, visible: bool = True) -> dict:
    if not visible:
        return {"id": int(card.getId()), "name": "Face-down card"}
    data = {
        "id": int(card.getId()),
        "name": str(card.getName()),
        "mana_cost": "" if card.getManaCost().isNoCost() else str(card.getManaCost()),
        "types": str(card.getType()),
        # Forge stores line breaks of card text as a literal backslash-n.
        "text": str(card.getOracleText()).replace("\\n", "\n"),
    }
    if card.isCreature():
        data["power"] = int(card.getNetPower())
        data["toughness"] = int(card.getNetToughness())
    return data


def _permanent(card, viewer) -> dict:
    visible = not card.isFaceDown() or card.getController().equals(viewer)
    data = _card(card, visible)
    attached = card.getEntityAttachedTo()
    data.update({
        "tapped": bool(card.isTapped()),
        "summoning_sick": bool(card.isSick()),
        "damage": int(card.getDamage()),
        "counters": {str(entry.getElement()): int(entry.getCount()) for entry in card.getCounters().entrySet()},
        "attached_to": int(attached.getId()) if attached is not None else None,
    })
    return data


def _commanders(player) -> list[dict]:
    return [{**_card(c), "tax": 2 * int(player.getCommanderCast(c))} for c in player.getCommanders()]


def player_view(session, seat: int) -> dict:
    game = session.game
    you = session.player(seat)
    phases = game.getPhaseHandler()
    seats = range(len(session.seats))
    view = {
        "format": session.format.label,
        "turn": int(phases.getTurn()),
        "active_seat": session.seat_of(phases.getPlayerTurn()) if phases.getPlayerTurn() is not None else None,
        "phase": str(phases.getPhase()) if phases.getPhase() is not None else "",
        "you": {
            "seat": seat,
            "name": session.seats[seat].name,
            "life": int(you.getLife()),
            "hand": [_card(c) for c in you.getCardsIn(_zone("Hand"))],
            "library": int(you.getCardsIn(_zone("Library")).size()),
            "graveyard": [_card(c) for c in you.getCardsIn(_zone("Graveyard"))],
            "exile": [_card(c, not c.isFaceDown()) for c in you.getCardsIn(_zone("Exile"))],
            "mana_pool": int(you.getManaPool().totalMana()),
            "mana_available": int(jpype.JClass("forge.ai.ComputerUtilMana").getAvailableManaEstimate(you)),
            "lands_played": int(you.getLandsPlayedThisTurn()),
            "commanders": _commanders(you),
        },
        "opponents": [],
        "battlefield": {},
        "stack": [],
        "combat": None,
    }
    for other in seats:
        player = session.player(other)
        view["battlefield"][str(other)] = [_permanent(c, you) for c in player.getCardsIn(_zone("Battlefield"))]
        if other == seat:
            continue
        view["opponents"].append({
            "seat": other,
            "name": session.seats[other].name,
            "life": int(player.getLife()),
            "hand": int(player.getCardsIn(_zone("Hand")).size()),
            "library": int(player.getCardsIn(_zone("Library")).size()),
            "graveyard": [_card(c) for c in player.getCardsIn(_zone("Graveyard"))],
            "exile": [_card(c, not c.isFaceDown()) for c in player.getCardsIn(_zone("Exile"))],
            "commanders": _commanders(player),
        })
    for item in game.getStack():
        view["stack"].append({
            "text": str(item.getStackDescription()),
            "source": str(item.getSourceCard().getName()),
            "controller": session.seat_of(item.getActivatingPlayer()),
        })
    combat = game.getCombat()
    if combat is not None:
        view["combat"] = {"attackers": [
            {
                "id": int(a.getId()),
                "name": str(a.getName()),
                "defender": str(combat.getDefenderByAttacker(a)),
                "blocked_by": [int(b.getId()) for b in combat.getBlockers(a)],
            }
            for a in combat.getAttackers()
        ]}
    return view
