from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "deliverables"
    / "zy"
    / "pose-demo"
    / "scripts"
    / "download_pose_model.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("download_pose_model", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_download_is_verified_and_atomically_replaced(monkeypatch, tmp_path: Path):
    module = _load_module()
    payload = b"verified-model"
    output = tmp_path / "pose.task"
    output.write_bytes(b"old-model")
    monkeypatch.setattr(module, "EXPECTED_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(module, "download_file", lambda _url, destination: destination.write_bytes(payload))
    monkeypatch.setattr("sys.argv", [str(SCRIPT_PATH), "--output", str(output)])

    module.main()

    assert output.read_bytes() == payload
    assert not output.with_name("pose.task.part").exists()


def test_checksum_failure_preserves_existing_model(monkeypatch, tmp_path: Path):
    module = _load_module()
    output = tmp_path / "pose.task"
    output.write_bytes(b"existing-model")
    monkeypatch.setattr(module, "EXPECTED_SHA256", hashlib.sha256(b"expected").hexdigest())
    monkeypatch.setattr(module, "download_file", lambda _url, destination: destination.write_bytes(b"invalid"))
    monkeypatch.setattr("sys.argv", [str(SCRIPT_PATH), "--output", str(output)])

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        module.main()

    assert output.read_bytes() == b"existing-model"
    assert not output.with_name("pose.task.part").exists()
