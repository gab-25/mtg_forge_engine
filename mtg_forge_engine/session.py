"""One game: a Forge match on its own thread, its event log and its outcome.

The game thread is the only one that touches the Forge Game. Decisions for
external seats reach ``ask`` through the Java shim (mtg_forge_engine.handler), which
blocks the game thread until a client answers.
"""

import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass

import jpype

from .formats import Format
from .queue import Decision, DecisionQueue

logger = logging.getLogger(__name__)

MAX_OPTIONS = 255
TURN_START = re.compile(r"^Turn (\d+) ")


@dataclass(frozen=True)
class Option:
    label: str
    facts: tuple[str, ...] = ()


@dataclass(frozen=True)
class SeatSpec:
    name: str
    deck: object  # forge.deck.Deck
    controller: str  # "external" or "forge_ai"


class GameSession:
    def __init__(self, game_id: str, fmt: Format, seed: int, seats: list[SeatSpec], queue: DecisionQueue,
                 max_turns: int, slots: threading.Semaphore):
        self.id = game_id
        self.format = fmt
        self.seed = seed
        self.seats = seats
        self.queue = queue
        self.max_turns = max_turns
        # MAX_TURNS counts rounds in multiplayer: each player gets as many turns as in a duel.
        self.turn_limit = max_turns * len(seats) if len(seats) > 2 else max_turns
        self.status = "queued"
        self.winner: int | None = None
        self.end_reason: str | None = None
        self.error: str | None = None
        self.ended_at: float | None = None
        self._slots = slots
        self._events: list[dict] = []
        self._lock = threading.Lock()
        self._abort = threading.Event()
        self._game = None
        self._match = None
        self._players: list = []
        self._final_turn = 0
        # The Python side of each external seat's Java controller.
        self.handlers: list = []
        self._log_seen = 0
        # The turn of the last Forge log entry read: the log is read in batches.
        self._log_turn = 0
        self._turn_limit_hit = False
        self._orphaned = False
        self._thread = threading.Thread(target=self._run, name=f"game-{game_id}", daemon=True)

    # --- lifecycle --------------------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def abort(self) -> None:
        """Called from a request thread. Forge's Game is not thread-safe, so the
        game thread ends the game at its next decision (withdrawn decisions wake
        it up). A game with no external seat never calls back: it is ended from
        here, at the risk of racing Forge's AI."""
        self._abort.set()
        self.queue.withdraw_game(self.id)
        if all(seat.controller == "forge_ai" for seat in self.seats):
            self._end_game()

    @property
    def game(self):
        return self._game

    @property
    def turn(self) -> int:
        game = self._game
        return int(game.getPhaseHandler().getTurn()) if game is not None else self._final_turn

    def summary(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "format": self.format.label,
            "seed": self.seed,
            "turn": self.turn,
            "winner": self.winner,
            "end_reason": self.end_reason,
            "error": self.error,
        }

    def events_since(self, since: int) -> list[dict]:
        with self._lock:
            return list(self._events[max(since, 0):])

    def player(self, seat: int):
        return self._players[seat]

    def seat_of(self, player) -> int:
        for index, candidate in enumerate(self._players):
            if candidate.equals(player):
                return index
        raise ValueError(f"{player} is not in game {self.id}")

    # --- decisions --------------------------------------------------------------

    def ask(self, seat: int, kind: str, prompt: str, options: list[Option]) -> int | None:
        """Blocks the game thread until the seat's client answers. None: Forge's AI decides."""
        if self._abort.is_set():
            self._end_game()
            return None
        if not options or self._past_turn_limit():
            return None
        if len(options) == 1:
            return 0
        if len(options) > MAX_OPTIONS:
            self.fallback(seat, kind, "too_many_options")
            return None
        self._sync_log()
        from .view import player_view

        decision = Decision(
            id=uuid.uuid4().hex,
            game_id=self.id,
            seat=seat,
            kind=kind,
            prompt=prompt,
            view=player_view(self, seat),
            options=[{"index": i, "label": o.label, "facts": list(o.facts)} for i, o in enumerate(options)],
        )
        self.queue.submit(decision)
        answer = self.queue.wait(decision)
        if answer.reason == "orphaned":
            # No client took the decision: nobody is playing this game any more.
            self._orphaned = True
            self._abort.set()
            self.fallback(seat, kind, answer.reason)
            self._end_game()
            return None
        if answer.choice is None:
            self.fallback(seat, kind, answer.reason, answer.meta)
            return None
        self._event("decision", seat, f"{kind}: {options[answer.choice].label}",
                    {"kind": kind, "choice": answer.choice, **answer.meta})
        return answer.choice

    def fallback(self, seat: int, kind: str, reason: str, meta: dict | None = None) -> None:
        self._event("fallback", seat, f"{kind}: decided by Forge AI ({reason})",
                    {"kind": kind, "reason": reason, **(meta or {})})

    def on_ai_decision(self, seat: int, method: str) -> None:
        self._event("forge_ai", seat, f"{method}: decided by Forge AI", {"method": method})
        if self._abort.is_set():
            self._end_game()
        else:
            self._past_turn_limit()

    # --- internals --------------------------------------------------------------

    def _run(self) -> None:
        with self._slots:
            if self._abort.is_set():
                self._finish("aborted")
                return
            self.status = "running"
            try:
                jpype.JClass("forge.bridge.GameRandom").bindThisThread(self.seed)
                self._game = self._create_game()
                if not self._abort.is_set():
                    self._match.startGame(self._game)
                self._sync_log()
                self._record_outcome()
                self._finish("aborted" if self._abort.is_set() else "finished")
            except Exception as exc:
                logger.exception("game %s failed", self.id)
                self.error = f"{type(exc).__name__}: {exc}"
                self._finish("failed")
            finally:
                self._release()

    def _create_game(self):
        J = jpype.JClass
        game_type = J("forge.game.GameType").Commander if self.format.commander else J("forge.game.GameType").Constructed
        rules = J("forge.game.GameRules")(game_type)
        rules.setAppliedVariants(J("java.util.EnumSet").of(game_type))
        rules.setGamesPerMatch(1)
        registered = J("java.util.ArrayList")()
        registered_player = J("forge.game.player.RegisteredPlayer")
        for index, seat in enumerate(self.seats):
            rp = registered_player.forCommander(seat.deck) if self.format.commander else registered_player(seat.deck)
            rp.setStartingLife(self.format.starting_life)
            rp.setPlayer(self._lobby_player(index, seat))
            registered.add(rp)
        self._match = J("forge.game.Match")(rules, registered, f"mtg-forge-engine {self.id}")
        game = self._match.createGame()
        self._players = list(game.getRegisteredPlayers())
        return game

    def _lobby_player(self, index: int, seat: SeatSpec):
        if seat.controller == "forge_ai":
            return jpype.JClass("forge.player.GamePlayerUtil").createAiPlayer(seat.name, 0, 0, None, "Default")
        from .handler import make_handler

        handler = make_handler(self, index)
        self.handlers.append(handler)
        return jpype.JClass("forge.bridge.BridgeLobbyPlayer")(seat.name, handler)

    def _release(self) -> None:
        """Drops the Forge game. A handler (Python) and the game (Java) reference
        each other through the JVM boundary, which neither collector can see
        through: without this every ended game stays in the heap."""
        if self._game is not None:
            self._final_turn = int(self._game.getPhaseHandler().getTurn())
        for handler in self.handlers:
            handler.session = None
        self._game = None
        self._match = None
        self._players = []

    def _end_game(self) -> None:
        game = self._game
        if game is not None and not game.isGameOver():
            game.setGameOver(jpype.JClass("forge.game.GameEndReason").Draw)

    def _past_turn_limit(self) -> bool:
        game = self._game
        if game is None:
            return False
        if game.isGameOver():
            return True
        if game.getPhaseHandler().getTurn() <= self.turn_limit:
            return False
        self._turn_limit_hit = True
        game.setGameOver(jpype.JClass("forge.game.GameEndReason").Draw)
        return True

    def _record_outcome(self) -> None:
        outcome = self._game.getOutcome() if self._game is not None else None
        if self._orphaned:
            self.end_reason = "orphaned"
        elif self._abort.is_set():
            self.end_reason = "aborted"
        elif self._turn_limit_hit:
            self.end_reason = "turn_limit"
        elif outcome is not None:
            self.end_reason = str(outcome.getWinCondition())
            if not outcome.isDraw():
                name = str(outcome.getWinningLobbyPlayer().getName())
                self.winner = next(i for i, seat in enumerate(self.seats) if seat.name == name)
        self._event("game_over", None, f"Game over: {self.end_reason}, winner seat {self.winner}",
                    {"winner": self.winner, "end_reason": self.end_reason})

    def _finish(self, status: str) -> None:
        self.ended_at = time.monotonic()
        self.status = status

    def _sync_log(self) -> None:
        game = self._game
        if game is None:
            return
        entries = list(game.getGameLog().getLogEntries(None))
        entries.reverse()  # Forge keeps the newest entry first
        for entry in entries[self._log_seen:]:
            text = str(entry.message())
            started = TURN_START.match(text)
            if started:
                self._log_turn = int(started.group(1))
            self._event("log", None, text, {"type": str(entry.type())}, turn=self._log_turn, phase="")
        self._log_seen = len(entries)

    def _event(self, kind: str, seat: int | None, text: str, payload: dict | None = None, *,
               turn: int | None = None, phase: str | None = None) -> None:
        if phase is None:
            game = self._game
            current = game.getPhaseHandler().getPhase() if game is not None else None
            phase = str(current) if current is not None else ""
        with self._lock:
            self._events.append({
                "seq": len(self._events),
                "turn": self.turn if turn is None else turn,
                "phase": phase,
                "seat": seat,
                "kind": kind,
                "text": text,
                "payload": payload or {},
            })
