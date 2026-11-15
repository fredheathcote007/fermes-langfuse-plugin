# OBS-002 D-02 / Hermes v0.23 source-assurance qualification

Date: 2026-11-06. Stage: **source tests only; NOT operational acceptance**.

## Approved design and release boundary

D-02 requires separate Langfuse projects and credentials per Hermes profile. The plugin resolves credentials through the active Hermes `agent.secret_scope` mapping, and caches the Langfuse SDK client by the effective Hermes home. The code being tested is the source in unmerged Fermes Langfuse PR #1, with v0.23 compatibility tests in stacked PR #2. No plugin runtime source has been changed in this assurance lane.

The v0.23 updater adds an opt-in automatic application mechanism; this is a source-level check of the consent gates and does not execute an update, clone, installation or rollback.

## Consolidated risk inventory and acceptance matrix

| Risk ID | Failure mode to exclude | Source-test oracle |
| --- | --- | --- |
| D02-P01/P03 | Profile A and B credentials, project endpoint and cached client alias in one process | Two unique synthetic scoped keypairs, endpoints and homes cause exactly two SDK-construction calls; client reused within but never across homes |
| D02-P02 | Missing multiplex scope reads another profile's ambient credentials | `UnscopedSecretError`, no SDK client construction; empty scope returns no client even with ambient keys |
| D02-P04/P05 | Scoped Hermes key loses precedence to legacy/ambient fallback, invalid placeholder accepted | Scoped legacy fallback used only when modern key absent; present placeholder causes no client; custom endpoints may accept nonstandard key prefixes while Cloud endpoints require standard prefixes |
| D02-P06 | Concurrent same-ID profile turns or client construction cross profile boundary | 64 overlapping warm-client lookups plus 50 rounds of eight concurrent cold-client constructions plus existing same-ID trace/attribution tests maintain isolation |
| D02-P07 | One profile exporter or finalizer handles another profile's queued observations | Existing `test_finalize_flushes_every_profile_without_an_ambient_scope` verifies per-profile flush and independent client mapping without a credential scope; **real network/project egress still blocked** |
| D02-P08 | Rotating a profile's credentials silently redirects existing cached client | Test demonstrates immutable per-home client cache until restart/rebuild; operational rotation procedure not qualified |
| H23-P09 | Automatic updates bypass default-off, held-ref or explicit grant boundaries | Ten v0.23-only source tests inject callbacks and fake receipt/marker state; default-off, positive opt-in, class filtering, held-ref and consent refusal are checked without installation |
| H23-P10 | Installer version floor, provenance or rollback incorrect | **BLOCKED**; requires separate installer qualification, not source-test acceptance |
| QA-P11 | Secrets, users, trace identifiers or endpoints exposed through evidence | Synthetic-only values in tests; CI source-only JSON receipt and JUnit artefact scan reject key/identity/endpoint tokens; no live Langfuse request |

## CI acceptance

Four full Langfuse test cells are required: pinned earlier Fermes Hermes core and upstream Hermes v0.23.0, each with SDK 4.15.2 and 4.18.0. The plugin source suite must collect **202 tests**, with 0 skipped/failed/error in each cell. Only the two v0.23 cells additionally run the ten updater source-gate tests. Each cell records immutable core SHA, SDK version, plugin SHA, manifest/core digests, JUnit XML counts and source-only PASS/FAIL/BLOCKED status.

The network-denial SDK exporter test is a Python-level DNS/connect/send interceptor, checked after SDK shutdown; native C networking and previously opened sockets are **not** proven by this test. The project-key tests spy on the actual plugin `_build_client` route but substitute an in-memory SDK factory; they do not prove remote project routing.

## Restrictions and remaining qualification

No production, configuration, credentials, catalogue publication, core update, real plugin installation, auto-update, merge or service changes. Both source PRs #1 and #2 remain open; this work is a separate stacked source-test PR. Full operational acceptance is still blocked on D-01 queued-identity disposal after consent revocation, D-02 actual distinct Langfuse project credentials and egress, D-04 seven-day trace retention/configuration-only recovery, v0.23 real gateway/delegation isolation and updater/installer rollback. Retain the original approved architecture and restore by dropping the isolated QA branch; no operational rollback is necessary because nothing is deployed.

## Confirmed defect and assurance limitation

Hermes v0.23 and the Fermes fork currently misinterpret quoted YAML `plugins.auto_apply: "false"` and `"no"` as truthy due to `bool(config_get(...))`. A scratch-only test of the real configuration loader confirmed the issue; see [Hermes issue #65](https://github.com/fredheathcote007/hermes-agent/issues/65). The new updater tests validate correctly typed inputs, held-with-ref refusal, consent-required refusal, and continuation across independent candidates. They **do not claim** the quoted-string consent bug is fixed: source-only updater approval is **blocked** until a separate fail-closed core correction is independently reviewed and qualified, under existing no-merge gates.

The JUnit artefact scan rejects synthetic key/identity/endpoint tokens on a successful source run. A test failure may emit only synthetic data to GitHub log output; no real credentials or user identifiers are used by this suite. The receipt-write gate fails closed when a token is detected.
