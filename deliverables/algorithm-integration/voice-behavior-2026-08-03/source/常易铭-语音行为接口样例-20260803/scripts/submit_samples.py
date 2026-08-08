import argparse
import json
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def post_json(base_url, endpoint, payload, timeout):
    request = Request(
        base_url.rstrip("/") + endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
        return response.status, {
            "saved": body.get("saved"),
            "idempotent": body.get("idempotent"),
        }


def main():
    parser = argparse.ArgumentParser(description="顺序提交语音和行为接口样例")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--log-output", type=Path, default=Path("submission-log.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    results = []
    success = True
    for relative_path in manifest["request_order"]:
        payload = json.loads((root / relative_path).read_text(encoding="utf-8"))
        item_id = payload.get("observation_id") or payload.get("evidence_id")
        endpoint = "/api/v1/observations" if "observation_id" in payload else "/api/v1/evidence"
        if args.dry_run:
            results.append({"file": relative_path, "id": item_id, "status": "validated"})
            continue
        try:
            status, summary = post_json(args.base_url, endpoint, payload, args.timeout)
            results.append(
                {"file": relative_path, "id": item_id, "status": "submitted", "http_status": status, **summary}
            )
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            results.append({"file": relative_path, "id": item_id, "status": "failed", "http_status": error.code, "error": detail})
            success = False
            break
        except URLError as error:
            results.append({"file": relative_path, "id": item_id, "status": "failed", "error": str(error.reason)})
            success = False
            break

    log = {
        "schema_version": "1.0",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "dry_run": args.dry_run,
        "success": success,
        "results": results,
    }
    args.log_output.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"完成{len(results)}项，success={success}，日志：{args.log_output.resolve()}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
