"""HTTP API. See the README for the client loop."""

import contextlib
import logging
import random
import threading

import anyio.to_thread
from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field, model_validator

from . import jvm
from .decklist import parse_decklist
from .formats import FORMATS
from .queue import ChoiceOutOfRange, DecisionQueue, UnknownDecision
from .registry import GameRegistry
from .session import SeatSpec
from .settings import load_settings

logger = logging.getLogger(__name__)

settings = load_settings()
queue = DecisionQueue(settings.decision_timeout)
registry = GameRegistry(settings, queue)


def _boot() -> None:
    try:
        jvm.start(settings.forge_home)
    except Exception:
        logger.exception("Forge failed to start")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Long-polling workers each hold a thread while they wait.
    anyio.to_thread.current_default_thread_limiter().total_tokens = 256
    threading.Thread(target=_boot, name="forge-boot", daemon=True).start()
    yield


app = FastAPI(title="Forge bridge", lifespan=lifespan)


class SeatIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    decklist: str = Field(min_length=1)
    controller: str = Field("external", pattern="^(external|forge_ai)$")


class GameIn(BaseModel):
    format: str
    seed: int | None = None
    seats: list[SeatIn] = Field(min_length=2, max_length=2)


class AnswerIn(BaseModel):
    choice: int | None = None
    delegate: bool = False
    meta: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def choice_or_delegate(self):
        if (self.choice is not None) == self.delegate:
            raise ValueError("give either a choice or delegate: true")
        return self


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
    if not jvm.is_ready():
        raise HTTPException(503, "Forge is still loading")
    fmt = FORMATS.get(body.format)
    if fmt is None:
        raise HTTPException(422, f"unknown format {body.format!r}; known: {sorted(FORMATS)}")
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
    session = registry.create(fmt, seed, [SeatSpec(s.name, b.deck, s.controller) for s, b in zip(body.seats, builds)])
    return {
        **session.summary(),
        "seats": [{"name": seat.name, "controller": seat.controller, "unsupported_cards": build.unsupported}
                  for seat, build in zip(session.seats, builds)],
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


@app.get("/decisions")
def lease_decision(wait: float = Query(30, ge=0, le=60), game: str | None = None):
    decision = queue.lease(wait, game)
    if decision is None:
        return Response(status_code=204)
    return decision.as_dict()


@app.post("/decisions/{decision_id}", status_code=204)
def answer_decision(decision_id: str, body: AnswerIn):
    try:
        queue.answer(decision_id, body.choice, delegate=body.delegate, meta=body.meta)
    except UnknownDecision:
        raise HTTPException(409, "decision unknown, already answered or expired")
    except ChoiceOutOfRange as exc:
        raise HTTPException(422, str(exc))
    return Response(status_code=204)
