import argparse
import json
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from evidence import validate_evidence_collection
from observation import validate_observation_collection


class SubmissionError(RuntimeError):
    pass


def load_bundle(path):
    bundle = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(bundle, dict):
        raise ValueError("联调包必须是JSON对象")
    observations = validate_observation_collection(bundle.get("observations"))
    evidence_items = validate_evidence_collection(bundle.get("evidence"))
    observation_ids = {item["observation_id"] for item in observations}
    for item in evidence_items:
        missing = sorted(set(item["observation_ids"]) - observation_ids)
        if missing:
            raise ValueError(
                f"Evidence {item['evidence_id']}引用了联调包中不存在的Observation：{missing}"
            )
        linked = [
            observation
            for observation in observations
            if observation["observation_id"] in item["observation_ids"]
        ]
        if any(
            observation["resident_id"] != item["resident_id"]
            or observation["source_mode"] != item["source_mode"]
            or observation["simulated"] != item["simulated"]
            for observation in linked
        ):
            raise ValueError("Evidence必须继承关联Observation的resident/source_mode/simulated")
    return bundle


def _post_json(url, payload, timeout, opener):
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Request-ID": f"cym-{payload.get('observation_id') or payload.get('evidence_id')}"},
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body
    except HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8"))
            detail = body.get("error", {})
            message = f"{detail.get('code', 'HTTP_ERROR')}: {detail.get('message', str(error))}"
        except (UnicodeDecodeError, json.JSONDecodeError):
            message = str(error)
        raise SubmissionError(f"HTTP {error.code} {message}") from error
    except URLError as error:
        raise SubmissionError(f"无法连接后端：{error.reason}") from error


def submit_bundle(bundle, base_url, timeout=10.0, opener=urlopen, dry_run=False):
    base_url = base_url.rstrip("/")
    log = {
        "schema_version": "1.0",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_url": base_url,
        "dry_run": bool(dry_run),
        "success": True,
        "results": [],
    }
    queue = [
        ("observation", "/api/v1/observations", item, item["observation_id"])
        for item in bundle["observations"]
    ] + [
        ("evidence", "/api/v1/evidence", item, item["evidence_id"])
        for item in bundle["evidence"]
    ]

    for item_type, endpoint, payload, item_id in queue:
        if dry_run:
            log["results"].append(
                {"type": item_type, "id": item_id, "endpoint": endpoint, "status": "validated"}
            )
            continue
        try:
            http_status, response = _post_json(base_url + endpoint, payload, timeout, opener)
            log["results"].append(
                {
                    "type": item_type,
                    "id": item_id,
                    "endpoint": endpoint,
                    "status": "submitted",
                    "http_status": http_status,
                    "saved": bool(response.get("saved")),
                    "idempotent": bool(response.get("idempotent")),
                }
            )
        except SubmissionError as error:
            log["success"] = False
            log["results"].append(
                {"type": item_type, "id": item_id, "endpoint": endpoint, "status": "failed", "error": str(error)}
            )
            break
    return log


def parse_args():
    parser = argparse.ArgumentParser(description="按Observation优先顺序提交联调包到FastAPI后端")
    parser.add_argument("--bundle", type=Path, required=True, help="行为Observation/Evidence联调包")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="后端根地址")
    parser.add_argument("--log-output", type=Path, required=True, help="脱敏提交日志JSON")
    parser.add_argument("--timeout", type=float, default=10.0, help="单次HTTP请求超时秒数")
    parser.add_argument("--dry-run", action="store_true", help="只做本地校验，不发送HTTP请求")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        bundle = load_bundle(args.bundle)
        log = submit_bundle(
            bundle,
            args.base_url,
            timeout=args.timeout,
            dry_run=args.dry_run,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"联调包校验失败：{error}")
        return 2

    output_path = args.log_output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"{'校验' if args.dry_run else '提交'}完成："
        f"成功{sum(item['status'] != 'failed' for item in log['results'])}项，"
        f"失败{sum(item['status'] == 'failed' for item in log['results'])}项"
    )
    print(f"脱敏日志：{output_path}")
    return 0 if log["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
