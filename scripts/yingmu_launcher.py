"""Windows-friendly process launcher for the packaged YingMu application."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable


LOGGER = logging.getLogger("yingmu.launcher")


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def self_command(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "scripts.yingmu_launcher", *args]


def configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )


def apply_demo_environment(runtime_dir: Path) -> dict[str, str]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    values = {
        "YINGMU_ENV": "mock",
        "YINGMU_DB_PATH": str((runtime_dir / "demo.db").resolve()),
        "YINGMU_CONTROL_TOKEN": "packaged-demo-control-token",
        "EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST": "false",
    }
    os.environ.update(values)
    return values


def load_live_environment(config_path: Path, runtime_dir: Path) -> dict[str, str]:
    if not config_path.is_file():
        raise ValueError(f"live configuration not found: {config_path}")
    from dotenv import dotenv_values

    loaded = {key: value for key, value in dotenv_values(config_path).items() if value is not None}
    loaded["YINGMU_ENV"] = "live"
    loaded.setdefault("YINGMU_DB_PATH", str((runtime_dir / "live.db").resolve()))
    required = ("EZVIZ_APP_KEY", "EZVIZ_APP_SECRET", "EZVIZ_DEVICE_SERIAL")
    missing = [key for key in required if not loaded.get(key, "").strip()]
    if missing:
        raise ValueError(f"live configuration is missing: {', '.join(missing)}")
    if loaded.get("EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST", "false").lower() == "true":
        raise ValueError("live mode refuses EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST=true")
    os.environ.update(loaded)
    return loaded


def json_request(method: str, url: str, payload: dict | None = None, timeout: float = 5.0) -> tuple[int, object]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed: object = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"detail": body[:300]}
        return exc.code, parsed


def verify_frontend(base_url: str, timeout: float = 5.0) -> None:
    request = urllib.request.Request(base_url, headers={"Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        content_type = response.headers.get("Content-Type", "")
    if response.status != 200 or "text/html" not in content_type or "<div id=\"app\"></div>" not in body:
        raise RuntimeError("packaged frontend did not pass the smoke test")


def wait_for_health(base_url: str, processes: list[subprocess.Popen], timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError("a packaged service exited before the health check passed")
        try:
            status, payload = json_request("GET", f"{base_url}/health", timeout=1.0)
            if status == 200 and isinstance(payload, dict) and payload.get("status") == "ok":
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    raise TimeoutError(f"health check did not pass within {timeout_seconds:g} seconds")


def _post_checked(requester: Callable, path: str, payload: dict) -> object:
    status, body = requester("POST", path, payload)
    if status not in {200, 201}:
        raise RuntimeError(f"demo seed failed at {path}: HTTP {status}")
    return body


def seed_demo(base_url: str, requester: Callable | None = None) -> dict[str, object]:
    from contracts.v1.mock_data import RESIDENT_ID, sequence

    if requester is None:
        requester = lambda method, path, payload: json_request(method, f"{base_url}{path}", payload, 10.0)
    payload = sequence()
    observations = {item["observation_id"]: item for item in payload["observations"]}
    evidence = {item["evidence_id"]: item for item in payload["evidence"]}

    _post_checked(requester, "/api/v1/observations", observations["obs-mock-green-001"])
    _post_checked(requester, "/api/v1/evidence", evidence["evi-mock-green-001"])
    _post_checked(requester, "/api/v1/observations", observations["obs-mock-rapid-rise-001"])
    _post_checked(requester, "/api/v1/evidence", evidence["evi-mock-rapid-rise-001"])
    _post_checked(requester, "/api/v1/observations", observations["obs-mock-trunk-sway-001"])
    orange = _post_checked(requester, "/api/v1/evidence", evidence["evi-mock-trunk-sway-001"])
    event_id = orange["evaluation"]["event_id"]
    _post_checked(requester, f"/api/v1/events/{event_id}/intervene", None)
    _post_checked(requester, "/api/v1/observations", observations["obs-mock-posture-recovered-001"])
    _post_checked(requester, "/api/v1/observations", observations["obs-mock-stable-trunk-angle-001"])
    _post_checked(requester, "/api/v1/evidence", evidence["evi-mock-posture-recovered-001"])
    resolved = _post_checked(requester, "/api/v1/risk/evaluate", {
        "resident_id": RESIDENT_ID,
        "evaluated_at": "2026-07-31T03:08:30+08:00",
    })
    return {
        "source_mode": "MOCK",
        "simulated": True,
        "resident_id": RESIDENT_ID,
        "event_id": event_id,
        "final_status": resolved.get("event", {}).get("status") if isinstance(resolved, dict) else None,
    }


def run_server(host: str, port: int) -> int:
    import uvicorn
    from backend.main import app

    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def run_alarm_worker(poll_seconds: float) -> int:
    from backend.worker.alarm_worker import run

    return asyncio.run(run(once=False, poll_seconds=poll_seconds))


def run_agent_worker(poll_seconds: float) -> int:
    from backend.worker.agent_worker import run

    return asyncio.run(run(once=False, poll_seconds=poll_seconds))


def _terminate(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 5
    for process in processes:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()


def run_stack(mode: str, args: argparse.Namespace) -> int:
    root = application_root()
    runtime_dir = (args.runtime_dir or (root / "runtime")).resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(runtime_dir / "logs" / f"{mode}.log")
    if mode == "demo":
        environment = apply_demo_environment(runtime_dir)
    else:
        environment = load_live_environment((args.config or (root / "config" / ".env.local")).resolve(), runtime_dir)
    child_environment = os.environ.copy()
    child_environment.update(environment)
    logs = runtime_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handles = [
        (logs / "server.log").open("a", encoding="utf-8"),
        (logs / "alarm-worker.log").open("a", encoding="utf-8"),
        (logs / "agent-worker.log").open("a", encoding="utf-8"),
    ]
    processes: list[subprocess.Popen] = []
    try:
        server_command = self_command("server", "--host", args.host, "--port", str(args.port))
        processes.append(subprocess.Popen(
            server_command,
            cwd=root,
            env=child_environment,
            stdout=handles[0],
            stderr=subprocess.STDOUT,
        ))
        base_url = f"http://{args.host if args.host not in {'0.0.0.0', '::'} else '127.0.0.1'}:{args.port}"
        wait_for_health(base_url, processes)
        worker_commands = (
            self_command("alarm-worker", "--poll-seconds", "1"),
            self_command("agent-worker", "--poll-seconds", "1"),
        )
        for command, handle in zip(worker_commands, handles[1:]):
            processes.append(subprocess.Popen(
                command,
                cwd=root,
                env=child_environment,
                stdout=handle,
                stderr=subprocess.STDOUT,
            ))
        if mode == "demo":
            summary = seed_demo(base_url)
            LOGGER.info("demo_seeded %s", json.dumps(summary, ensure_ascii=False))
            if args.smoke_test:
                verify_frontend(base_url)
                LOGGER.info("smoke_test_passed base_url=%s", base_url)
                return 0
        if not args.no_browser:
            webbrowser.open(base_url)
        print(f"萤目守望已启动：{base_url}")
        print("按 Ctrl+C 停止全部服务。")
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        raise RuntimeError("a packaged service stopped unexpectedly; inspect runtime/logs")
    except KeyboardInterrupt:
        LOGGER.info("shutdown_requested")
        return 0
    finally:
        _terminate(processes)
        for handle in handles:
            handle.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="YingMuShouWang", description="萤目守望统一启动器")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("demo", "live"):
        stack = subparsers.add_parser(command)
        stack.add_argument("--host", default="127.0.0.1")
        stack.add_argument("--port", type=int, default=8000)
        stack.add_argument("--runtime-dir", type=Path)
        stack.add_argument("--config", type=Path)
        stack.add_argument("--no-browser", action="store_true")
        stack.set_defaults(smoke_test=False)
        if command == "demo":
            stack.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    server = subparsers.add_parser("server")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8000)
    for command in ("alarm-worker", "agent-worker"):
        worker = subparsers.add_parser(command)
        worker.add_argument("--poll-seconds", type=float, default=1.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if getattr(args, "port", 8000) not in range(1, 65536):
        raise SystemExit("port must be between 1 and 65535")
    if getattr(args, "poll_seconds", 1.0) <= 0:
        raise SystemExit("poll-seconds must be positive")
    try:
        if args.command in {"demo", "live"}:
            return run_stack(args.command, args)
        if args.command == "server":
            return run_server(args.host, args.port)
        if args.command == "alarm-worker":
            return run_alarm_worker(args.poll_seconds)
        return run_agent_worker(args.poll_seconds)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
