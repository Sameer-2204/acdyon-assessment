# Engineering Decisions

## Source selection

RemoteOK is the primary source because its JSON API supplies structured job
metadata. We Work Remotely RSS is the fallback because it is a distinct,
simple, public feed. Different formats make the fallback meaningful: a problem
with RemoteOK's API or its anti-abuse layer does not prevent a WWR RSS scrape.

## Python, FastAPI, and async HTTP

Python 3.12 provides mature libraries for HTTP, data validation, retries, and
RSS parsing. FastAPI makes the review surface small: health, data, manual
trigger, and metrics endpoints are all directly inspectable. `httpx` keeps the
network path asynchronous and reuses connections within each source client.

## Validation as the source contract

Every parser constructs the same Pydantic `JobListing`. This is preferred over
returning raw source-shaped dictionaries because downstream consumers receive
a stable format and upstream drift becomes visible at the boundary. Bad
individual entries are skipped with structured logging rather than causing an
otherwise valid feed to be discarded.

## Resilience policy

The service combines rate limiting, jitter, retry, and circuit breaking because
they address different failures. The limiter prevents excess request rate;
jitter avoids machine-regular timing; retries help with temporary faults; and
the breaker prevents continued traffic to a failing source. A 403 is not
retried because it is a strong signal to stop, while 429 and server failures
are treated as potentially temporary.

## Persistence

Results are saved as JSON files. This keeps the demo easy to run and audit,
but Render free instances do not provide durable application storage. For a
production service, the persistence seam in `Pipeline._save_results` should
write to a managed relational database or object store instead.

## Human review note

Before submitting this work, the project owner should review these trade-offs,
the source terms of use, and any statement about development assistance so the
submission accurately reflects their own process and authorization.
