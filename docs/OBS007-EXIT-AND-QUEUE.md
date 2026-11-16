# OBS-007 exit latency and export-queue fixes (16 November 2026)

QA measured two Langfuse SDK limits. Turns are never slowed, but process exit and bursts were affected.

## 1. Process exit stalled while Langfuse was unreachable

Measured against a loopback endpoint that accepts connections and never replies:

| | Before | After |
|---|---|---|
| `on_session_finalize(reason="shutdown")` | 5.2 s | 2.0 s |
| Process exit after finalize | 7.0 s | 2.6 s |
| Process exit with a turn still open (atexit path) | 5.7 s | 2.6 s |

Changes:
- **Exit-time export work is bounded.** Flush and shutdown run in a daemon thread that exit waits on for at most `HERMES_LANGFUSE_FLUSH_TIMEOUT` seconds (default **2**). At process exit the plugin shuts each settled client down itself (flush, then stop) within that bound, so the SDK's own atexit hook has nothing left to wait for. Several multiplexed clients shut down in parallel under ONE shared bound, not one bound each.
- **Export request timeout defaults to 2 s.** OpenTelemetry's exit hook joins the in-flight export, so exit can never be quicker than that request's timeout. The plugin now passes `timeout=2` (configurable with `HERMES_LANGFUSE_TIMEOUT`, or `LANGFUSE_TIMEOUT`; both are read through the profile scope, so a multiplexed profile can set them in its own `.env`). Raise it for a distant endpoint; a self-hosted one answers in milliseconds.
- With a healthy endpoint, spans still export and exit stays quick (tested).

## 2. Spans beyond the 2,048-span queue were dropped silently

- **Configurable (per profile too):** `HERMES_LANGFUSE_MAX_QUEUE_SIZE` sets the SDK batch queue size. The SDK only reads `OTEL_BSP_MAX_QUEUE_SIZE` at construction, so the plugin sets that variable only for the client construction call. It never overrides an operator's own value and does not leak to the rest of the process. Default unchanged: 2048. Larger queues hold more memory during an outage.
- **Visible:** when the queue overflows, the plugin logs `Langfuse plugin: the span export queue is full and spans are being dropped …`, at most once a minute. No exact count is given, because OpenTelemetry de-duplicates its own drop warnings.

Not changed: spans created while Langfuse is unreachable are still dropped rather than buffered to disk. That is SDK design, and is accepted under the D04 weekly-rotation decision.

Tests: `tests/test_obs007_exit_and_queue.py` adds 19 cases, including real-SDK subprocess timing against unreachable and healthy loopback endpoints and an end-to-end OpenTelemetry queue overflow. The strict source suite goes from 218 to 237.
