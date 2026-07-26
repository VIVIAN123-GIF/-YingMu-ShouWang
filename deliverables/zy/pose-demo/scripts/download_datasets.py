from __future__ import annotations

import argparse
import csv
import hashlib
import html.parser
import json
import pathlib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Iterable


URFD_PAGE = "https://fenix.ur.edu.pl/~mkepski/ds/uf.html"
URFD_BASE = "https://fenix.ur.edu.pl/~mkepski/ds/data/"
PRE_VFALL_ARTICLE_ID = "26488216"
PRE_VFALL_API_CANDIDATES = (
    f"https://api.figshare.com/v2/articles/{PRE_VFALL_ARTICLE_ID}/versions/3",
    f"https://api.figshare.com/v2/articles/{PRE_VFALL_ARTICLE_ID}",
)


@dataclass
class DownloadItem:
    dataset: str
    label: str
    modality: str
    source_url: str
    relative_path: pathlib.Path
    expected_size: int | None = None


class UrfdLinkParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href")
        if href:
            self.hrefs.append(href)


def default_ssl_context() -> ssl.SSLContext:
    return ssl._create_unverified_context()


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, context=default_ssl_context()) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, context=default_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def remote_size(url: str) -> int | None:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
    try:
        with urllib.request.urlopen(request, context=default_ssl_context()) as response:
            header = response.headers.get("Content-Length")
            return int(header) if header else None
    except Exception:
        return None


def download_file(url: str, destination: pathlib.Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing_size = destination.stat().st_size if destination.exists() else 0
    headers = {"User-Agent": "Mozilla/5.0"}
    if existing_size > 0:
        headers["Range"] = f"bytes={existing_size}-"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, context=default_ssl_context()) as response:
        status_code = getattr(response, "status", None)
        mode = "ab" if existing_size > 0 and status_code == 206 else "wb"
        with destination.open(mode) as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_pre_vfall_modality(name: str) -> str:
    lowered = name.lower()
    if lowered.endswith((".zip", ".png", ".jpg", ".jpeg", ".bmp")):
        return "rgb"
    if "depth" in lowered:
        return "depth"
    if lowered.endswith(".csv"):
        return "metadata"
    return "archive"


def build_urfd_items(include_preview_mp4: bool) -> list[DownloadItem]:
    items: list[DownloadItem] = []
    for index in range(1, 31):
        seq = f"fall-{index:02d}"
        for camera in ("cam0", "cam1"):
            filename = f"{seq}-{camera}-rgb.zip"
            items.append(
                DownloadItem(
                    dataset="urfd",
                    label="fall",
                    modality="rgb",
                    source_url=urllib.parse.urljoin(URFD_BASE, filename),
                    relative_path=pathlib.Path("urfd/original") / filename,
                )
            )
        data_name = f"{seq}-data.csv"
        items.append(
            DownloadItem(
                dataset="urfd",
                label="fall",
                modality="metadata",
                source_url=urllib.parse.urljoin(URFD_BASE, data_name),
                relative_path=pathlib.Path("urfd/original") / data_name,
            )
        )
        if include_preview_mp4 and index == 1:
            for camera in ("cam0", "cam1"):
                preview_name = f"{seq}-{camera}.mp4"
                items.append(
                    DownloadItem(
                        dataset="urfd",
                        label="fall",
                        modality="video",
                        source_url=urllib.parse.urljoin(URFD_BASE, preview_name),
                        relative_path=pathlib.Path("urfd/samples") / preview_name,
                    )
                )

    for index in range(1, 41):
        seq = f"adl-{index:02d}"
        rgb_name = f"{seq}-cam0-rgb.zip"
        items.append(
            DownloadItem(
                dataset="urfd",
                label="adl",
                modality="rgb",
                source_url=urllib.parse.urljoin(URFD_BASE, rgb_name),
                relative_path=pathlib.Path("urfd/original") / rgb_name,
            )
        )
        data_name = f"{seq}-data.csv"
        items.append(
            DownloadItem(
                dataset="urfd",
                label="adl",
                modality="metadata",
                source_url=urllib.parse.urljoin(URFD_BASE, data_name),
                relative_path=pathlib.Path("urfd/original") / data_name,
            )
        )
    return items


def build_pre_vfall_items() -> list[DownloadItem]:
    article = None
    for candidate in PRE_VFALL_API_CANDIDATES:
        article = fetch_json(candidate)
        if article.get("files"):
            break
    if not article or not article.get("files"):
        raise RuntimeError("Unable to resolve Pre-VFall files from Figshare API.")

    items: list[DownloadItem] = []
    for file_info in article["files"]:
        name = file_info["name"]
        items.append(
            DownloadItem(
                dataset="pre-vfall",
                label="unknown",
                modality=infer_pre_vfall_modality(name),
                source_url=file_info["download_url"],
                relative_path=pathlib.Path("pre-vfall/original") / name,
                expected_size=file_info.get("size"),
            )
        )
    return items


def verify_urfd_index() -> None:
    page = fetch_text(URFD_PAGE)
    parser = UrfdLinkParser()
    parser.feed(page)
    hrefs = set(parser.hrefs)
    required = {
        "./data/fall-01-cam0-rgb.zip",
        "./data/fall-30-cam1-rgb.zip",
        "./data/adl-01-cam0-rgb.zip",
        "./data/adl-40-cam0-rgb.zip",
    }
    missing = sorted(required - hrefs)
    if missing:
        raise RuntimeError(f"URFD page is missing expected links: {missing}")


def write_manifest(root: pathlib.Path, downloaded_items: Iterable[DownloadItem]) -> pathlib.Path:
    manifest_path = root / "manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["dataset", "relative_path", "file_name", "label", "modality", "source_url", "size_bytes", "sha256"],
        )
        writer.writeheader()
        for item in downloaded_items:
            destination = root / item.relative_path
            if destination.exists():
                writer.writerow(
                    {
                        "dataset": item.dataset,
                        "relative_path": str(item.relative_path).replace("\\", "/"),
                        "file_name": destination.name,
                        "label": item.label,
                        "modality": item.modality,
                        "source_url": item.source_url,
                        "size_bytes": destination.stat().st_size,
                        "sha256": sha256_file(destination),
                    }
                )
    return manifest_path


def download_items(root: pathlib.Path, items: Iterable[DownloadItem], overwrite: bool) -> None:
    for item in items:
        destination = root / item.relative_path
        expected_size = item.expected_size if item.expected_size is not None else remote_size(item.source_url)
        if destination.exists() and not overwrite:
            if expected_size is not None and destination.stat().st_size == expected_size:
                print(f"Skip existing: {destination}")
                continue
        print(f"Downloading: {item.source_url}")
        download_file(item.source_url, destination)
        if expected_size is not None and destination.stat().st_size != expected_size:
            raise RuntimeError(f"Incomplete download for {destination}: {destination.stat().st_size}/{expected_size} bytes.")


def extract_archives(root: pathlib.Path) -> None:
    for archive in sorted(root.rglob("*.zip")):
        destination = archive.parent.parent / "extracted" / archive.stem
        destination.mkdir(parents=True, exist_ok=True)
        if any(destination.iterdir()):
            continue
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download URFD and Pre-VFall datasets.")
    parser.add_argument("--dataset", choices=("urfd", "pre-vfall", "all"), default="all")
    parser.add_argument("--root", default="data/raw")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-extract", action="store_true")
    parser.add_argument("--include-preview-mp4", action="store_true")
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    all_items: list[DownloadItem] = []
    if args.dataset in ("urfd", "all"):
        verify_urfd_index()
        all_items.extend(build_urfd_items(include_preview_mp4=args.include_preview_mp4))
    if args.dataset in ("pre-vfall", "all"):
        all_items.extend(build_pre_vfall_items())

    download_items(root, all_items, overwrite=args.overwrite)
    if not args.skip_extract:
        extract_archives(root)
    manifest_path = write_manifest(root, all_items)
    print(f"Manifest written to: {manifest_path}")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        print(f"HTTP error: {exc}", file=sys.stderr)
        raise
