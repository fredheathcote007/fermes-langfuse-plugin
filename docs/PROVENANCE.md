# OBS-002 controlled-source provenance

- Canonical intended source: `fredheathcote007/fermes-langfuse-plugin#langfuse`.
- Upstream: `https://github.com/NousResearch/hermes-official-plugins`, plugin subdirectory `langfuse`.
- Verified upstream baseline: `e7a218f26db88426ab3e7376f0e000b6e356f5e7` (includes upstream PR #293, merged as `2e577d8b6823e92d674259c8dafafc066d1aa25e` on 6 November 2026).
- Downstream source candidate: independently tested scratch commit `9dfc859cb8c069e58b34c899f6591a2c2511cc4f` in an isolated clone of upstream; copied `langfuse/` only, with no `__pycache__`, tokens, environment files or runtime traces.
- CI dependency: `fredheathcote007/hermes-agent` is PUBLIC as verified on 6 November 2026; GitHub Actions checks out pinned source `ab41b03062b99b9b19a310c203c5bf48d7820fee` using read-only permissions and no extra token. If visibility changes, this CI becomes BLOCKED until an authorised read-only checkout mechanism is reviewed.
- Declared Langfuse SDK dependency: `langfuse==4.15.2`; tested with SDK 4.15.2 and 4.18.0 and OpenTelemetry SDK 1.45.1; keep exact lock versions and receipts in a follow-on immutable release qualification.
- Source-only test evidence: 191 plugin tests passed with each SDK version, Hermes admission validator 15 PASS (one pre-existing warning category regarding private Hermes core imports). These are *not* operational privacy or production qualification.

## Disposition and deployment boundary

D-01 requests discard of all unsent identity-bearing telemetry after revocation. The supported SDK has no verified queue-discard mechanism. For this controlled interim, `end_user_attribution: true` still results in **no optional userId attribution**, not implied consent or guaranteed purge. The code keeps optional attribution fail closed. No production, QA service, credential, deployment, or merge authority is granted by this record.

D-02 distinct Langfuse projects and credentials per Hermes profile is an approved design direction, *not* a completed project-routing deployment.
D-04 seven-day disposable trace retention and configuration-only recovery is an approved design direction, *not* a verified storage policy.

The source repository contains the code once. Do not add a second in-tree third-party plugin to Hermes core. A separate reviewed PR in the `fredheathcote007/hermes-agent` fork must update `plugin-catalog/langfuse.yaml` to the exact immutable Fermes Git commit and source subdirectory; never update the catalog with a branch name. Installation is a distinct later approval. Rollback to the previously pinned official plugin revision needs explicit rollback and duplicate-install tests; never delete existing installations during source-only qualification.
