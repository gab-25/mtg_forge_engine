# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Forge (the Java MTG rules engine, pinned to `forge-2.0.15` via the `FORGE_REF` build arg) exposed over HTTP. A client posts decklists; Forge's AI plays every seat and the client reads the game log and the outcome. No seat can be driven from outside. Many games run in parallel in one JVM, embedded in the Python process through JPype. The README is the API contract (endpoints, event kinds, env vars): keep it in sync when behaviour changes.

## Commands

```bash
uv sync
uv run pytest -m "not jvm"                                        # pure tests, run locally
uv run pytest tests/test_decklist.py::test_name                   # a single pure test
docker compose run --rm --build mtg-forge-engine pytest -m jvm    # tests needing Forge
docker compose run --rm --build mtg-forge-engine pytest tests/test_session.py -k name
docker compose up --build                                         # run the service on 127.0.0.1:8080
```

Forge (`forge.jar`, `res/`, the compiled bridge) exists only in the Docker image under `/opt/forge`; the first build compiles Forge with Maven and takes several minutes. Tests that need it are marked `jvm` and use the session-scoped `forge` fixture (`tests/conftest.py`), which skips outside the image. There is no linter or formatter configured.

CI (`.github/workflows/ci.yml`) builds the image on every push to `main` and pushes it to `ghcr.io/<repo>` (tags `latest` and `sha-<commit>`).

## Architecture

**Request path.** `api.py` (FastAPI) holds one module-level `GameRegistry`. Forge boots on a background thread at startup (`jvm.start`), so `/health` and game creation return 503 until the card database is loaded. Modules that import `jpype` must not be imported before the JVM runs; `api.py` imports `decks` lazily inside handlers for this reason.

**One game = one Python thread.** `GameRegistry.create` builds a `GameSession` whose `_run` thread acquires a slot from a semaphore (`MAX_CONCURRENT_GAMES`; extra games stay `queued`) and calls Forge's `Match.startGame`, which runs the whole game synchronously on that thread. Every seat is a plain Forge AI player (`GamePlayerUtil.createAiPlayer`), so the game never calls back into Python: the log is read and the outcome recorded once `startGame` returns. Only the game thread may touch the Forge `Game` (not thread-safe).

`registry.py`, `decklist.py`, `formats.py` and `settings.py` are pure Python and unit-testable without Forge; everything importing `jpype` needs the JVM.

**Determinism.** `GameRandom` replaces Forge's global `MyRandom` with a per-thread seeded generator (`bindThisThread(seed)` at the start of each game thread), so concurrent games don't share a random sequence and a game is reproducible from its `seed`.

**Game end bookkeeping** lives in small Java event subscribers (`java/forge/bridge/`), because Forge doesn't expose it and nothing else runs on the game thread: `TurnLimit` ends the game in a draw past the turn limit (multiplayer counts rounds: `MAX_TURNS × seats`), `Abort` ends it in a draw at the next game event once `DELETE /games/{id}` flipped its switch (a request thread never touches the `Game`), and `EliminationTracker` records the turn each player lost.

**Memory.** Ended games stay in the registry for `GAME_TTL`; `GameSession._release` drops the session's references to the Forge game when it ends so the JVM can collect it right away. Nothing is persisted.

**Java changes.** The bridge is compiled with `javac` against `forge.jar` during the image build (the `forge` stage of the `Dockerfile`), so Java edits only take effect after `docker compose ... --build`. When using Forge classes, check their API against the pinned Forge release.

Design specs and implementation plans for past features are in `docs/superpowers/`.
