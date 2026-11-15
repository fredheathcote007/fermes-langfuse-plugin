# OBS-007 trace shape fixes (15 November 2026)

Findings from real Qwen turns on the Project Coordinator QA stacks, with the fix for each.

| Finding | Change |
|---|---|
| A delegated subagent's own turn (its LLM calls and tools) exported as a **separate trace**, linked to the parent only by `child_session_id` metadata. | `subagent_start` records the parent trace and its `Subagent: <role>` observation for that child session, scoped to the profile. The child's first hook then opens a `Subagent turn` observation **as a child of that span** (via the span's own `start_observation`, so the SDK does not mark it `as_root`). Trace-level session, name and tags stay the parent's, and the nested turn never sets trace-level input/output. The link is released at `subagent_stop`. If the parent observation lacks real SDK ids, the child keeps its own trace as before. |
| Every root `Hermes turn` references a parent span id that is never exported. | **No change: this is SDK design.** For a `trace_context` start, Langfuse SDK v4 creates a random placeholder parent and sets `langfuse.internal.as_root=true`, which Langfuse uses to treat the span as the trace root. |
| The `profile` metadata reads `default` or `custom`, so it cannot tell two profiles apart. Hermes names a profile only under `~/.hermes/profiles/<name>`. | `profile` is kept as Hermes reports it. Root metadata adds `profile_ref`: the first 12 hex characters of SHA-256 of the resolved Hermes home. It distinguishes profiles without exporting the home path. |

Tests: `tests/test_obs007_trace_shape.py` adds 5 cases, all red on the previous source. One drives the real Langfuse SDK in a subprocess with a capture-only exporter, synthetic keys and no network, and asserts one trace, one root, and the parent → `Subagent: leaf` → `Subagent turn` → `LLM call` chain. The strict source suite goes from 212 to 217.
