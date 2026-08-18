"""
logging_config.py — Structured logging setup using structlog.

Why structlog over stdlib logging:
- Outputs JSON by default → machine-parseable, grep-able, ready for log aggregation
- Context binding → attach source name, request ID, etc. once, they appear on every log line
- No silent failures — if a scrape fails, the structured log includes the source,
  the HTTP status, the retry count, and the error, all as queryable fields

In development: pretty-prints to console for readability.
In production: outputs JSON lines.
"""

import logging
import os
import sys

import structlog


def setup_logging() -> None:
    """Configure structlog for the application."""

    # Use pretty console output in dev, JSON in production
    is_production = os.getenv("ENVIRONMENT", "development") == "production"

    if is_production:
        # JSON lines — each log entry is a single JSON object on one line
        renderer = structlog.processors.JSONRenderer()
    else:
        # Colored, human-readable console output for local development
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            # Add log level name (info, warning, error, etc.)
            structlog.stdlib.add_log_level,
            # Add ISO timestamp
            structlog.processors.TimeStamper(fmt="iso"),
            # If an exception is being logged, format the traceback
            structlog.processors.format_exc_info,
            # Add caller info (module, function, line number) for debugging
            structlog.processors.CallsiteParameterAdder(
                [
                    structlog.processors.CallsiteParameter.MODULE,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
            # Final renderer (JSON or console)
            renderer,
        ],
        # Use a dict for the internal context — simple and fast
        context_class=dict,
        # Use structlog's own logger (not stdlib wrapper)
        logger_factory=structlog.PrintLoggerFactory(),
        # Cache the processor pipeline for performance
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging to go through structlog,
    # so third-party libraries (httpx, uvicorn) don't bypass our setup
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )
