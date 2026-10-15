# MTG Forge Engine

[Forge](https://github.com/Card-Forge/forge) (2.0.15) as an HTTP rules engine in a Docker
container. External agents — the Jev seats of `mtg_deck_tester` — answer each player
decision; Forge enforces the rules and decides whatever is not exposed. Many games run in
parallel in one JVM.

## Run

```bash
docker compose up --build        # first build compiles Forge: several minutes
curl localhost:8080/health       # 503 while the card database loads, then 200
```

The service has no authentication: compose publishes it on `127.0.0.1` only. Put it on the
same Docker network as its client.

| Variable | Default | Meaning |
|---|---|---|
| `MAX_CONCURRENT_GAMES` | 16 | Games running at once; extra games wait as `queued`. |
| `DECISION_TIMEOUT` | 120 | Seconds a leased decision may stay unanswered before Forge's AI takes it. |
| `MAX_TURNS` | 50 | Turn limit; reaching it is a draw (`end_reason: "turn_limit"`). Two-seat games count game turns; games of 3–4 seats count rounds (`MAX_TURNS` × seats game turns), so each player gets as many turns as in a duel. |
| `GAME_TTL` | 3600 | Seconds an ended game stays readable. |
| `ORPHAN_TIMEOUT` | 600 | Seconds a decision may wait for a worker to lease it; past that the client is taken as gone and the game is aborted (`end_reason: "orphaned"`). Keep it well above the queueing time of your worker pool. |
| `JAVA_OPTS` | `-Xmx2g` | JVM options. |
| `PORT` | 8080 | HTTP port. |

Build another Forge release with `docker compose build --build-arg FORGE_REF=forge-2.0.16`.

## API

| Method | Path | |
|---|---|---|
| `GET` | `/health` | `{"status":"ready","cards":N}`; 503 while loading |
| `POST` | `/games` | `{"format","seed"?,"seats":[{"name","decklist","controller"?}]}` → 201 game; 2 seats, 2–4 for `commander` |
| `POST` | `/decks/check` | `{"format","decklist"}` → `{"unresolved":[…],"unsupported_cards":[…],"missing_commander"}`, no game started |
| `GET` | `/games/{id}` | status (`queued`/`running`/`finished`/`failed`/`aborted`), turn, winner seat, end reason, eliminations |
| `GET` | `/games/{id}/events?since=N` | `{"events":[…],"next":M}` |
| `DELETE` | `/games/{id}` | abort |
| `GET` | `/decisions?wait=30&game=<id>` | the oldest pending decision of any game (or of `game`); 204 if none |
| `POST` | `/decisions/{decision_id}` | `{"choice":i}` or `{"delegate":true}`, optional `"meta":{…}` |

Formats: `standard`, `pioneer`, `modern`, `legacy`, `vintage`, `pauper` (2 seats, 20 life),
`duel_commander` (2 seats, 20 life), `commander` (2–4 seats, 40 life). Both commander formats
apply the 21 commander damage rule. Another seat count is a 422.
Decklists are Moxfield/MTGO text (`4 Lightning Bolt`, `Commander`/`Sideboard` headers,
`*CMDR*`). Unknown cards: 422 `{"detail":{"unresolved":{"<seat>":[…]}}}`. Deck legality is
not checked.

A decision:

```json
{"decision_id":"…","game_id":"…","seat":0,"kind":"attack","prompt":"Declare attackers",
 "view":{…},"options":[{"index":0,"label":"Done (no more attackers)","facts":[]},
 {"index":1,"label":"Attack with Goblin Guide #12 (2/2) -> Player B (20 life)",
  "facts":["deals 2 damage if unblocked","no creature can block it"]}]}
```

Kinds: `mulligan`, `bottom`, `priority`, `target`, `attack`, `block`, `choose_cards`,
`confirm`, `mode`. Multi-selects come one pick at a time, option 0 being "Done" once the
minimum is reached. Everything else (mana payment, damage assignment, scry, …) is decided
by Forge's AI and logged as a `forge_ai` event.

A priority decision offers only what can be played: land plays, and spells and abilities
whose costs can be paid and whose targets exist, a spell that targets the stack (Stifle,
Spell Snare, …) included. A `target` option is a player, a card, or a spell or ability on
the stack (`Lightning Bolt deals 3 damage to … (Lightning Bolt #12, B's, on the stack)`).

Event kinds: `log` (Forge's game log), `decision`, `fallback` (`reason`: `delegate`,
`timeout`, `withdrawn`, `orphaned`, `too_many_options`, `invalid_attack`, `invalid_block`, `error`),
`play_failed` (a spell or ability the client chose that Forge did not play, so the same
priority decision comes back: `payload.ability` is its label, `payload.reason` is `modes`,
`targets` or `costs`), `forge_ai`, `game_over`.

## Multiplayer

A `commander` game seats 2–4 players, each `external` or `forge_ai`, in seat order.

- The view lists every other seat under `opponents`. Each player (`you` included) has
  `in_game` (false once they lost: their permanents leave the battlefield) and
  `commander_damage` (`[{"commander","id","seat","damage"}]`, damage taken from each
  commander, `seat` its owner's). `combat.attackers[].defender_seat` is the seat under attack.
- Attack options name the defending player; block options only list the attackers
  attacking you or your permanents; the first mulligan is free (Forge's multiplayer rule).
- `winner` is the last seat standing. `game_over` (and `GET /games/{id}`) has
  `eliminations`: `[{"seat","turn","reason"}]`, first eliminated first, `reason` one of
  Forge's `LifeReachedZero`, `CommanderDamage`, `Milled`, `Poisoned`, `SpellEffect`,
  `OpponentWon`, `Conceded`.

## Client loop

```python
import requests

BASE = "http://mtg-forge-engine:8080"

def worker(choose):
    """choose(decision) -> (index, meta) or (None, meta) to let Forge decide."""
    while True:
        r = requests.get(f"{BASE}/decisions", params={"wait": 30}, timeout=40)
        if r.status_code == 204:
            continue
        decision = r.json()
        index, meta = choose(decision)
        body = {"delegate": True, "meta": meta} if index is None else {"choice": index, "meta": meta}
        requests.post(f"{BASE}/decisions/{decision['decision_id']}", json=body, timeout=10)
```

Run M such workers (threads) to have M Jev calls in flight across all open games.

## Development

```bash
uv sync
uv run pytest -m "not jvm"                              # pure tests, no Forge
docker compose run --rm --build mtg-forge-engine pytest -m jvm    # everything that needs Forge
```

The only Java is `java/forge/bridge/` (a `PlayerControllerAi` subclass forwarding
decisions to Python through JPype); it is compiled against Forge in the image build.

## Limitations

- No persistence (a restart loses every game); no auth.
- Triggered abilities with modes or a "targeting player" get their targets from Forge's AI.
- Binary choices (coin flips, tap or untap, odd or even) are Forge's AI: their two outcomes
  depend on the kind of choice, so they are not exposed as `confirm`.
