# Anti-Bot Job Scraper

A small FastAPI service that ingests remote job listings while behaving like a
polite client. It tries the RemoteOK JSON API first and falls back to the We
Work Remotely RSS feed when the primary source is unhealthy.

## What it demonstrates

- A normalized, validated job-listing contract
- Rate limiting with timing jitter and realistic request headers
- Retry of transient failures only (429, 5xx, connection errors, and timeouts)
- Per-source circuit breakers with a single half-open recovery probe
- Ordered failover from RemoteOK to WWR
- Structured logs, API health/status endpoints, and ephemeral JSON persistence

## Run locally

Requires Python 3.12 or later.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn src.main:app --reload
```

The background worker starts immediately. For an on-demand cycle, send:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/scrape
```

Available endpoints:

| Endpoint | Description |
| --- | --- |
| `GET /health` | Service health and each circuit-breaker state |
| `GET /jobs` | Latest persisted normalized listings |
| `POST /scrape` | Run one scrape cycle immediately |
| `GET /status` | Cycle totals, fallback count, and source metrics |

## Test

```powershell
pytest tests/ -v
```

The tests make no live network calls.

## Configuration

All operational settings can be supplied as environment variables. The main
ones are `SCRAPE_INTERVAL` (default `300` seconds), `SCRAPE_JITTER` (default
`60`), `RATE_LIMIT_MAX_TOKENS`, `RATE_LIMIT_REFILL_SECONDS`,
`CIRCUIT_BREAKER_FAILURE_THRESHOLD`, and `HTTP_TIMEOUT_SECONDS`. See
`src/config.py` for the full list and defaults.

## Deploy to Render

1. Push this directory to a GitHub repository.
2. Create a Render web service from that repository.
3. Render reads `render.yaml`, installs dependencies, and starts Uvicorn.

The `data/` directory is deliberately ephemeral for this demo. Replace the
file storage in `Pipeline._save_results` with a managed database for a
production deployment.

See [DESIGN.md](DESIGN.md) for operational boundaries and [DECISIONS.md](DECISIONS.md)
for the engineering trade-offs.
