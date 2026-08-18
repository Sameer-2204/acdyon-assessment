import time

from src.resilience.circuit_breaker import CircuitBreaker, CircuitState


def test_circuit_opens_after_failure_threshold():
    breaker = CircuitBreaker(name="test", failure_threshold=2, cooldown_seconds=60)

    breaker.record_failure()
    assert breaker.state is CircuitState.CLOSED

    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    assert not breaker.allow_request()
    assert breaker.total_trips == 1


def test_circuit_allows_only_one_half_open_probe_and_recovers():
    breaker = CircuitBreaker(name="test", failure_threshold=1, cooldown_seconds=0)
    breaker.record_failure()

    assert breaker.state is CircuitState.HALF_OPEN
    assert breaker.allow_request()
    assert not breaker.allow_request()

    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED
    assert breaker.allow_request()


def test_failed_half_open_probe_increases_cooldown():
    breaker = CircuitBreaker(
        name="test",
        failure_threshold=1,
        cooldown_seconds=1,
        cooldown_multiplier=2,
        max_cooldown=3,
    )
    breaker.record_failure()
    breaker._last_failure_time = time.monotonic() - 2

    assert breaker.allow_request()
    breaker.record_failure()

    assert breaker.state is CircuitState.OPEN
    assert breaker.get_status()["current_cooldown"] == 2
