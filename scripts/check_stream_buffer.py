"""Print a browser-safe readiness report for the private stream buffer."""

from __future__ import annotations

import argparse
import json

from backend.service.stream_buffer_service import (
    StreamBufferError,
    probe_stream_buffer_assembly,
    stream_buffer_health,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the private stream buffer without exposing media.")
    parser.add_argument(
        "--assembly-probe",
        action="store_true",
        help="Assemble, validate, and immediately delete a diagnostic MP4.",
    )
    args = parser.parse_args()
    health = stream_buffer_health()
    report = health
    if args.assembly_probe and health["ready"]:
        try:
            assembly_probe = probe_stream_buffer_assembly()
        except StreamBufferError as exc:
            assembly_probe = {
                "schema_version": "stream-buffer-probe/1.0",
                "result": "FAILED",
                "error_code": exc.code,
                "contains_credentials": False,
                "contains_media_path": False,
                "media_retained": False,
            }
        report = {"health": health, "assembly_probe": assembly_probe}
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    assembly_ready = not args.assembly_probe or (
        isinstance(report.get("assembly_probe"), dict)
        and report["assembly_probe"].get("result") == "SUCCESS"
    )
    return 0 if health["ready"] and assembly_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
