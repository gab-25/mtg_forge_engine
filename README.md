# Forge bridge

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
| `MAX_TURNS` | 50 | Turn limit; reaching it is a draw (`end_reason: "turn_limit"`). |
| `GAME_TTL` | 3600 | Seconds an ended game stays readable. |
| `ORPHAN_TIMEOUT` | 600 | Seconds a decision may wait for a worker to lease it; past that the client is taken as gone and the game is aborted (`end_reason: "orphaned"`). Keep it well above the queueing time of your worker pool. |
| `JAVA_OPTS` | `-Xmx2g` | JVM options. |
| `PORT` | 8080 | HTTP port. |

Build another Forge release with `docker compose build --build-arg FORGE_REF=forge-2.0.16`.

## API

| Method | Path | |
|---|---|---|
| `GET` | `/health` | `{"status":"ready","cards":N}`; 503 while loading |
| `POST` | `/games` | `{"format","seed"?,"seats":[{"name","decklist","controller"?}]×2}` → 201 game |
| `GET` | `/games/{id}` | status (`queued`/`running`/`finished`/`failed`/`aborted`), turn, winner seat, end reason |
| `GET` | `/games/{id}/events?since=N` | `{"events":[…],"next":M}` |
| `DELETE` | `/games/{id}` | abort |
| `GET` | `/decisions?wait=30&game=<id>` | the oldest pending decision of any game (or of `game`); 204 if none |
| `POST` | `/decisions/{decision_id}` | `{"choice":i}` or `{"delegate":true}`, optional `"meta":{…}` |

Formats: `standard`, `pioneer`, `modern`, `legacy`, `vintage`, `pauper`, `duel_commander`.
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

Event kinds: `log` (Forge's game log), `decision`, `fallback` (`reason`: `delegate`,
`timeout`, `withdrawn`, `orphaned`, `too_many_options`, `invalid_attack`, `invalid_block`, `error`),
`forge_ai`, `game_over`.

## Client loop

```python
import requests

BASE = "http://forge-bridge:8080"

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
docker compose run --rm --build bridge pytest -m jvm    # everything that needs Forge
```

The only Java is `java/forge/bridge/` (a `PlayerControllerAi` subclass forwarding
decisions to Python through JPype); it is compiled against Forge in the image build.

## Limitations

- Two seats per game; no persistence (a restart loses every game); no auth.
- Triggered abilities with modes or a "targeting player" get their targets from Forge's AI.
- Binary choices (coin flips, tap or untap, odd or even) are Forge's AI: their two outcomes
  depend on the kind of choice, so they are not exposed as `confirm`.
