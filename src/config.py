"""
config.py — All tunables in one place.

Every magic number in the system lives here. When you need to change how
aggressive the rate limiter is, how many failures trip the circuit breaker,
or what headers we send, you change ONE file — not grep through scraper code.

Values can be overridden via environment variables for deployment flexibility.
"""

import os


# ---------------------------------------------------------------------------
# Scrape schedule
# ---------------------------------------------------------------------------
# How often the background loop runs (seconds). Jitter is added on top.
SCRAPE_INTERVAL_SECONDS = int(os.getenv("SCRAPE_INTERVAL", "300"))
# Max random jitter added to the interval (seconds)
SCRAPE_INTERVAL_JITTER = int(os.getenv("SCRAPE_JITTER", "60"))

# ---------------------------------------------------------------------------
# Rate limiter (token-bucket)
# ---------------------------------------------------------------------------
# Max requests allowed per window
RATE_LIMIT_MAX_TOKENS = int(os.getenv("RATE_LIMIT_MAX_TOKENS", "5"))
# Token refill interval (seconds) — one token added every N seconds
RATE_LIMIT_REFILL_SECONDS = float(os.getenv("RATE_LIMIT_REFILL_SECONDS", "2.0"))
# Random jitter range added to each request delay (seconds)
RATE_LIMIT_JITTER_MAX = float(os.getenv("RATE_LIMIT_JITTER_MAX", "1.5"))

# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------
# Consecutive failures before the circuit opens
CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(
    os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "3")
)
# How long to stay OPEN before probing (seconds)
CIRCUIT_BREAKER_COOLDOWN_SECONDS = int(
    os.getenv("CIRCUIT_BREAKER_COOLDOWN_SECONDS", "60")
)
# Multiplier for cooldown on repeated failures (exponential backoff on recovery)
CIRCUIT_BREAKER_COOLDOWN_MULTIPLIER = float(
    os.getenv("CIRCUIT_BREAKER_COOLDOWN_MULTIPLIER", "2.0")
)
# Max cooldown cap (seconds) — don't wait longer than this
CIRCUIT_BREAKER_MAX_COOLDOWN = int(
    os.getenv("CIRCUIT_BREAKER_MAX_COOLDOWN", "600")
)

# ---------------------------------------------------------------------------
# Retry (exponential backoff via tenacity)
# ---------------------------------------------------------------------------
RETRY_MAX_ATTEMPTS = int(os.getenv("RETRY_MAX_ATTEMPTS", "3"))
RETRY_BASE_WAIT_SECONDS = float(os.getenv("RETRY_BASE_WAIT_SECONDS", "1.0"))
RETRY_MAX_WAIT_SECONDS = float(os.getenv("RETRY_MAX_WAIT_SECONDS", "30.0"))

# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "15.0"))

# A pool of realistic User-Agent strings. We rotate through these to avoid
# sending the same UA on every request (a trivial bot fingerprint).
# These are real Chrome UAs from recent stable releases.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
]

# Realistic headers that a real browser would send. Missing these is one of
# the easiest bot fingerprints — most scrapers send *only* a User-Agent.
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # Only advertise codecs httpx can decode with the pinned dependencies.
    # Advertising Brotli without installing a Brotli decoder can make an
    # otherwise healthy upstream response fail during decompression.
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}

# ---------------------------------------------------------------------------
# Source-specific parsing config
# ---------------------------------------------------------------------------
# RemoteOK JSON field mappings — if they rename a field, change it here.
REMOTEOK_API_URL = "https://remoteok.com/api"
REMOTEOK_FIELD_MAP = {
    "id": "id",
    "title": "position",
    "company": "company",
    "url": "url",
    "location": "location",
    "tags": "tags",
    "date": "date",
}

# We Work Remotely RSS
WWR_RSS_URL = "https://weworkremotely.com/categories/remote-jobs.rss"
# RSS fields are accessed via feedparser's normalized entry attributes.
# These are the feedparser attribute names we expect.
WWR_FIELD_MAP = {
    "title": "title",
    "company": "author",  # WWR puts company name in the <author> tag
    "url": "link",
    "summary": "summary",
}

# ---------------------------------------------------------------------------
# Data storage
# ---------------------------------------------------------------------------
DATA_DIR = os.getenv("DATA_DIR", "data")
