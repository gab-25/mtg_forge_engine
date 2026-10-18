# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Forge (the Java MTG rules engine, pinned to `forge-2.0.15` via the `FORGE_REF` build arg) exposed over HTTP. External agents answer player decisions; Forge enforces the rules and decides everything not exposed. Many games run in parallel in one JVM, embedded in the Python process through JPype. The README is the API contract (endpoints, decision kinds, event kinds, env vars): keep it in sync when behaviour changes.

## Commands

```bash
uv sync
uv run pytest -m "not jvm"                                        # pure tests, run locally
uv run pytest tests/test_queue.py::test_name                      # a single pure test
docker compose run --rm --build mtg-forge-engine pytest -m jvm    # tests needing Forge
docker compose run --rm --build mtg-forge-engine pytest tests/test_combat.py -k name
docker compose up --build                                         # run the service on 127.0.0.1:8080
```

Forge (`forge.jar`, `res/`, the compiled bridge) exists only in the Docker image under `/opt/forge`; the first build compiles Forge with Maven and takes several minutes. Tests that need it are marked `jvm` and use the session-scoped `forge` fixture (`tests/conftest.py`), which skips outside the image. There is no linter or formatter configured.

CI (`.github/workflows/ci.yml`) builds the image on every push to `main` and pushes it to `ghcr.io/<repo>` (tags `latest` and `sha-<commit>`).

## Architecture

**Request path.** `api.py` (FastAPI) holds module-level singletons: one `DecisionQueue` and one `GameRegistry`. Forge boots on a background thread at startup (`jvm.start`), so `/health` and game creation return 503 until the card database is loaded. Modules that import `jpype` must not be imported before the JVM runs; `api.py` imports `decks` lazily inside handlers for this reason.

**One game = one Python thread.** `GameRegistry.create` builds a `GameSession` whose `_run` thread acquires a slot from a semaphore (`MAX_CONCURRENT_GAMES`; extra games stay `queued`) and calls Forge's `Match.startGame`, which runs the whole game synchronously on that thread. Only the game thread may touch the Forge `Game` (not thread-safe); `abort()` from a request thread just sets a flag and withdraws decisions, and the game thread ends the game at its next callback.

**Decision flow (Java → Python → HTTP → back).**
1. External seats are `BridgeLobbyPlayer`s whose controller is `BridgeController` (`java/forge/bridge/`), a subclass of Forge's `PlayerControllerAi`. For each exposed decision it first calls a `DecisionHandler`; a `null` return hands the decision back to Forge's AI. Non-exposed decisions are always the AI's and are reported via `onAiDecision`.
2. `DecisionHandler` is implemented in Python (`handler.py`, a JPype `@JImplements` class created lazily once the JVM exists). Any Python exception is caught there, logged as a `fallback` event with reason `error`, and the AI decides.
3. `choices.py` turns each Forge decision into one or more single-choice questions (multi-selects are asked one pick at a time, option 0 = "Done" once the minimum is reached), labelled by `labels.py`, and calls `GameSession.ask`. With `SIMULATE=1`, attack, block and priority decisions are instead one question over complete actions (`candidates.py`, a fixed enumeration), each with the position it leads to, simulated on a copy of the game with the opponents silenced (`simulation.py`, Forge's `GameCopier`/`GameSimulator`) and diffed by `outcome.py`; while a simulation runs, `handler.py` leaves the copy's decisions to Forge's AI (`session.simulating`).
4. `ask` builds the player's `view` (`view.py`), submits a `Decision` to the queue and **blocks the game thread** in `queue.wait` until a worker leases it (`GET /decisions`) and answers it (`POST /decisions/{id}`), or until the lease times out (`DECISION_TIMEOUT` → AI), nobody leases it (`ORPHAN_TIMEOUT` → game aborted as `orphaned`) or the game is withdrawn.

`queue.py`, `registry.py`, `decklist.py`, `formats.py` and `settings.py` are pure Python and unit-testable without Forge; everything importing `jpype` needs the JVM.

**Determinism.** `GameRandom` replaces Forge's global `MyRandom` with a per-thread seeded generator (`bindThisThread(seed)` at the start of each game thread), so concurrent games don't share a random sequence and a game is reproducible from its `seed`.

**Game end bookkeeping** lives in small Java helpers because Forge doesn't expose it: `TurnLimit` ends the game in a draw past the turn limit even with no external seat to call back (multiplayer counts rounds: `MAX_TURNS × seats`), and `EliminationTracker` records the turn each player lost.

**Memory.** Python handlers and Java game objects reference each other across the JVM boundary, which neither GC can see through: `GameSession._release` must break those references when a game ends. Ended games are purged from the registry after `GAME_TTL`. Nothing is persisted.

**Java changes.** The bridge is compiled with `javac` against `forge.jar` during the image build (the `forge` stage of the `Dockerfile`), so Java edits only take effect after `docker compose ... --build`. When overriding `PlayerControllerAi` methods, check the signature against the pinned Forge release.

Design specs and implementation plans for past features are in `docs/superpowers/`.
