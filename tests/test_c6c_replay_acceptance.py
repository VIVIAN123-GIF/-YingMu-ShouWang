from scripts.run_c6c_replay_acceptance import redact, validate_package


def _package():
    return {
        "schema_version": "1.0",
        "scenario_id": "c6c-test-001",
        "resident_id": "resident-c6c-test-001",
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "asset": {
            "asset_id": "asset-c6c-test-001", "title": "redacted clip",
            "source_mode": "RECORDED_REPLAY", "simulated": True,
            "stream_url": None, "fallback_url": None, "fallback_kind": "AUTHORIZED_CLIP",
            "available": True, "verification_status": "VERIFIED",
            "captured_at": "2026-08-02T14:00:00+08:00", "notice": "no local media in Git",
            "device_ref": "device-ref-test", "device_model": "EZVIZ_C6C",
            "camera_position_id": "position-test", "authorization_status": "AUTHORIZED",
            "authorization_record_id": "authorization-test", "retention_until": "2026-08-31T23:59:59+08:00",
        },
        "observations": [{
            "schema_version": "1.0", "observation_id": "obs-c6c-test-001",
            "resident_id": "resident-c6c-test-001", "timestamp": "2026-08-02T14:00:01+08:00",
            "source": "pose", "feature_name": "sit_to_stand_duration", "feature_value": 0.4,
            "unit": "second", "location": "living_room", "confidence": 0.8, "data_quality": 0.8,
            "source_mode": "RECORDED_REPLAY", "asset_id": "asset-c6c-test-001", "simulated": True,
        }],
        "evidence": [{
            "schema_version": "1.0", "evidence_id": "evi-c6c-test-001",
            "observation_ids": ["obs-c6c-test-001"], "resident_id": "resident-c6c-test-001",
            "timestamp": "2026-08-02T14:00:01+08:00", "risk_domain": "FALL", "evidence_type": "rapid_rise",
            "severity": 0.8, "confidence": 0.8, "data_quality": 0.8, "baseline_value": 2.5,
            "current_value": 0.4, "baseline_deviation": -0.84, "time_scale": "SHORT",
            "location": "living_room", "explanation": "rapid rise", "adapter_version": "c6c-test-v1",
            "source_mode": "RECORDED_REPLAY", "simulated": True,
        }],
    }


def test_c6c_package_validation_keeps_authorized_asset_provenance():
    package = validate_package(_package())
    assert package["asset"]["authorization_status"] == "AUTHORIZED"
    assert package["asset"]["device_model"] == "EZVIZ_C6C"


def test_c6c_summary_redacts_local_sources_and_credentials():
    value = redact({"video_zip": r"C:\private\video.zip", "stream_url": "https://private.example/live",
                    "access_token": "secret", "safe": "value"})
    assert value == {"video_zip": "[REDACTED]", "stream_url": "[REDACTED]",
                     "access_token": "[REDACTED]", "safe": "value"}
