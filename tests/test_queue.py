import threading
import time

import pytest

from forge_bridge.queue import ChoiceOutOfRange, Decision, DecisionQueue, UnknownDecision


def decision(id_, game="g1", options=3):
    return Decision(id=id_, game_id=game, seat=0, kind="priority", prompt="p", view={},
                    options=[{"index": i, "label": str(i), "facts": []} for i in range(options)])


def wait_in_thread(queue, d):
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("answer", queue.wait(d)), daemon=True)
    thread.start()
    return thread, result


def test_lease_is_fifo_and_exclusive():
    q = DecisionQueue(timeout=5)
    q.submit(decision("a"))
    q.submit(decision("b"))
    assert q.lease(0).id == "a"
    assert q.lease(0).id == "b"
    assert q.lease(0) is None


def test_lease_filters_by_game():
    q = DecisionQueue(timeout=5)
    q.submit(decision("a", game="g1"))
    q.submit(decision("b", game="g2"))
    assert q.lease(0, "g2").id == "b"


def test_lease_waits_for_a_submission():
    q = DecisionQueue(timeout=5)
    threading.Timer(0.1, lambda: q.submit(decision("a"))).start()
    assert q.lease(2).id == "a"


def test_answer_wakes_the_game_thread():
    q = DecisionQueue(timeout=5)
    d = decision("a")
    q.submit(d)
    thread, result = wait_in_thread(q, d)
    q.lease(0)
    q.answer("a", 2, meta={"confidence": 0.5})
    thread.join(2)
    assert result["answer"].choice == 2
    assert result["answer"].reason == "client"
    assert result["answer"].meta == {"confidence": 0.5}


def test_delegate():
    q = DecisionQueue(timeout=5)
    d = decision("a")
    q.submit(d)
    thread, result = wait_in_thread(q, d)
    q.answer("a", delegate=True)
    thread.join(2)
    assert result["answer"].choice is None and result["answer"].reason == "delegate"


def test_second_answer_and_unknown_id_are_rejected():
    q = DecisionQueue(timeout=5)
    d = decision("a")
    q.submit(d)
    thread, _ = wait_in_thread(q, d)
    q.answer("a", 0)
    thread.join(2)
    with pytest.raises(UnknownDecision):
        q.answer("a", 0)
    with pytest.raises(UnknownDecision):
        q.answer("nope", 0)


def test_choice_out_of_range():
    q = DecisionQueue(timeout=5)
    q.submit(decision("a", options=2))
    with pytest.raises(ChoiceOutOfRange):
        q.answer("a", 2)
    with pytest.raises(ChoiceOutOfRange):
        q.answer("a", -1)


def test_leased_decision_times_out_and_late_answer_is_rejected():
    q = DecisionQueue(timeout=0.2)
    d = decision("a")
    q.submit(d)
    thread, result = wait_in_thread(q, d)
    q.lease(0)
    thread.join(2)
    assert result["answer"].choice is None and result["answer"].reason == "timeout"
    with pytest.raises(UnknownDecision):
        q.answer("a", 0)


def test_unleased_decision_does_not_time_out():
    q = DecisionQueue(timeout=0.1)
    d = decision("a")
    q.submit(d)
    thread, result = wait_in_thread(q, d)
    time.sleep(0.4)
    assert "answer" not in result
    q.answer("a", 1)
    thread.join(2)
    assert result["answer"].choice == 1


def test_withdraw_game():
    q = DecisionQueue(timeout=5)
    d = decision("a", game="g1")
    other = decision("b", game="g2")
    q.submit(d)
    q.submit(other)
    thread, result = wait_in_thread(q, d)
    q.withdraw_game("g1")
    thread.join(2)
    assert result["answer"].reason == "withdrawn"
    assert q.lease(0).id == "b"


def test_decision_submitted_after_withdrawal_is_withdrawn():
    """An abort can land between a game thread's last check and its submit."""
    q = DecisionQueue(timeout=5)
    q.withdraw_game("g1")
    d = decision("a", game="g1")
    q.submit(d)
    thread, result = wait_in_thread(q, d)
    thread.join(2)
    assert result["answer"].reason == "withdrawn"
    assert q.lease(0) is None


def test_unleased_decision_is_orphaned_after_the_orphan_timeout():
    q = DecisionQueue(timeout=5, orphan_timeout=0.2)
    d = decision("a")
    q.submit(d)
    thread, result = wait_in_thread(q, d)
    thread.join(2)
    assert result["answer"].choice is None and result["answer"].reason == "orphaned"
    with pytest.raises(UnknownDecision):
        q.answer("a", 0)
