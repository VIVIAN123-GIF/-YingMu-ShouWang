# Gait Acceptance Summary

## Model
- Path: `models/pose_landmarker_heavy.task`
- Version: MediaPipe Pose Landmarker Heavy float16/1
- SHA-256: `64437af838a65d18e5ba7a0d39b465540069bc8aae8308de3e318aad31fcbc7b`
- Verification: `PoseLandmarker initialization: OK`

## Batches
- SUCCESS: `job-gait-success-check` / `None` / 58031 ms
- NO_EVIDENCE: `job-gait-noevidence-check` / `None` / 12031 ms
- LOW_QUALITY: `job-gait-lowquality-check` / `None` / 7031 ms
- FAILED: `job-gait-failed-check` / `MODEL_NOT_FOUND` / 0 ms

## Format Checks
- `adl_01_cam0.avi` -> `LOW_QUALITY` / vf=0.58 / 17078 ms
- `adl_01_cam0.mov` -> `LOW_QUALITY` / vf=0.58 / 16094 ms
- `adl_01_cam0.webm` -> `LOW_QUALITY` / vf=0.64 / 22188 ms
- `adl-01-cam0.mp4` -> `LOW_QUALITY` / vf=0.613 / 18484 ms

## Commands
- Install deps:
  `.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt -r contracts/requirements.txt -r deliverables/zy/pose-demo/requirements.txt`
- Verify environment:
  `.\.venv\Scripts\python.exe deliverables\zy\pose-demo\scripts\verify_setup.py --model models\pose_landmarker_heavy.task`
  Result: `PoseLandmarker initialization: OK`
- Run MediaPipe demo:
  `.\.venv\Scripts\python.exe deliverables\zy\pose-demo\scripts\run_pose_demo.py --input <redacted_authorized_video> --model models\pose_landmarker_heavy.task --output-dir <redacted_output> --max-frames 60`
  Result: MediaPipe completed on a real-person clip; generated media artifacts were not retained in this deliverable.
- Run tests:
  `.\.venv\Scripts\python.exe -m pytest tests\test_gait_adapter.py tests\test_contracts_and_mock.py tests\test_algorithm_gateway.py -q`
  Result: `32 passed`

## Failure Reasons
- `INPUT_NOT_FOUND` or `MODEL_NOT_FOUND` indicates unreadable input or missing model.
- `UNSUPPORTED_INPUT` is returned for extensions outside mp4/avi/mov/webm.
- OpenCV could not open the original non-ASCII source paths directly here, so temporary ASCII working copies were used and then removed from this deliverable.
