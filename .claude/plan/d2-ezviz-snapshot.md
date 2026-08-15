# D2 Ezviz Snapshot Delivery Plan

## Goal

Complete the engineering portion of Zhang's D2 delivery: normalize real
Ezviz captures into the frozen `PlatformSnapshotResult`, keep temporary media
URLs process-local, generate a capture-only redacted acceptance batch, and
prepare the handoff artifacts for on-site execution.

## Scope

- Normalize provider capture responses into `PlatformSnapshotResult`.
- Separate the internal capture result from the public debug response.
- Do not create an Asset before the backend downloader has persisted media.
- Add capture-only and caller-selected output directory support to the live
  acceptance script.
- Persist ten independent redacted audit records and a capture-focused summary.
- Add tests for contracts, redaction, output isolation, and failure reporting.
- Add a D2 README and field verification template.

## Out Of Scope

- Supplying or rotating Ezviz credentials.
- Operating the physical camera or confirming the live scene.
- Downloading and retaining resident media without on-site authorization.
- Creating the backend Asset downloader owned by the backend role.
- Implementing playback, voice, algorithm Evidence, or agent explanations.

## Implementation

1. Add an internal normalized capture method to `DeviceAdapter`.
2. Make the public snapshot route return a redacted audit view.
3. Update alarm-task handoff to consume the normalized internal object without
   persisting or returning its temporary URL.
4. Extend `validate_ezviz_live.py` with capture-only mode, isolated output
   directories, contract validation, redacted per-run records, and summary
   statistics.
5. Add unit and integration tests.
6. Add D2 deliverable templates and exact on-site commands.

## Acceptance

- Public API responses and generated reports contain no temporary URL,
  credentials, verification code, or complete device serial.
- Successful live captures validate as `PlatformSnapshotResult`.
- Ten requested runs create ten distinct records, including failed attempts.
- Capture-only mode does not call the playback-address API.
- Existing tests continue to pass.

## Status

- [x] Plan created
- [x] Capture normalization and redaction
- [x] Acceptance batch tooling
- [x] Tests and documentation
- [x] Full verification
- [x] Commit and push
