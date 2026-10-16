"""The Python side of the Java shim: Forge asks, the seat's client answers.

The JPype class can only be defined once the JVM runs, hence the cached factory.
A Python error never reaches Forge: it is logged and the AI decides instead.
"""

import functools
import logging

import jpype
from jpype import JImplements, JOverride

from . import choices
from .choices import ForgeAi
from .labels import ability_label

logger = logging.getLogger(__name__)


def _boolean(value):
    return None if value is None else jpype.JClass("java.lang.Boolean").valueOf(bool(value))


def _list(values):
    if values is None:
        return None
    result = jpype.JClass("java.util.ArrayList")()
    for value in values:
        result.add(value)
    return result


@functools.cache
def _handler_class():
    @JImplements("forge.bridge.DecisionHandler")
    class Handler:
        def __init__(self, session, seat: int):
            self.session = session
            self.seat = seat

        def _guard(self, kind: str, decide):
            try:
                return decide()
            except Exception:
                logger.exception("game %s seat %s: %s failed", self.session.id, self.seat, kind)
                self.session.fallback(self.seat, kind, "error")
                return None

        @JOverride
        def mulliganKeepHand(self, player, cardsToReturn, ai):
            return self._guard("mulligan", lambda: _boolean(
                choices.mulligan(self.session, self.seat, player, int(cardsToReturn), ForgeAi(ai))))

        @JOverride
        def tuckCardsViaMulligan(self, player, hand, cardsToReturn, ai):
            return self._guard("bottom", lambda: _list(
                choices.bottom(self.session, self.seat, player, hand, int(cardsToReturn), ForgeAi(ai))))

        @JOverride
        def chooseSpellAbilityToPlay(self, player, ai):
            return self._guard("priority", lambda: _list(choices.priority(self.session, self.seat, player, ForgeAi(ai))))

        @JOverride
        def chooseTargetsFor(self, player, sa, ai):
            return self._guard("target", lambda: _boolean(
                choices.targets(self.session, self.seat, player, sa, ForgeAi(ai))))

        @JOverride
        def declareAttackers(self, player, combat, ai):
            return self._guard("attack", lambda: _boolean(
                choices.attackers(self.session, self.seat, player, combat, ForgeAi(ai))))

        @JOverride
        def declareBlockers(self, player, combat, ai):
            return self._guard("block", lambda: _boolean(
                choices.blockers(self.session, self.seat, player, combat, ForgeAi(ai))))

        @JOverride
        def chooseEntities(self, player, sa, title, options, min, max, ai):
            return self._guard("choose_cards", lambda: _list(choices.entities(
                self.session, self.seat, player, title, options, int(min), int(max), ForgeAi(ai))))

        @JOverride
        def confirm(self, player, message, ai):
            return self._guard("confirm", lambda: _boolean(
                choices.confirm(self.session, self.seat, str(message) if message is not None else "", ForgeAi(ai))))

        @JOverride
        def chooseModes(self, player, sa, possible, min, num, allowRepeat, ai):
            return self._guard("mode", lambda: _list(choices.modes(
                self.session, self.seat, sa, possible, int(min), int(num), bool(allowRepeat), ForgeAi(ai))))

        @JOverride
        def onPlayFailed(self, player, sa, reason):
            try:
                self.session.play_failed(self.seat, ability_label(sa), str(reason))
            except Exception:
                logger.exception("game %s seat %s: play_failed failed", self.session.id, self.seat)

        @JOverride
        def onAiDecision(self, player, method):
            self.session.on_ai_decision(self.seat, str(method))

    return Handler


def make_handler(session, seat: int):
    return _handler_class()(session, seat)
