from __future__ import annotations

import csv
import json
from pathlib import Path

from contracts.v1.forewarning import SceneCalibration


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "docs" / "field-acceptance"


def test_positive_pair_manifest_has_fixed_roles_and_privacy_safe_fields():
    path = TEMPLATES / "03-positive-pair-manifest.template.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)

    assert reader.fieldnames == [
        "pair_id", "clip_role", "clip_id", "participant_ref",
        "authorization_record_id", "captured_at", "retention_until",
        "camera_position_id", "scene_config_id", "location", "resolution",
        "fps", "codec_name", "planned_label", "transition_start_ms",
        "transition_end_ms", "assessment_window_start_ms",
        "assessment_window_end_ms", "stable_start_ms", "stable_end_ms",
        "annotator_a_ref", "annotator_b_ref", "annotation_status", "validity",
        "exclusion_reason", "sha256", "private_storage_confirmed",
        "algorithm_run_status", "notes",
    ]
    assert [row["clip_role"] for row in rows] == ["RISK", "RECOVERY"]
    assert not {
        "participant_name", "participant_phone", "media_path", "private_path",
        "device_serial", "app_key", "app_secret", "access_token",
    }.intersection(reader.fieldnames)


def test_scene_example_is_valid_and_contains_all_four_zone_types():
    payload = json.loads(
        (TEMPLATES / "04-scene-calibration.example.json").read_text(encoding="utf-8")
    )

    calibration = SceneCalibration.model_validate(payload)

    assert {zone.zone_type for zone in calibration.zones} == {
        "HIGH_RISK", "SUPPORT", "OBSTACLE", "SAFE",
    }
    assert "not-for-live" in calibration.scene_config_id
    assert "pelvis center" in (calibration.notes or "")


def test_live_acceptance_template_is_redacted_and_incomplete():
    path = TEMPLATES / "06-live-device-acceptance.template.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False).lower()

    assert payload["status"] == "INCOMPLETE"
    assert payload["provenance"] == {
        "source_mode": "LIVE_DEVICE",
        "simulated": False,
        "inheritance_passed": False,
    }
    assert payload["contains_credentials"] is False
    assert payload["contains_media_path"] is False
    assert payload["contains_device_serial"] is False
    assert "app_secret" not in serialized
    assert "access_token" not in serialized
    assert "http://" not in serialized and "https://" not in serialized
