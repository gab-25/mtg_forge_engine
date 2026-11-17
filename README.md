# MTG Forge Engine

[Forge](https://github.com/Card-Forge/forge) (2.0.15) as an HTTP rules engine in a Docker
container. A client posts two to four decklists; Forge's AI plays every seat under Forge's
rules, and the client reads the game log and the outcome. Many games run in parallel in one
JVM.

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
| `MAX_TURNS` | 50 | Turn limit; reaching it is a draw (`end_reason: "turn_limit"`). Two-seat games count game turns; games of 3–4 seats count rounds (`MAX_TURNS` × seats game turns), so each player gets as many turns as in a duel. |
| `GAME_TTL` | 3600 | Seconds an ended game stays readable. |
| `JAVA_OPTS` | `-Xmx2g` | JVM options. |
| `PORT` | 8080 | HTTP port. |

Build another Forge release with `docker compose build --build-arg FORGE_REF=forge-2.0.16`.

## API

| Method | Path | |
|---|---|---|
| `GET` | `/health` | `{"status":"ready","cards":N}`; 503 while loading |
| `POST` | `/games` | `{"format","seed"?,"seats":[{"name","decklist"}]}` → 201 game with `"seats":[{"name","unsupported_cards"}]`; 2 seats, 2–4 for `commander` |
| `POST` | `/decks/check` | `{"format","decklist"}` → `{"unresolved":[…],"unsupported_cards":[…],"missing_commander"}`, no game started |
| `GET` | `/games/{id}` | status (`queued`/`running`/`finished`/`failed`/`aborted`), turn, winner seat, end reason, eliminations |
| `GET` | `/games/{id}/events?since=N` | `{"events":[…],"next":M}` |
| `DELETE` | `/games/{id}` | abort: the game ends as a draw (`end_reason: "aborted"`) at its next game event |

Formats: `standard`, `pioneer`, `modern`, `legacy`, `vintage`, `pauper` (2 seats, 20 life),
`duel_commander` (2 seats, 20 life), `commander` (2–4 seats, 40 life). Both commander formats
apply the 21 commander damage rule. Another seat count is a 422.
Decklists are Moxfield/MTGO text (`4 Lightning Bolt`, `Commander`/`Sideboard` headers,
`*CMDR*`). Unknown cards: 422 `{"detail":{"unresolved":{"<seat>":[…]}}}`. Deck legality is
not checked.

Every seat is played by Forge's AI (its `Default` profile). A `seed` (random if omitted)
drives the shuffles and every other random draw of the game, so the same seed and decks
replay the same game.

Event kinds: `log` (Forge's game log, `payload.type` its entry type) and `game_over`
(`payload`: `winner`, `end_reason`, `eliminations`). The log is read when the game ends, so
a game's events appear all at once, `game_over` last; poll `GET /games/{id}` for its status
and turn meanwhile.

`end_reason`: the name of Forge's `GameEndReason` when the game ends by itself, else
`turn_limit` or `aborted`.

## Multiplayer

A `commander` game seats 2–4 players, in seat order. `winner` is the last seat standing.
`game_over` (and `GET /games/{id}`) has `eliminations`: `[{"seat","turn","reason"}]`, first
eliminated first, `reason` one of Forge's `LifeReachedZero`, `CommanderDamage`, `Milled`,
`Poisoned`, `SpellEffect`, `OpponentWon`, `Conceded`. Two-seat games report the loser there
too.

## Client loop

```python
import time

import requests

BASE = "http://mtg-forge-engine:8080"

def play(fmt, seats, seed=None):
    """seats: [{"name", "decklist"}]. Returns the final game and its events."""
    game = requests.post(f"{BASE}/games", json={"format": fmt, "seed": seed, "seats": seats},
                         timeout=60).json()
    while (state := requests.get(f"{BASE}/games/{game['id']}", timeout=10).json())["status"] in (
            "queued", "running"):
        time.sleep(2)
    events = requests.get(f"{BASE}/games/{game['id']}/events", params={"since": 0}, timeout=10).json()
    return state, events["events"]
```

## Development

```bash
uv sync
uv run pytest -m "not jvm"                              # pure tests, no Forge
docker compose run --rm --build mtg-forge-engine pytest -m jvm    # everything that needs Forge
```

The only Java is `java/forge/bridge/` (game event subscribers for the turn limit, abort and
eliminations, and the per-game random generator); it is compiled against Forge in the image
build.

## Limitations

- No persistence (a restart loses every game); no auth.
- Only Forge's AI plays: no seat can be driven from outside.
