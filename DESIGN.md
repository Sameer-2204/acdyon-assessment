# Design

## Detection surface

Automated clients often stand out through a default Python user agent, missing
browser-style headers, bursty parallel requests, fixed request intervals, and
repeated requests after an error. This service reduces those signals by using a
small pool of current browser user-agent strings, standard `Accept` and
language headers, a shared keep-alive client, sequential source access, and
random jitter both before a request and between scrape cycles.

The intent is to be identifiable as a well-behaved consumer of public feeds,
not to evade a source's access controls. It does not rotate proxies, spoof a
browser fingerprint, manage cookies, or use a headless browser. Those measures
would add complexity and could undermine the stated policy of backing off when
a source does not want automated traffic.

## Ingestion strategy

RemoteOK's public JSON endpoint is the preferred source because it provides
richer records. We Work Remotely's RSS feed is the fallback and demonstrates a
second ingestion format with a separate parser.

Both parsers emit `JobListing`, a Pydantic-validated common schema. Individual
invalid entries are logged and dropped; an invalid document fails the attempt.
This keeps malformed upstream data out of the stored results while preserving
the raw entry in memory for debugging.

The pipeline tries sources in priority order and stops after the first source
that returns listings. This minimizes requests. If RemoteOK fails or is
temporarily unavailable, WWR is tried in the same cycle. Empty but valid
responses do not trip the circuit breaker, but allow the fallback to be used.

## Resilience

Each source has independent resilience state:

- A token bucket controls request pace; the wait includes uniformly random
  jitter.
- Tenacity retries only transient HTTP/network failures with exponential
  backoff and jitter. A 403 and other non-429 client errors fail fast.
- A circuit breaker opens after consecutive failures. It waits for a cooldown,
  then permits one half-open probe. A successful probe resets the breaker; a
  failed probe increases the next cooldown up to a cap.

The API exposes breaker state and pipeline totals at `/health` and `/status`.
Structlog records request timing, source selection, parser errors, breaker
transitions, and result persistence. Stored data is timestamped JSON plus a
`latest.json` copy for quick API reads.

Markup or schema drift is caught at the parser/model boundary. Missing or bad
listing fields are logged per entry, while an unparseable JSON/XML payload is
reported as a failed scrape and contributes to the breaker state. Field names
are centralized in `src/config.py` to make simple upstream changes cheap to
repair.

## Operating boundary

The service is limited to public endpoints that need no login. It uses modest,
sequential traffic and obeys errors: a 403 is not retried and repeated failures
open the breaker before the fallback is used. If a provider removes public
access, publishes a restriction that prohibits this use, or requires bypassing
technical controls, ingestion from that provider should stop. A production
service should also use a durable store and alerting; Render's free filesystem
is intentionally treated as ephemeral here.
