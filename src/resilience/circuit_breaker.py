"""
circuit_breaker.py — Three-state circuit breaker for source health tracking.

THE PROBLEM THIS SOLVES:
When a source starts returning errors (403 blocked, 500 server errors, timeouts),
naively retrying every request wastes time and makes us look MORE like a bot
(hammering a failing endpoint). A circuit breaker "trips" after enough failures
and stops sending requests entirely for a cooldown period.

THE THREE STATES:
1. CLOSED (normal) — requests flow through normally. Failures are counted.
2. OPEN (tripped) — the source is considered down. All requests are immediately
   rejected without being sent. After a cooldown, transitions to HALF_OPEN.
3. HALF_OPEN (probing) — one single request is allowed through as a "probe".
   If it succeeds → back to CLOSED. If it fails → back to OPEN with a longer cooldown.

WHY THE COOLDOWN INCREASES:
If the source is genuinely blocking us, a fixed 60-second cooldown means we
probe every minute — still annoying. Exponentially increasing the cooldown
(60s → 120s → 240s → ...) means we gradually back off, which is both polite
and less likely to trigger further blocking.

THIS IS WHAT TRIGGERS THE FALLBACK:
When the RemoteOK circuit breaker is OPEN, the pipeline sees it and skips
directly to the WWR RSS fallback. The circuit breaker doesn't know about
the fallback — that logic lives in the pipeline. Separation of concerns.
"""

import time
from enum import Enum

import structlog

from src import config

log = structlog.get_logger()


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Source is down, reject requests
    HALF_OPEN = "half_open" # Probing with a single request


class CircuitBreaker:
    """
    Circuit breaker for a single source.

    Usage:
        cb = CircuitBreaker(name="remoteok")

        if not cb.allow_request():
            # Circuit is open, skip this source
            return

        try:
            result = await fetch_data()
            cb.record_success()
        except Exception as e:
            cb.record_failure()
            raise
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = config.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        cooldown_seconds: int = config.CIRCUIT_BREAKER_COOLDOWN_SECONDS,
        cooldown_multiplier: float = config.CIRCUIT_BREAKER_COOLDOWN_MULTIPLIER,
        max_cooldown: int = config.CIRCUIT_BREAKER_MAX_COOLDOWN,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.base_cooldown = cooldown_seconds
        self.cooldown_multiplier = cooldown_multiplier
        self.max_cooldown = max_cooldown

        # Internal state
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._current_cooldown = float(cooldown_seconds)
        self._half_open_probe_in_flight = False

        # Metrics for the /status endpoint
        self.total_successes = 0
        self.total_failures = 0
        self.total_trips = 0  # How many times the circuit has opened

    @property
    def state(self) -> CircuitState:
        """Current state, accounting for cooldown expiry."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._current_cooldown:
                # Cooldown expired — transition to HALF_OPEN for probing
                log.info(
                    "circuit_breaker_half_open",
                    source=self.name,
                    cooldown_elapsed=round(elapsed, 1),
                )
                self._state = CircuitState.HALF_OPEN
        return self._state

    def allow_request(self) -> bool:
        """
        Should the caller send a request to this source?
        Returns True if the circuit is CLOSED or HALF_OPEN (probe).
        Returns False if the circuit is OPEN.
        """
        current = self.state  # This may transition OPEN → HALF_OPEN
        if current == CircuitState.OPEN:
            log.debug(
                "circuit_breaker_rejected",
                source=self.name,
                retry_in=round(
                    self._current_cooldown
                    - (time.monotonic() - self._last_failure_time),
                    1,
                ),
            )
            return False
        if current == CircuitState.HALF_OPEN:
            if self._half_open_probe_in_flight:
                log.debug("circuit_breaker_probe_rejected", source=self.name)
                return False
            self._half_open_probe_in_flight = True
        return True

    def record_success(self) -> None:
        """Record a successful request. Resets the circuit to CLOSED."""
        if self._state == CircuitState.HALF_OPEN:
            log.info(
                "circuit_breaker_recovered",
                source=self.name,
                was_half_open=True,
            )
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_probe_in_flight = False
        # Reset cooldown to base on recovery
        self._current_cooldown = float(self.base_cooldown)
        self.total_successes += 1

    def record_failure(self) -> None:
        """
        Record a failed request. May trip the circuit to OPEN.
        """
        self._failure_count += 1
        self.total_failures += 1
        self._last_failure_time = time.monotonic()
        self._half_open_probe_in_flight = False

        if self._state == CircuitState.HALF_OPEN:
            # Probe failed — go back to OPEN with a longer cooldown
            self._state = CircuitState.OPEN
            self._current_cooldown = min(
                self._current_cooldown * self.cooldown_multiplier,
                self.max_cooldown,
            )
            self.total_trips += 1
            log.warning(
                "circuit_breaker_probe_failed",
                source=self.name,
                next_cooldown=self._current_cooldown,
            )
        elif self._failure_count >= self.failure_threshold:
            # Enough consecutive failures — trip the circuit
            self._state = CircuitState.OPEN
            self.total_trips += 1
            log.warning(
                "circuit_breaker_tripped",
                source=self.name,
                failures=self._failure_count,
                cooldown=self._current_cooldown,
            )

    def get_status(self) -> dict:
        """Return current status for the /status API endpoint."""
        return {
            "source": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "current_cooldown": self._current_cooldown,
            "half_open_probe_in_flight": self._half_open_probe_in_flight,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "total_trips": self.total_trips,
        }
