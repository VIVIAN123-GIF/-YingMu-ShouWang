import hashlib
import json
import zipfile

from scripts.run_behavior_replay_acceptance import load_delivery


def test_result_only_delivery_requires_observation_asset_traceability(tmp_path):
    asset = {
        "asset_id": "asset-test", "title": "authorized test replay", "source_mode": "RECORDED_REPLAY",
        "simulated": True, "stream_url": None, "fallback_url": None, "fallback_kind": "LOCAL_AUTHORIZED_FILE",
        "available": False, "verification_status": "PROCESSED_LOCAL", "captured_at": "2026-08-09T10:00:00+08:00",
        "notice": "no raw video", "authorization_status": "AUTHORIZED",
    }
    observations = [{
        "schema_version": "1.0", "observation_id": "obs-test", "resident_id": "resident-test",
        "timestamp": "2026-08-09T10:00:01+08:00", "source": "tracking", "feature_name": "track_point_count",
        "feature_value": 4, "unit": "count", "location": "living_room", "confidence": 0.5,
        "data_quality": 0.6, "source_mode": "RECORDED_REPLAY", "asset_id": "asset-test", "simulated": True,
    }]
    entries = {
        "asset.json": json.dumps(asset).encode(),
        "behavior_observations.json": json.dumps(observations).encode(),
        "behavior_bundle.json": json.dumps({"observations": observations, "evidence": []}).encode(),
    }
    manifest = "\n".join(f"{hashlib.sha256(value).hexdigest().upper()}  {name}" for name, value in entries.items())
    archive_path = tmp_path / "delivery.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
        archive.writestr("sha256sums.txt", manifest)

    delivery = load_delivery(archive_path)

    assert delivery["asset"]["authorization_status"] == "AUTHORIZED"
    assert len(delivery["observations"]) == 1
    assert delivery["evidence_count"] == 0
