# OBS-002 D02/T08 — shared project-key source guard (candidate)

**Status:** source-only candidate; NOT accepted for runtime qualification or installation.
**Base:** PR #3 at commit `9bd2cf7ce725926fa18fbc9331dae5e2f2e1871e`.
**Requirement:** D02 requires distinct Langfuse projects and credential pairs for Hermes profiles.

## Reproduction and proposed correction

Using non-network synthetic credentials and a constructor spy, two distinct profile homes both built SDK clients when configured with the same Langfuse project public key. The new test was RED before the fix and GREEN afterwards.

The candidate records an in-memory SHA-256 digest of the public project key against the resolved profile home after successful client construction. Another home presenting either matching credential component is rejected before SDK construction, with a diagnostic containing no keys or profile identities. The existing first-build lock serialises race conditions.

Four added source tests cover identical keypairs, the same public key with a different secret, the same secret with a different public key, and concurrent cold client builds with an identical project key. This extends the strict source suite from 202 to **206 tests**. The separate v0.23 updater control remains 10 tests.

## Boundaries and required evidence

- No real credentials, Langfuse projects, deployed plugins or QA service settings were changed.
- The registries are in process memory only and do not log either key, its digest, or an identity.
- No hot credential rotation: changes require restart as with the existing immutable client cache.
- Distinct public and secret API key pairs can refer to the SAME backend project. This source guard cannot prove project uniqueness across different keys; independent D02 live project-ID/egress qualification is still mandatory.
- Host aliases and endpoint aliases with distinct keys are likewise outside this source guard.
- D01 identity attribution remains disabled until queued-exporter discard is proven.
- All four pinned core/SDK CI cells, independent exact-diff review, and operational T01/T08 evidence remain acceptance gates. Do not merge/install on source-only proof.

The original PR #3 202-test receipts remain historical source-only evidence and are not re-labelled as 206-test results.
