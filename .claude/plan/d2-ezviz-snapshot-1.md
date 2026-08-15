# D2 Snapshot Asset Pipeline Extension

## Goal

Complete the backend-owned D2 stages after platform capture: download the
temporary Ezviz image, verify and store it privately, create a traceable Asset,
and only then move the alarm task to `WAITING_ALGORITHM`.

## Frozen Boundaries

- Real media is stored outside the repository in `YINGMU_PRIVATE_MEDIA_ROOT`.
- The temporary provider URL and private storage key are never public fields.
- Authorization metadata is mandatory before real media is persisted.
- No unauthenticated protected-media route is introduced in D2.
- Existing public Asset submissions remain backward compatible.

## Implementation

1. Add private-media, authorization, camera, model, and size-limit settings.
2. Add streaming download with status, content type, signature, byte limit,
   SHA-256, temporary-file cleanup, and atomic replacement.
3. Extend Asset persistence with content hash, media type, byte count, and an
   internal-only storage key.
4. Add compatible SQLite migrations for existing databases.
5. Connect the downloader to `AlarmProcessingTask` with deterministic Asset
   identity and retry/permanent-failure classification.
6. Add isolated tests without contacting the real Ezviz service.

## Acceptance

- A valid image creates one verified LIVE_DEVICE Asset.
- The private path and temporary URL never appear in public responses.
- Empty, invalid, oversized, unauthorized, and transient responses are handled
  deterministically and leave no `.part` files.
- `capture_asset_id` is non-null before `WAITING_ALGORITHM` is committed.
- Existing tests and D2 tests pass.

## Status

- [x] Scope frozen
- [x] Private download and verification
- [x] Asset metadata and migration
- [x] Worker integration
- [x] Tests and full regression
- [x] Commit and push
