"""Shared integrity and privacy checks for public release artifacts."""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator


MEDIA_SUFFIXES = {".avi", ".m4a", ".mkv", ".mov", ".mp4", ".wav", ".webm"}
DATABASE_SUFFIXES = {".db", ".db-journal", ".sqlite", ".sqlite3"}
TEXT_SUFFIXES = {
    ".cmd", ".css", ".csv", ".env", ".example", ".html", ".ini", ".js",
    ".json", ".md", ".ps1", ".py", ".toml", ".ts", ".txt", ".vue", ".xml",
    ".yaml", ".yml",
}
TEXT_NAMES = {"LICENSE", "MANIFEST-SHA256.txt", "requirements.txt"}
IGNORED_PARTS = {
    ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__",
    "build", "dist", "node_modules",
}
PRIVATE_PARTS = {
    "private", "private-media", "signed-consent", "test_locked",
}
SENSITIVE_KEYS = {
    "AGENT_LLM_API_KEY", "EZVIZ_ACCESS_TOKEN", "EZVIZ_APP_KEY", "EZVIZ_APP_SECRET",
    "EZVIZ_DEVICE_SERIAL", "EZVIZ_DEVICE_VERIFY_CODE", "EZVIZ_WEBHOOK_SECRET",
    "YINGMU_CONTROL_TOKEN",
}
DUMMY_VALUES = {
    "", "[redacted]", "changeme", "demo", "device", "example", "key", "only-key",
    "placeholder", "redacted", "replace-me", "secret", "test", "token", "your-value",
}
ABSOLUTE_LOCAL_PATH = re.compile(
    r"(?i)(?:[a-z]:\\" + "Users" + r"\\[^\\\s]+\\|/" + "Users" + r"/[^/\s]+/|/"
    + "home" + r"/[^/\s]+/)"
)
SENSITIVE_URL = re.compile(
    r"(?i)https?://([^/\s?#]+)[^\s]*[?&](?:access_?token|auth|signature|token)="
    r"([^&#\s]+)"
)
ASSIGNMENT = re.compile(r"(?m)^[ \t]*([A-Z][A-Z0-9_]+)[ \t]*=[ \t]*([^#\r\n]*)$")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


@dataclass(frozen=True)
class Finding:
    path: str
    kind: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "kind": self.kind, "detail": self.detail}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def forbidden_release_path(name: str, *, allow_final_video: bool = False) -> str | None:
    path = PurePosixPath(name.replace("\\", "/"))
    lowered_parts = {part.lower() for part in path.parts}
    lowered_name = path.name.lower()
    suffix = path.suffix.lower()
    if lowered_name == ".env":
        return "runtime environment file"
    if lowered_parts & PRIVATE_PARTS:
        return "private data directory"
    if suffix in DATABASE_SUFFIXES:
        return "database file"
    if suffix in MEDIA_SUFFIXES and not (allow_final_video and lowered_name.endswith("演示视频.mp4")):
        return "raw media file"
    if "授权" in path.name and any(word in path.name.lower() for word in ("signed", "scan", "原件", "签字")):
        return "signed consent original"
    return None


def is_text_name(name: str) -> bool:
    path = PurePosixPath(name)
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES


def scan_text(name: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    if ABSOLUTE_LOCAL_PATH.search(text):
        findings.append(Finding(name, "absolute_local_path", "contains a user-specific absolute path"))
    if PRIVATE_KEY.search(text):
        findings.append(Finding(name, "private_key", "contains a private key block"))
    for match in ASSIGNMENT.finditer(text):
        key, raw_value = match.groups()
        if key not in SENSITIVE_KEYS:
            continue
        raw_value = raw_value.strip()
        env_style = PurePosixPath(name).name in {".env", ".env.example", ".env.template"}
        quoted_literal = (
            len(raw_value) >= 2
            and raw_value[0] in {"'", '"'}
            and raw_value[-1] == raw_value[0]
        )
        if not env_style and not quoted_literal:
            continue
        value = raw_value.strip("'\"")
        normalized = value.lower()
        if normalized in DUMMY_VALUES or normalized.startswith(("${", "{{", "<")):
            continue
        findings.append(Finding(name, "credential_assignment", f"{key} has a non-placeholder value"))
    for match in SENSITIVE_URL.finditer(text):
        host, value = match.groups()
        if host.lower().endswith((".invalid", ".test")) or value.lower() in DUMMY_VALUES:
            continue
        findings.append(Finding(name, "temporary_or_signed_url", f"sensitive URL query on {host}"))
    return findings


def scan_files(files: Iterable[tuple[Path, str]], *, allow_final_video: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    for path, name in files:
        reason = forbidden_release_path(name, allow_final_video=allow_final_video)
        if reason:
            findings.append(Finding(name, "forbidden_path", reason))
            continue
        if is_text_name(name) and path.stat().st_size <= 5 * 1024 * 1024:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                findings.append(Finding(name, "invalid_text_encoding", "expected UTF-8 text"))
            else:
                findings.extend(scan_text(name, text))
    return findings


def _zip_text_entries(path: Path) -> Iterator[tuple[str, str | None]]:
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            if entry.is_dir() or entry.file_size > 5 * 1024 * 1024 or not is_text_name(entry.filename):
                continue
            try:
                yield entry.filename, archive.read(entry).decode("utf-8")
            except UnicodeDecodeError:
                yield entry.filename, None


def scan_zip(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    with zipfile.ZipFile(path) as archive:
        names = [entry.filename for entry in archive.infolist() if not entry.is_dir()]
    for name in names:
        reason = forbidden_release_path(name)
        if reason:
            findings.append(Finding(f"{path.name}!/{name}", "forbidden_path", reason))
    for name, text in _zip_text_entries(path):
        if text is None:
            findings.append(Finding(f"{path.name}!/{name}", "invalid_text_encoding", "expected UTF-8 text"))
        else:
            findings.extend(
                Finding(f"{path.name}!/{finding.path}", finding.kind, finding.detail)
                for finding in scan_text(name, text)
            )
    return findings


def manifest_lines(root: Path, *, exclude_names: set[str] | None = None) -> list[str]:
    excluded = exclude_names or set()
    lines = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        lines.append(f"{sha256_file(path)}  {relative}")
    return lines
