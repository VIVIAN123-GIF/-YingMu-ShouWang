"""Submit algorithm Observations and their linked Evidence to the frozen backend API.

Algorithms own feature extraction and Evidence adaptation. This script only
submits their already-generated JSON in the required order and never computes
the final risk level.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def load_json(path: Path) -> dict:
    """Load exactly one JSON object from an algorithm output file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 JSON 文件 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 必须是一个 JSON 对象")
    return payload


def post_json(
    url: str,
    payload: dict,
    timeout_seconds: float,
    retries: int = 2,
    retry_interval: float = 0.5,
) -> dict:
    """提交幂等结果；仅重试临时网络、限流和服务端错误。"""
    last_error: Exception | None = None
    for attempt in range(1, retries + 2):
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return {
                    "status_code": response.status,
                    "body": json.loads(response.read().decode("utf-8")),
                    "attempts": attempt,
                }
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"{url} 返回 HTTP {exc.code}: {body}")
            retryable = exc.code == 408 or exc.code == 429 or 500 <= exc.code < 600
        except (URLError, TimeoutError) as exc:
            last_error = RuntimeError(f"无法连接 {url}: {exc}")
            retryable = True
        if retryable and attempt <= retries:
            time.sleep(retry_interval * attempt)
            continue
        raise last_error
    raise RuntimeError(f"{url} request failed unexpectedly")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="依次提交冻结 v1.0 Observation 和其关联 Evidence。"
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--observation",
        type=Path,
        action="append",
        help="Observation JSON 文件；Evidence 关联多条 Observation 时重复传入此参数",
    )
    input_group.add_argument(
        "--scenario-file",
        type=Path,
        help="包含 scenarios 数组的算法批量样例 JSON 文件",
    )
    parser.add_argument("--evidence", type=Path, help="Evidence JSON 文件")
    parser.add_argument("--scenario", help="批量样例中要提交的 scenario 名称，与 --scenario-file 一起使用")
    parser.add_argument(
        "--backend-url", default="http://127.0.0.1:8000", help="后端地址，不含 /api/v1"
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="单次请求超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="临时故障的额外重试次数")
    parser.add_argument("--retry-interval", type=float, default=0.5, help="首次重试间隔秒数")
    args = parser.parse_args()

    try:
        if args.scenario_file:
            if args.evidence:
                raise ValueError("使用 --scenario-file 时不能同时指定 --evidence")
            if not args.scenario:
                raise ValueError("使用 --scenario-file 时必须指定 --scenario")
            envelope = load_json(args.scenario_file)
            scenarios = envelope.get("scenarios")
            if not isinstance(scenarios, list):
                raise ValueError("批量样例必须包含 scenarios 数组")
            matched = next(
                (item for item in scenarios if item.get("scenario") == args.scenario), None
            )
            if not isinstance(matched, dict):
                raise ValueError(f"未找到场景: {args.scenario}")
            observation = matched.get("observation")
            evidence = matched.get("evidence")
            if not isinstance(observation, dict) or not isinstance(evidence, dict):
                raise ValueError("场景必须同时包含 observation 和 evidence 对象")
            observations = [observation]
        else:
            if not args.evidence:
                raise ValueError("使用 --observation 时必须指定 --evidence")
            observations = [load_json(path) for path in args.observation]
            evidence = load_json(args.evidence)
        observation_ids_to_submit = [item.get("observation_id") for item in observations]
        observation_ids = evidence.get("observation_ids")
        if not isinstance(observation_ids, list) or not observation_ids:
            raise ValueError("Evidence.observation_ids 必须是非空数组")
        if None in observation_ids_to_submit or len(set(observation_ids_to_submit)) != len(observation_ids_to_submit):
            raise ValueError("每个 Observation 必须有唯一的 observation_id")
        missing = set(observation_ids) - set(observation_ids_to_submit)
        if missing:
            raise ValueError(
                f"本次提交缺少 Evidence 引用的 Observation: {sorted(missing)}"
            )

        base_url = args.backend_url.rstrip("/")
        observation_results = [
            post_json(f"{base_url}/api/v1/observations", observation, args.timeout,
                      args.retries, args.retry_interval)
            for observation in observations
        ]
        evidence_result = post_json(
            f"{base_url}/api/v1/evidence", evidence, args.timeout,
            args.retries, args.retry_interval
        )
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"SUBMIT_FAILED: {exc}") from exc

    print(json.dumps({
        "observations": observation_results,
        "evidence": evidence_result,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
