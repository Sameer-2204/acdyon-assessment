"""
main.py — FastAPI application with health check, data, and control endpoints.

ENDPOINTS:
- GET  /health  — Is the service running? What's the circuit breaker state?
- GET  /jobs    — Return the latest scraped job listings
- POST /scrape  — Manually trigger a scrape cycle (for demo/review purposes)
- GET  /status  — Full pipeline metrics: cycles, failures, source health

BACKGROUND TASK:
The scrape loop runs as a background task via FastAPI's lifespan hook.
It starts when the app starts and runs until the app shuts down.
The POST /scrape endpoint triggers an ADDITIONAL immediate cycle
without affecting the scheduled loop.
"""

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import JSONResponse

from src.logging_config import setup_logging
from src.pipeline import Pipeline
from src.scraper.registry import create_default_registry

# Initialize logging before anything else
setup_logging()
log = structlog.get_logger()

# Module-level references so endpoints can access them
_pipeline: Pipeline | None = None
_registry = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan hook — runs on startup and shutdown.

    On startup: create the registry and pipeline, start the background scrape loop.
    On shutdown: close all HTTP clients cleanly.
    """
    global _pipeline, _registry

    log.info("app_starting")

    # Create the source registry and pipeline
    _registry = create_default_registry()
    _pipeline = Pipeline(registry=_registry)

    # Start the background scrape loop as an asyncio task
    scrape_task = asyncio.create_task(_pipeline.run_loop())

    log.info("app_started", sources=[s.name for s in _registry.get_sources()])

    yield  # App is running — handle requests

    # Shutdown: cancel the background loop and close HTTP clients
    scrape_task.cancel()
    try:
        await scrape_task
    except asyncio.CancelledError:
        pass

    await _registry.close_all()
    log.info("app_shutdown")


app = FastAPI(
    title="Anti-Bot Job Scraper",
    description="Resilient job listing ingestion pipeline — take-home assessment demo",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    """Small landing response for reviewers opening the service URL."""
    return {
        "service": "Anti-Bot Job Scraper",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "jobs": "/jobs",
    }


@app.get("/health")
async def health():
    """
    Health check endpoint.

    Returns service status and circuit breaker states for each source.
    A monitoring system would poll this to detect degradation.
    """
    if _pipeline is None:
        return JSONResponse(
            status_code=503,
            content={"status": "starting", "message": "Pipeline not initialized yet"},
        )

    return {
        "status": "healthy",
        "last_scrape": _pipeline.last_scrape_time,
        "last_source": _pipeline.last_scrape_source,
        "sources": {
            source.name: source.circuit_breaker.get_status()
            for source in _registry.get_sources()
        },
    }


@app.get("/jobs")
async def get_jobs():
    """
    Return the latest scraped job listings.

    Reads from the latest.json file on disk. If no scrape has completed
    yet, returns an empty result set (not a 404 — the endpoint exists,
    there's just no data yet).
    """
    if _pipeline is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Pipeline not initialized yet"},
        )

    return _pipeline.get_latest_listings()


@app.post("/scrape")
async def trigger_scrape():
    """
    Manually trigger an immediate scrape cycle.

    This is for demo/review purposes — lets a reviewer see the pipeline
    work without waiting for the scheduled interval. Does not affect
    the background schedule.
    """
    if _pipeline is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Pipeline not initialized yet"},
        )

    log.info("manual_scrape_triggered")
    result = await _pipeline.run_once()

    if result and result.success:
        return {
            "status": "success",
            "source": result.source,
            "listings_count": len(result.listings),
            "duration_seconds": result.duration_seconds,
        }
    else:
        return JSONResponse(
            status_code=502,
            content={
                "status": "failed",
                "error": result.error_message if result else "All sources failed",
            },
        )


@app.get("/status")
async def get_status():
    """
    Full pipeline status with metrics.

    Shows: total cycles, success/failure counts, per-source circuit
    breaker state, and timing information. This is the dashboard view.
    """
    if _pipeline is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Pipeline not initialized yet"},
        )

    return _pipeline.get_status()
