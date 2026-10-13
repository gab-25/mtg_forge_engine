"""Pending decisions of every game, handed out to client workers. Pure Python.

A game thread submits a decision and blocks in ``wait``. A worker leases it
(``lease``) and answers it (``answer``). Once leased, a decision that is not
answered within ``timeout`` seconds is taken by Forge's AI. An unleased decision
waits for a worker indefinitely.
"""

import threading
import time
from dataclasses import dataclass, field


class UnknownDecision(Exception):
    """The decision does not exist, was already answered, or expired."""


class ChoiceOutOfRange(Exception):
    """The answer names an option the decision does not have."""


@dataclass(frozen=True)
class Answer:
    # None: Forge's AI decides.
    choice: int | None
    # "client", "delegate", "timeout" or "withdrawn".
    reason: str = "client"
    meta: dict = field(default_factory=dict)


@dataclass
class Decision:
    id: str
    game_id: str
    seat: int
    kind: str
    prompt: str
    view: dict
    options: list[dict]
    leased_at: float | None = None
    answer: Answer | None = None

    def as_dict(self) -> dict:
        return {
            "decision_id": self.id,
            "game_id": self.game_id,
            "seat": self.seat,
            "kind": self.kind,
            "prompt": self.prompt,
            "view": self.view,
            "options": self.options,
        }


class DecisionQueue:
    def __init__(self, timeout: float):
        self.timeout = timeout
        self._cond = threading.Condition()
        # Insertion order is age: leases hand out the oldest first.
        self._open: dict[str, Decision] = {}
        # Games whose decisions were withdrawn. A game thread may submit after
        # the withdrawal (it checked for an abort just before it landed).
        self._withdrawn: set[str] = set()

    def submit(self, decision: Decision) -> None:
        with self._cond:
            if decision.game_id in self._withdrawn:
                decision.answer = Answer(None, "withdrawn")
                return
            self._open[decision.id] = decision
            self._cond.notify_all()

    def lease(self, wait: float, game_id: str | None = None) -> Decision | None:
        deadline = time.monotonic() + wait
        with self._cond:
            while True:
                for decision in self._open.values():
                    if decision.leased_at is None and game_id in (None, decision.game_id):
                        decision.leased_at = time.monotonic()
                        self._cond.notify_all()
                        return decision
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)

    def answer(self, decision_id: str, choice: int | None = None, *, delegate: bool = False,
               meta: dict | None = None) -> None:
        with self._cond:
            decision = self._open.get(decision_id)
            if decision is None:
                raise UnknownDecision(decision_id)
            if delegate:
                answer = Answer(None, "delegate", meta or {})
            elif choice is None or not 0 <= choice < len(decision.options):
                raise ChoiceOutOfRange(f"choice {choice} not in 0..{len(decision.options) - 1}")
            else:
                answer = Answer(choice, "client", meta or {})
            self._close(decision, answer)

    def wait(self, decision: Decision) -> Answer:
        with self._cond:
            while decision.answer is None:
                if decision.leased_at is None:
                    self._cond.wait()
                    continue
                remaining = decision.leased_at + self.timeout - time.monotonic()
                if remaining <= 0:
                    self._close(decision, Answer(None, "timeout"))
                    break
                self._cond.wait(remaining)
            return decision.answer

    def withdraw_game(self, game_id: str) -> None:
        with self._cond:
            self._withdrawn.add(game_id)
            for decision in [d for d in self._open.values() if d.game_id == game_id]:
                self._close(decision, Answer(None, "withdrawn"))

    def _close(self, decision: Decision, answer: Answer) -> None:
        decision.answer = answer
        self._open.pop(decision.id, None)
        self._cond.notify_all()
