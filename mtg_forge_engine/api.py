"""HTTP API. See the README for the endpoints."""

import contextlib
import logging
import random
import threading

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field

from . import jvm
from .decklist import parse_decklist
from .formats import FORMATS
from .registry import GameRegistry
from .session import SeatSpec
from .settings import load_settings

logger = logging.getLogger(__name__)

settings = load_settings()
registry = GameRegistry(settings)


def _boot() -> None:
    try:
        jvm.start(settings.forge_home)
    except Exception:
        logger.exception("Forge failed to start")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_boot, name="forge-boot", daemon=True).start()
    yield


app = FastAPI(title="MTG Forge Engine", lifespan=lifespan)


class SeatIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    decklist: str = Field(min_length=1)


class GameIn(BaseModel):
    format: str
    seed: int | None = None
    seats: list[SeatIn] = Field(min_length=2, max_length=4)


class DeckCheckIn(BaseModel):
    format: str
    decklist: str = Field(min_length=1)


def _session(game_id: str):
    session = registry.get(game_id)
    if session is None:
        raise HTTPException(404, "no such game")
    return session


@app.get("/health")
def health(response: Response):
    if not jvm.is_ready():
        response.status_code = 503
        return {"status": "starting"}
    return {"status": "ready", "cards": jvm.card_count()}


@app.post("/games", status_code=201)
def create_game(body: GameIn):
    fmt = FORMATS.get(body.format)
    if fmt is None:
        raise HTTPException(422, f"unknown format {body.format!r}; known: {sorted(FORMATS)}")
    if error := fmt.seat_error(len(body.seats)):
        raise HTTPException(422, error)
    if not jvm.is_ready():
        raise HTTPException(503, "Forge is still loading")
    from .decks import build_deck

    builds = []
    unresolved = {}
    for seat in body.seats:
        parsed = parse_decklist(seat.decklist)
        if fmt.commander and not parsed.commanders:
            raise HTTPException(422, f"seat {seat.name!r} has no commander")
        build = build_deck(seat.name, parsed, commander=fmt.commander)
        if build.unresolved:
            unresolved[seat.name] = build.unresolved
        builds.append(build)
    if unresolved:
        raise HTTPException(422, {"unresolved": unresolved})
    seed = body.seed if body.seed is not None else random.randrange(2**31)
    session = registry.create(fmt, seed, [SeatSpec(s.name, b.deck) for s, b in zip(body.seats, builds)])
    return {
        **session.summary(),
        "seats": [{"name": seat.name, "unsupported_cards": build.unsupported}
                  for seat, build in zip(session.seats, builds)],
    }


@app.post("/decks/check")
def check_deck(body: DeckCheckIn):
    """What Forge makes of one decklist, without starting a game."""
    if not jvm.is_ready():
        raise HTTPException(503, "Forge is still loading")
    fmt = FORMATS.get(body.format)
    if fmt is None:
        raise HTTPException(422, f"unknown format {body.format!r}; known: {sorted(FORMATS)}")
    from .decks import build_deck

    parsed = parse_decklist(body.decklist)
    build = build_deck("check", parsed, commander=fmt.commander)
    return {
        "unresolved": build.unresolved,
        "unsupported_cards": build.unsupported,
        "missing_commander": fmt.commander and not parsed.commanders,
    }


@app.get("/games/{game_id}")
def get_game(game_id: str):
    return _session(game_id).summary()


@app.get("/games/{game_id}/events")
def get_events(game_id: str, since: int = Query(0, ge=0)):
    events = _session(game_id).events_since(since)
    return {"events": events, "next": since + len(events)}


@app.delete("/games/{game_id}", status_code=204)
def delete_game(game_id: str):
    if not registry.abort(game_id):
        raise HTTPException(404, "no such game")
    return Response(status_code=204)

