"""Every game of the process: creation, lookup, abort, expiry, concurrency slots."""

import threading
import time
import uuid
from dataclasses import replace

from .formats import Format
from .queue import DecisionQueue
from .session import GameSession, SeatSpec
from .settings import Settings


def unique_names(names: list[str]) -> list[str]:
    """Seat names identify the winner, so a name used twice gets its seat number."""
    return [f"{name} (seat {i + 1})" if names.count(name) > 1 else name for i, name in enumerate(names)]


class GameRegistry:
    def __init__(self, settings: Settings, queue: DecisionQueue):
        self.settings = settings
        self.queue = queue
        self._slots = threading.BoundedSemaphore(settings.max_concurrent_games)
        self._games: dict[str, GameSession] = {}
        self._lock = threading.Lock()

    def create(self, fmt: Format, seed: int, seats: list[SeatSpec]) -> GameSession:
        self.purge()
        names = unique_names([seat.name for seat in seats])
        seats = [replace(seat, name=name) for seat, name in zip(seats, names)]
        session = GameSession(uuid.uuid4().hex, fmt, seed, seats, self.queue, self.settings.max_turns, self._slots)
        with self._lock:
            self._games[session.id] = session
        session.start()
        return session

    def get(self, game_id: str) -> GameSession | None:
        self.purge()
        with self._lock:
            return self._games.get(game_id)

    def abort(self, game_id: str) -> bool:
        session = self.get(game_id)
        if session is None:
            return False
        session.abort()
        return True

    def purge(self) -> None:
        now = time.monotonic()
        with self._lock:
            for game_id in [g for g, s in self._games.items()
                            if s.ended_at is not None and now - s.ended_at > self.settings.game_ttl]:
                del self._games[game_id]
