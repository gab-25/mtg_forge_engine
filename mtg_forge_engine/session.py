"""One game: a Forge match on its own thread, its event log and its outcome.

Every seat is Forge's AI, so the game runs inside ``Match.startGame`` without ever
calling back into Python. The game thread is the only one that touches the Forge
Game; ending it early (abort, turn limit) is left to Java event subscribers that
run on that thread (``forge.bridge.Abort``, ``forge.bridge.TurnLimit``).
"""

import logging
import re
import threading
import time
from dataclasses import dataclass

import jpype

from .formats import Format

logger = logging.getLogger(__name__)

TURN_START = re.compile(r"^Turn (\d+) ")


@dataclass(frozen=True)
class SeatSpec:
    name: str
    deck: object  # forge.deck.Deck


class GameSession:
    def __init__(self, game_id: str, fmt: Format, seed: int, seats: list[SeatSpec], max_turns: int,
                 slots: threading.Semaphore):
        self.id = game_id
        self.format = fmt
        self.seed = seed
        self.seats = seats
        self.max_turns = max_turns
        # MAX_TURNS counts rounds in multiplayer: each player gets as many turns as in a duel.
        self.turn_limit = max_turns * len(seats) if len(seats) > 2 else max_turns
        self.status = "queued"
        self.winner: int | None = None
        self.end_reason: str | None = None
        # [{"seat", "turn", "reason"}] of the players who lost, first eliminated first.
        self.eliminations: list[dict] = []
        self.error: str | None = None
        self.ended_at: float | None = None
        self._slots = slots
        self._events: list[dict] = []
        self._lock = threading.Lock()
        self._abort = threading.Event()
        self._game = None
        self._match = None
        self._players: list = []
        self._tracker = None
        self._turn_cap = None
        self._abort_switch = None
        self._final_turn = 0
        self._log_seen = 0
        # The turn of the last Forge log entry read: the log is read in batches.
        self._log_turn = 0
        self._thread = threading.Thread(target=self._run, name=f"game-{game_id}", daemon=True)

    # --- lifecycle --------------------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def abort(self) -> None:
        """Called from a request thread. Forge's Game is not thread-safe, so this only
        flips a switch: the game thread ends the game at its next game event. A game
        still queued never starts."""
        self._abort.set()
        switch = self._abort_switch
        if switch is not None:
            switch.request()

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
            "eliminations": self.eliminations,
            "error": self.error,
        }

    def events_since(self, since: int) -> list[dict]:
        with self._lock:
            return list(self._events[max(since, 0):])

    def seat_of(self, player) -> int:
        for index, candidate in enumerate(self._players):
            if candidate.equals(player):
                return index
        raise ValueError(f"{player} is not in game {self.id}")

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
                # abort() sets the flag before it reads the switch, and the switch exists
                # by now: an abort that missed the switch is caught here.
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
        ai_player = J("forge.player.GamePlayerUtil")
        for seat in self.seats:
            rp = registered_player.forCommander(seat.deck) if self.format.commander else registered_player(seat.deck)
            rp.setStartingLife(self.format.starting_life)
            rp.setPlayer(ai_player.createAiPlayer(seat.name, 0, 0, None, "Default"))
            registered.add(rp)
        self._match = J("forge.game.Match")(rules, registered, f"mtg-forge-engine {self.id}")
        game = self._match.createGame()
        self._tracker = J("forge.bridge.EliminationTracker")(game)
        self._turn_cap = J("forge.bridge.TurnLimit")(game, self.turn_limit)
        self._abort_switch = J("forge.bridge.Abort")(game)
        self._players = list(game.getRegisteredPlayers())
        return game

    def _release(self) -> None:
        """Drops the Forge game. The session stays in the registry for GAME_TTL after
        the game ends: without this the JVM keeps every ended game in its heap until
        then."""
        if self._game is not None:
            self._final_turn = int(self._game.getPhaseHandler().getTurn())
        self._game = None
        self._match = None
        self._tracker = None
        self._turn_cap = None
        self._abort_switch = None
        self._players = []

    def _eliminations(self) -> list[dict]:
        tracker = self._tracker
        if tracker is None:
            return []
        tracker.record()  # the last loss may have come after the last event
        return [{"seat": self.seat_of(player), "turn": int(tracker.getTurn(player)),
                 "reason": str(player.getOutcome().lossState)}
                for player in tracker.getOrder()]

    def _record_outcome(self) -> None:
        self.eliminations = self._eliminations()
        outcome = self._game.getOutcome() if self._game is not None else None
        if self._abort.is_set():
            self.end_reason = "aborted"
        elif self._turn_cap is not None and self._turn_cap.isHit():
            self.end_reason = "turn_limit"
        elif outcome is not None:
            self.end_reason = str(outcome.getWinCondition())
            if not outcome.isDraw():
                name = str(outcome.getWinningLobbyPlayer().getName())
                self.winner = next(i for i, seat in enumerate(self.seats) if seat.name == name)
        self._event("game_over", None, f"Game over: {self.end_reason}, winner seat {self.winner}",
                    {"winner": self.winner, "end_reason": self.end_reason, "eliminations": self.eliminations})

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
