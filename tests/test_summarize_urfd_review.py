import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import cv2
import numpy as np

from scripts.summarize_urfd_review import build_review


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_download_module():
    path = Path("deliverables/zy/pose-demo/scripts/download_datasets.py").resolve()
    spec = importlib.util.spec_from_file_location("download_datasets_for_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_feature_module():
    path = Path("deliverables/zy/pose-demo/scripts/build_gait_feature_dataset.py").resolve()
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("build_gait_features_for_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_urfd_cam0_download_selection_has_full_sequence_set():
    module = load_download_module()
    items = module.build_urfd_items(include_preview_mp4=False, camera_filter="cam0")

    assert len(items) == 140
    assert sum(item.modality == "rgb" for item in items) == 70
    assert sum(item.modality == "metadata" for item in items) == 70
    assert all("cam1" not in item.relative_path.as_posix() for item in items)


def test_feature_builder_reads_non_ascii_windows_path(tmp_path: Path):
    module = load_feature_module()
    image_path = tmp_path / "中文目录" / "frame-1.png"
    image_path.parent.mkdir()
    source = np.full((8, 10, 3), 127, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", source)
    assert ok
    encoded.tofile(image_path)

    decoded = module.read_image_bgr(image_path)

    assert decoded is not None
    assert decoded.shape == source.shape


def review_args(tmp_path: Path) -> argparse.Namespace:
    manifest = tmp_path / "manifest.csv"
    features = tmp_path / "features.csv"
    frames = tmp_path / "frames.csv"
    build_summary = tmp_path / "build-summary.json"
    baseline = tmp_path / "baseline.json"
    model = tmp_path / "model.task"
    feature_builder = tmp_path / "builder.py"
    public_manifest = tmp_path / "public-manifest.csv"

    manifest_rows = []
    for label in ("fall", "adl"):
        for file_name, modality in (
            (f"{label}-01-cam0-rgb.zip", "rgb"),
            (f"{label}-01-data.csv", "metadata"),
        ):
            manifest_rows.append(
                {
                    "dataset": "urfd",
                    "relative_path": f"urfd/original/{file_name}",
                    "file_name": file_name,
                    "label": label,
                    "modality": modality,
                    "source_url": f"https://example.test/{file_name}",
                    "size_bytes": "10",
                    "sha256": "a" * 64,
                }
            )
    write_csv(manifest, manifest_rows)

    feature_rows = [
        {
            "sequence_id": "fall-01-cam0-rgb",
            "label": "fall",
            "total_frames": "2",
            "detected_frames": "2",
            "valid_frame_ratio": "1.0",
            "step_speed": "0.31",
            "sway_frequency_hz": "0.3",
            "step_length_asymmetry_ratio": "0.8",
            "mean_core_visibility": "0.9",
        },
        {
            "sequence_id": "adl-01-cam0-rgb",
            "label": "adl",
            "total_frames": "2",
            "detected_frames": "1",
            "valid_frame_ratio": "0.5",
            "step_speed": "0.1",
            "sway_frequency_hz": "0.2",
            "step_length_asymmetry_ratio": "0.1",
            "mean_core_visibility": "0.8",
        },
    ]
    write_csv(features, feature_rows)

    frame_rows = [
        {
            "sequence_id": "fall-01-cam0-rgb",
            "timestamp_ms": "0",
            "pelvis_y_smooth": "0.60",
            "trunk_angle_deg_smooth": "0.0",
        },
        {
            "sequence_id": "fall-01-cam0-rgb",
            "timestamp_ms": "500",
            "pelvis_y_smooth": "0.50",
            "trunk_angle_deg_smooth": "10.0",
        },
        {
            "sequence_id": "adl-01-cam0-rgb",
            "timestamp_ms": "2000",
            "pelvis_y_smooth": "0.55",
            "trunk_angle_deg_smooth": "1.0",
        },
        {
            "sequence_id": "adl-01-cam0-rgb",
            "timestamp_ms": "2500",
            "pelvis_y_smooth": "0.54",
            "trunk_angle_deg_smooth": "1.5",
        },
    ]
    write_csv(frames, frame_rows)

    build_summary.write_text(
        json.dumps({"sequence_count": 2, "frame_row_count": 4}), encoding="utf-8"
    )
    baseline.write_text(
        json.dumps(
            {
                "rule_parameters": {
                    "tracking_lost_valid_frame_ratio": 0.65,
                    "baseline_speed": 0.1,
                    "relative_speed_deviation_alert_ratio": 1.5,
                    "baseline_asymmetry": 0.2,
                    "gait_instability_alert_ratio": 2.0,
                    "baseline_sway_deg": 8.0,
                }
            }
        ),
        encoding="utf-8",
    )
    model.write_bytes(b"model")
    feature_builder.write_text("# builder\n", encoding="utf-8")

    return argparse.Namespace(
        manifest=manifest,
        features=features,
        frames=frames,
        build_summary=build_summary,
        baseline_profile=baseline,
        model=model,
        feature_builder=feature_builder,
        output=tmp_path / "result.json",
        public_manifest_output=public_manifest,
        download_date="2026-08-27",
        camera_filter="cam0",
        frame_stride=2,
        visibility_threshold=0.5,
        expected_fall_count=1,
        expected_adl_count=1,
        archived_processed=False,
    )


def test_review_reports_quality_and_descriptive_indicators(tmp_path: Path):
    result = build_review(review_args(tmp_path))

    assert result["status"] == "COMPLETE"
    assert result["sample_count"] == 2
    assert result["processing"]["processing_success_count"] == 1
    assert result["processing"]["low_quality_count"] == 1
    assert result["processing"]["failure_count"] == 0
    indicators = result["metrics"]["engineering_indicator_counts"]
    assert indicators["rapid_rise"] == {"total": 1, "fall_label": 1, "adl_label": 0}
    assert indicators["trunk_sway"] == {"total": 1, "fall_label": 1, "adl_label": 0}
    assert indicators["tracking_lost"] == {"total": 1, "fall_label": 0, "adl_label": 1}
    assert result["metrics"]["classification_metrics"]["status"] == "NOT_APPLICABLE"
    assert result["source_artifacts"]["public_manifest_sha256"]


def test_review_rejects_missing_processed_sequence(tmp_path: Path):
    args = review_args(tmp_path)
    rows = list(csv.DictReader(args.features.open(encoding="utf-8")))
    write_csv(args.features, rows[:1])

    with pytest.raises(ValueError, match="processed sequence mismatch"):
        build_review(args)
