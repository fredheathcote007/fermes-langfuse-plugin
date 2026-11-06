# OBS-002: Hermes v0.23.0 compatibility assessment

Date: 2026-11-06. Scope: **source-only compatibility, no installation or merge**.

## Exact inputs and upstream findings

- Hermes release: `NousResearch/hermes-agent` **v0.23.0**, immutable commit `2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19`, released 2026-11-05.
- Earlier Fermes plugin compatibility core: `fredheathcote007/hermes-agent` commit `ab41b03062b99b9b19a310c203c5bf48d7820fee`.
- Fermes controlled plugin branch: its exact Git commit is resolved per CI run; source is not merged, installed or deployed by this test.
- Langfuse SDK: declared pinned `4.15.2`, additionally qualified on `4.18.0`; OpenTelemetry delivery and queued identity revocation need separate operational proof.
- v0.23.0's **official** Hermes plugin catalogue still pins upstream Langfuse source `e1f16143f164c4db10ea8fc0fc47ff8ac611e9fc` dated 2026-10-23. Upstream plugin isolation PR #293 merged later on 2026-11-06. Therefore v0.23.0's catalogue pin does **not** include that merge.

## Consolidated change inventory and scope

| Risk | v0.23.0 exposure | Required oracle | Source-only result |
| --- | --- | --- | --- |
| H23-01 | New plugin loader/manifest and version floor | Four clean-room CI cells with exact source SHA, manifest digest and admission check | Tested locally; GitHub CI pending |
| H23-02 | Shared gateway and multi-profile plugin hosts | Two profiles with same turn/session/child IDs; correct positive and negative project routing in live gateway | BLOCKED: live runtime not qualified |
| H23-03 | Session/hook lifecycle, retry and close | Exactly accounted-for root/tool/generation/subagent events, no cross-profile closure after interrupted/duplicate hooks | Source tests only; live hook ledger BLOCKED |
| H23-04 | Pluggable cross-profile delegation | Child trace is isolated by effective profile and cannot borrow parent's identifiers or credentials | BLOCKED: live delegation test required |
| H23-05 | Opt-in `plugins.auto_apply` and bulk `plugins update` | In disposable home, an attempted update leaves review-pinned plugin unchanged when auto-apply is OFF; no update without a new SHA review | BLOCKED: behavioural update test not run |
| H23-06 | `requires_hermes` floors and installer rollback | Older unsupported core rejected for the right reason; pin/rollback tested against local disposable installations | BLOCKED: installer/rollback test not run |
| H23-07 | SDK compatibility and identity egress | Plugin full suite and manifest pass for both SDKs; synthetic CapturingExporter sees no optional userId even unsafe explicit opt-in and zero Python-level socket DNS/connect/send attempts through the guarded APIs, including SDK shutdown; native-network and pre-existing sockets remain unproven | Local source-only tests PASS |
| H23-08 | Provenance and evidence retention | Record core SHA, SDK version, core/manifest SHA256, test selection and exact PASS/FAIL/BLOCKED state per cell | Implemented in source-only CI receipt |

**No blanket upstream merge:** v0.23 adds shared-gateway coordination, auto-update, profile plugin hosts and delegation. Those are relevant compatibility surfaces to test, not authority to replace the Fermes fork or approved D01-D04 architecture. Do not enable auto-update for a deployment that relies on manually reviewed commit pins.

## Acceptance boundary

Four source CI combinations: earlier Fermes core and Hermes v0.23.0, each with Langfuse SDK 4.15.2 and 4.18.0 on Python 3.14. This matrix uses immutable source refs, a plugin admission check, the complete `langfuse/tests/` suite with exactly 191 collected and zero skipped, and a synthetic SDK-backed no-network egress probe. Each cell uploads a seven-day source-only receipt. Any failed/skipped/blocked required test is not a pass.

**Explicitly outside this source-only qualification:** gateway deployment, profile credential or project changes (D02), plugin update/installer actions on running systems, SDK queue purge after consent revocation (D01), seven-day storage retention/configuration recovery (D04), production, source or catalogue merge. No source-level PASS proves those operational requirements.

Review evidence and the full P01-P10/M11-M18/T01-T12 inventory are tracked in [OBS-002 issue #2](https://github.com/fredheathcote007/fermes-observability/issues/2). A separate source PR, independent review, GitHub CI and later owner approvals remain mandatory.
