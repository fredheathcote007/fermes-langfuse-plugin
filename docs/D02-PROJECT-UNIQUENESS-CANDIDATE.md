# OBS-002 D02/T08 — shared project-key source guard (candidate)

**Status:** source-only candidate with separate isolated QA integration receipts; NOT accepted for full gateway operational qualification or installation.
**Base:** PR #3 at commit `9bd2cf7ce725926fa18fbc9331dae5e2f2e1871e`.
**Requirement:** D02 requires distinct Langfuse projects and credential pairs for Hermes profiles.

## Reproduction and proposed correction

Using non-network synthetic credentials and a constructor spy, two distinct profile homes both built SDK clients when configured with the same Langfuse project public key. The new test was RED before the fix and GREEN afterwards.

The candidate records separate in-memory SHA-256 digests of the public project key and secret key against the resolved profile home after successful client construction. Another home presenting either matching credential component is rejected before SDK construction, with a diagnostic containing no keys or profile identities. The existing first-build lock serialises race conditions.

Four added source tests cover identical keypairs, the same public key with a different secret, the same secret with a different public key, and concurrent cold client builds with an identical project key. One further regression uses the real pinned Hermes gateway profile runtime-scope binder, verifying credential/home context resets and rejecting a reused secret with another public key. This extends the strict source suite from 202 to **207 tests**. The separate v0.23 updater control remains 10 tests.

## Boundaries and required evidence

- Source code and CI tests do not change credentials, Langfuse projects, deployed plugins or QA service settings. Separately authorised isolated integration tests used two new disposable QA projects and expiring credentials; the existing project/key was preserved.
- The registries are in process memory only and do not log either key, its digest, or an identity.
- No hot credential rotation: changes require restart as with the existing immutable client cache.
- Distinct public and secret API key pairs can refer to the SAME backend project. This source guard cannot prove project uniqueness across different keys; independent D02 live project-ID/egress qualification is still mandatory.
- Host aliases and endpoint aliases with distinct keys are likewise outside this source guard.
- D01 identity attribution remains disabled until queued-exporter discard is proven.
- All four pinned core/SDK CI cells, independent exact-diff review, and operational T01/T08 evidence remain acceptance gates. Do not merge/install on source-only proof.

The original PR #3 202-test receipts remain historical source-only evidence and are not re-labelled as 207-test results.

## 13 November QA-only operational evidence (not a live gateway deployment)

With owner approval, two disposable QA projects and expiring test-only credentials were created in the existing isolated Langfuse stack. Using real SDK v4.18 and the candidate plugin, distinct Hermes profile scopes routed synthetic spans to their correct projects. A second integration test exercised the **actual `gateway.run._profile_runtime_scope`** binder from pinned Hermes v0.23, verified per-turn secret/home restoration, and rejected the same secret paired with another public key.

Read-only exact-name checks against Langfuse v4 ClickHouse `events_core` and `events_full` showed the expected project ID and empty `user_id` for every synthetic record, without reading historical trace contents. Private receipts reside at `/srv/scratch/obs002-closure-20261106/receipts/20261113-verified/`; no credential values appear in this document or repository.

The additional gateway-binder source regression is enforced in all four pinned Hermes/SDK CI combinations. The source suite now expects **207 tests, zero skipped or failed**. This is **not proof of a launched multiplexed gateway** or of automatic detection when two independently issued API key pairs map to one backend project. Full D02 operational acceptance and independent review remain outstanding.
