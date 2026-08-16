import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "deliverables"
    / "zy"
    / "pose-demo"
    / "scripts"
    / "build_provisional_baseline_package.py"
)
SPEC = importlib.util.spec_from_file_location("build_provisional_baseline_package", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SUBMIT_SCRIPT = SCRIPT.with_name("submit_golden_package.py")
SUBMIT_SPEC = importlib.util.spec_from_file_location("submit_golden_package", SUBMIT_SCRIPT)
SUBMIT_MODULE = importlib.util.module_from_spec(SUBMIT_SPEC)
SUBMIT_SPEC.loader.exec_module(SUBMIT_MODULE)


def manifest(days=(1, 2, 3)):
    return {
        "resident_id": "resident-fixture",
        "device_ref": "device-ref-fixture",
        "device_model": "EZVIZ_C6C",
        "camera_position_id": "fixed-position-fixture",
        "authorization_status": "AUTHORIZED",
        "authorization_record_id": "auth-ref-fixture",
        "retention_until": "2026-08-31T23:59:59+08:00",
        "recordings": [
            {
                "asset_id": f"asset-fixture-{day}",
                "captured_at": f"2026-08-{day:02d}T09:00:00+08:00",
                "local_path": f"D:/private/not-for-git/day-{day}.mp4",
                "rise_duration_seconds": 3.0 + day / 10,
                "relative_gait_speed_frame_heights_per_second": 0.40 + day / 100,
                "stable_trunk_angle_deg": 3.5 + day / 10,
                "confidence": 0.92,
                "data_quality": 0.90,
            }
            for day in days
        ],
    }


def test_three_day_manifest_builds_ready_privacy_safe_package():
    package = MODULE.build_package(manifest())
    assert package["package_status"] == "READY"
    assert package["progress"] == {"observed_days": 3, "provisional_target_days": 3}
    assert len(package["asset_manifest"]) == 3
    assert len(package["observations"]) == 9
    assert len(package["evidences"]) == 9
    assert {
        observation["feature_name"] for observation in package["observations"]
    } == {"sit_to_stand_duration", "relative_gait_speed", "stable_trunk_angle_deg"}
    assert all("local_path" not in asset for asset in package["asset_manifest"])
    assert all("source_path" not in asset for asset in package["asset_manifest"])
    assert "D:/private" not in str(package)
    SUBMIT_MODULE.validate_package(package)


def test_two_days_or_low_quality_remains_pending():
    assert MODULE.build_package(manifest((1, 2)))["package_status"] == "PENDING_ASSET"
    low_quality = manifest()
    low_quality["recordings"][1]["data_quality"] = 0.69
    assert MODULE.build_package(low_quality)["package_status"] == "PENDING_ASSET"
