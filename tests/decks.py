"""Decklists the tests play: a fast red deck against green creatures, so that games
end in a few turns; Commander lists for duels and pods."""

RED = """
20 Mountain
4 Goblin Guide
4 Monastery Swiftspear
4 Lightning Bolt
4 Lava Spike
4 Rift Bolt
4 Fiery Confluence
4 Faithless Looting
4 Mogg Fanatic
4 Bloodghast
4 Keldon Marauders
"""

GREEN = """
24 Forest
4 Llanowar Elves
4 Grizzly Bears
4 Centaur Courser
4 Kalonian Tusker
4 Giant Growth
4 Elvish Visionary
4 Garruk's Companion
4 Thragtusk
"""

DUEL_COMMANDER = """
Commander
1 Krenko, Mob Boss

Deck
1 Lightning Bolt
1 Goblin Guide
97 Mountain
"""

# Legality is not checked, so the pod deck may run more than one copy of a card.
COMMANDER = """
Commander
1 Krenko, Mob Boss

Deck
39 Mountain
6 Goblin Guide
6 Monastery Swiftspear
6 Lightning Bolt
6 Lava Spike
6 Rift Bolt
6 Keldon Marauders
6 Mogg Fanatic
6 Bloodghast
6 Fiery Confluence
6 Faithless Looting
"""
