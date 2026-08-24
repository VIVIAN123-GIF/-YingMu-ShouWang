"""Probe fresh EZVIZ HLS URLs and compare playlist/TS segment progression.

The probe intentionally emits only redacted metadata.  It never writes a
playlist, segment, token, device serial, or complete playback URL to disk.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import EZVIZ_CHANNEL_NO, EZVIZ_DEVICE_SERIAL
from scripts.validate_ezviz_live import business_code, call_stage, device_alias, now_iso


TZ = timezone(timedelta(hours=8))
SAFE_HEX = re.compile(r"[^0-9a-f]")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_playlist(body: str, playlist_url: str) -> dict[str, Any]:
    media_match = re.search(r"#EXT-X-MEDIA-SEQUENCE:(\d+)", body)
    media_sequence = int(media_match.group(1)) if media_match else None
    target_match = re.search(r"#EXT-X-TARGETDURATION:(\d+)", body)
    target_duration = int(target_match.group(1)) if target_match else None
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    segments: list[dict[str, Any]] = []
    pending_duration: float | None = None
    ordinal = 0
    for line in lines:
        if line.startswith("#EXTINF:"):
            try:
                pending_duration = float(line.split(":", 1)[1].split(",", 1)[0])
            except ValueError:
                pending_duration = None
            continue
        if line.startswith("#") or pending_duration is None:
            continue
        absolute = urljoin(playlist_url, line)
        index = media_sequence + ordinal if media_sequence is not None else None
        segments.append(
            {
                "ordinal": ordinal,
                "index": index,
                "duration_seconds": pending_duration,
                "uri_hash": sha256_bytes(line.encode("utf-8")),
                "url": absolute,
            }
        )
        ordinal += 1
        pending_duration = None
    return {
        "media_sequence": media_sequence,
        "target_duration": target_duration,
        "segment_count": len(segments),
        "has_endlist": "#EXT-X-ENDLIST" in body,
        "has_vod": "#EXT-X-PLAYLIST-TYPE:VOD" in body,
        "playlist_sha256": sha256_bytes(body.encode("utf-8")),
        "segments": segments,
    }


async def fetch_playlist(client: httpx.AsyncClient, url: str, warmup_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + warmup_seconds
    last: dict[str, Any] | None = None
    while True:
        response = await client.get(url, headers={"Cache-Control": "no-cache"})
        response.raise_for_status()
        last = parse_playlist(response.text, url)
        if len(last["segments"]) >= 3 or time.monotonic() >= deadline:
            return last
        await asyncio.sleep(2)
    assert last is not None


async def run_once(run_index: int, warmup_seconds: int) -> dict[str, Any]:
    payload = {
        "deviceSerial": EZVIZ_DEVICE_SERIAL,
        "channelNo": EZVIZ_CHANNEL_NO,
        "protocol": 2,
        "expireTime": 3600,
        "quality": 2,
    }
    body, http_status, latency_ms, _ = await call_stage("/v2/live/address/get", payload)
    code = business_code(body)
    data = body.get("data") if isinstance(body, dict) else None
    address = data.get("url") if isinstance(data, dict) else None
    result: dict[str, Any] = {
        "run": run_index,
        "requested_at": now_iso(),
        "http_status": http_status,
        "business_code": code,
        "address_obtained": isinstance(address, str) and urlparse(address).scheme in {"http", "https"},
        "address_latency_ms": latency_ms,
        "playlist": None,
        "segment_hashes": [],
        "failure_reason": None,
    }
    if not result["address_obtained"]:
        result["failure_reason"] = "PLAYBACK_ADDRESS_NOT_CONFIRMED"
        return result
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            playlist = await fetch_playlist(client, address, warmup_seconds)
            public_playlist = {key: value for key, value in playlist.items() if key != "segments"}
            result["playlist"] = public_playlist
            for segment in playlist["segments"]:
                response = await client.get(segment["url"], headers={"Cache-Control": "no-cache"})
                response.raise_for_status()
                result["segment_hashes"].append(
                    {
                        "ordinal": segment["ordinal"],
                        "index": segment["index"],
                        "duration_seconds": segment["duration_seconds"],
                        "byte_size": len(response.content),
                        "content_sha256": sha256_bytes(response.content),
                        "uri_hash": segment["uri_hash"],
                    }
                )
    except httpx.TimeoutException:
        result["failure_reason"] = "REQUEST_TIMEOUT"
    except httpx.HTTPError:
        result["failure_reason"] = "HTTP_REQUEST_ERROR"
    except (ValueError, KeyError):
        result["failure_reason"] = "INVALID_PLAYLIST"
    return result


async def main_async(args: argparse.Namespace) -> int:
    runs: list[dict[str, Any]] = []
    for index in range(1, args.runs + 1):
        runs.append(await run_once(index, args.warmup_seconds))
        if index < args.runs:
            await asyncio.sleep(args.interval_seconds)
    successful = [run for run in runs if run["failure_reason"] is None]
    segment_hashes = [
        item["content_sha256"]
        for run in successful
        for item in run["segment_hashes"]
    ]
    report = {
        "schema_version": "1.0",
        "test_kind": "EZVIZ_HLS_SEGMENT_PROBE",
        "generated_at": datetime.now(TZ).isoformat(timespec="milliseconds"),
        "device_alias": device_alias(),
        "channel_no": EZVIZ_CHANNEL_NO,
        "runs": runs,
        "successful_runs": len(successful),
        "unique_segment_content_hashes": len(set(segment_hashes)),
        "contains_credentials": False,
        "contains_playback_url": False,
    }
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if len(successful) == args.runs else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare fresh EZVIZ HLS playlists and TS segments.")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--interval-seconds", type=int, default=15)
    parser.add_argument("--warmup-seconds", type=int, default=15)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.runs < 1 or args.interval_seconds < 0 or args.warmup_seconds < 1:
        parser.error("runs must be >=1, interval-seconds >=0, warmup-seconds >=1")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
