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
        if path == "/api/v1/evidence" and payload["evidence_id"] == "evi-mock-trunk-sway-001":
            return 201, {"evaluation": {"event_id": "event-mock-fall-001"}}
        if path == "/api/v1/risk/evaluate":
            return 200, {"event": {"status": "RESOLVED"}}
        return 201, {}

    summary = launcher.seed_demo("http://unused", requester=requester)

    assert summary["source_mode"] == "MOCK"
    assert summary["simulated"] is True
    assert summary["event_id"] == "event-mock-fall-001"
    assert summary["final_status"] == "RESOLVED"
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
