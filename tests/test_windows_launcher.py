from __future__ import annotations

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.static_frontend import SPAStaticFiles
from scripts import yingmu_launcher as launcher


def test_source_child_command_uses_module_execution(monkeypatch):
    monkeypatch.delattr(launcher.sys, "frozen", raising=False)

    command = launcher.self_command("server", "--port", "8080")

    assert command == [sys.executable, "-m", "scripts.yingmu_launcher", "server", "--port", "8080"]


def test_demo_environment_uses_isolated_database(tmp_path, monkeypatch):
    monkeypatch.delenv("YINGMU_DB_PATH", raising=False)

    values = launcher.apply_demo_environment(tmp_path)

    assert values["YINGMU_ENV"] == "mock"
    assert values["YINGMU_DB_PATH"].endswith("demo.db")
    assert os.environ["YINGMU_DB_PATH"] == values["YINGMU_DB_PATH"]
    assert values["EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST"] == "false"


def test_live_environment_rejects_missing_credentials(tmp_path):
    config = tmp_path / ".env.local"
    config.write_text("YINGMU_ENV=live\nEZVIZ_APP_KEY=only-key\n", encoding="utf-8")

    with pytest.raises(ValueError, match="EZVIZ_APP_SECRET"):
        launcher.load_live_environment(config, tmp_path)


def test_live_environment_rejects_unsigned_webhook_mode(tmp_path):
    config = tmp_path / ".env.local"
    config.write_text(
        "EZVIZ_APP_KEY=key\nEZVIZ_APP_SECRET=secret\nEZVIZ_DEVICE_SERIAL=device\n"
        "EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST=true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="refuses"):
        launcher.load_live_environment(config, tmp_path)


def test_demo_seed_posts_existing_fixed_sequence():
    requests = []

    def requester(method, path, payload):
        requests.append((method, path, payload))
        if path == "/api/v1/evidence" and payload["evidence_id"] == "evi-mock-lateral-drift-001":
            return 201, {"evaluation": {"event_id": "event-mock-fall-001"}}
        if path == "/api/v1/risk/evaluate":
            return 200, {"event": {"status": "RESOLVED"}}
        return 201, {}

    summary = launcher.seed_demo("http://unused", requester=requester)

    assert summary["source_mode"] == "MOCK"
    assert summary["simulated"] is True
    assert summary["event_id"] == "event-mock-fall-001"
    assert summary["final_status"] == "RESOLVED"
    posted_observations = [
        payload["observation_id"]
        for _, path, payload in requests
        if path == "/api/v1/observations"
    ]
    posted_evidence = [
        payload["evidence_id"]
        for _, path, payload in requests
        if path == "/api/v1/evidence"
    ]
    assert "obs-mock-transition-001" in posted_observations
    assert "obs-mock-lateral-drift-001" in posted_observations
    assert "evi-mock-transition-001" in posted_evidence
    assert "evi-mock-lateral-drift-001" in posted_evidence
    assert any(path.endswith("/intervene") for _, path, _ in requests)


def test_spa_static_files_falls_back_to_index_for_deep_links(tmp_path):
    (tmp_path / "index.html").write_text("<main>dashboard</main>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('ok')", encoding="utf-8")
    app = FastAPI()
    app.mount("/", SPAStaticFiles(directory=tmp_path, html=True), name="frontend")

    with TestClient(app) as client:
        deep_link = client.get("/events/event-001")
        asset = client.get("/app.js")

    assert deep_link.status_code == 200
    assert deep_link.text == "<main>dashboard</main>"
    assert asset.status_code == 200
    assert asset.text == "console.log('ok')"


def test_verify_frontend_rejects_non_vue_html(monkeypatch):
    class Response:
        status = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return b"<html>missing mount point</html>"

    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())

    with pytest.raises(RuntimeError, match="frontend"):
        launcher.verify_frontend("http://unused")


def test_worker_specs_add_stream_buffer_only_for_enabled_live(monkeypatch):
    monkeypatch.delattr(launcher.sys, "frozen", raising=False)

    demo = launcher.worker_specs("demo", {"YINGMU_STREAM_BUFFER_ENABLED": "true"})
    live_disabled = launcher.worker_specs("live", {"YINGMU_STREAM_BUFFER_ENABLED": "false"})
    live_enabled = launcher.worker_specs("live", {"YINGMU_STREAM_BUFFER_ENABLED": "true"})

    assert [name for name, _ in demo] == ["alarm-worker", "agent-worker"]
    assert [name for name, _ in live_disabled] == ["alarm-worker", "agent-worker"]
    assert [name for name, _ in live_enabled] == [
        "alarm-worker", "agent-worker", "stream-buffer-worker",
    ]


def test_terminate_stops_every_started_process():
    class Process:
        def __init__(self):
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def wait(self, timeout):
            del timeout
            return self.returncode

        def kill(self):
            self.returncode = -9

    processes = [Process() for _ in range(4)]

    launcher._terminate(processes)

    assert all(process.terminated for process in processes)


def test_terminate_waits_after_force_kill():
    class Process:
        def __init__(self):
            self.wait_calls = 0
            self.killed = False

        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout):
            del timeout
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise launcher.subprocess.TimeoutExpired("worker", 5)
            return -9

        def kill(self):
            self.killed = True

    process = Process()

    launcher._terminate([process])

    assert process.killed is True
    assert process.wait_calls == 2


def test_terminate_reports_process_that_survives_force_kill():
    class Process:
        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout):
            raise launcher.subprocess.TimeoutExpired("worker", timeout)

        def kill(self):
            return None

    with pytest.raises(RuntimeError, match="PROCESS_TERMINATION_FAILED"):
        launcher._terminate([Process()])


def test_live_launcher_purges_configured_stream_buffer(tmp_path, monkeypatch):
    from backend.service import stream_buffer_service

    calls = []
    monkeypatch.setattr(
        stream_buffer_service,
        "purge_stream_buffer_runtime",
        lambda root: calls.append(root) or {
            "removed_segments": 2,
            "removed_workspaces": 1,
            "status_removed": True,
            "lock_removed": True,
            "lock_active": False,
        },
    )

    result = launcher._purge_live_stream_buffer(
        "live",
        {
            "YINGMU_STREAM_BUFFER_ENABLED": "true",
            "YINGMU_STREAM_BUFFER_ROOT": str(tmp_path / "buffer"),
        },
    )

    assert calls == [tmp_path / "buffer"]
    assert result["removed_segments"] == 2


def test_demo_launcher_does_not_purge_stream_buffer():
    assert launcher._purge_live_stream_buffer(
        "demo", {"YINGMU_STREAM_BUFFER_ENABLED": "true"}
    ) is None


def test_live_launcher_rejects_active_cleanup_lock(tmp_path, monkeypatch):
    from backend.service import stream_buffer_service

    monkeypatch.setattr(
        stream_buffer_service,
        "purge_stream_buffer_runtime",
        lambda _root: {
            "removed_segments": 0,
            "removed_workspaces": 0,
            "status_removed": False,
            "lock_removed": False,
            "lock_active": True,
        },
    )

    with pytest.raises(RuntimeError, match="STREAM_BUFFER_WORKER_STILL_ACTIVE"):
        launcher._purge_live_stream_buffer(
            "live",
            {
                "YINGMU_STREAM_BUFFER_ENABLED": "true",
                "YINGMU_STREAM_BUFFER_ROOT": str(tmp_path / "buffer"),
            },
        )


def test_self_check_loads_required_local_resources(capsys):
    assert launcher.run_self_check() == 0

    payload = __import__("json").loads(capsys.readouterr().out)
    assert payload["status"] == "SUCCESS"
    assert payload["device_contacted"] is False
    assert payload["scene_config_ids"] == [
        "scene-living-room-v1", "scene-recorded-demo-v1",
    ]
