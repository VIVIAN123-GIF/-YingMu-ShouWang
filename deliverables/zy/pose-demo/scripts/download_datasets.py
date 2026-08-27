from __future__ import annotations

import argparse
import csv
import hashlib
import html.parser
import json
import pathlib
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    for _ in range(5):
        try:
            with urllib.request.urlopen(
                request,
                context=default_ssl_context(),
                timeout=60,
            ) as response:
                header = response.headers.get("Content-Length")
                if header:
                    return int(header)
        except (OSError, urllib.error.URLError):
            continue
    return None


def download_file(
    url: str,
    destination: pathlib.Path,
    expected_size: int | None,
    max_attempts: int,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if expected_size is None:
        raise RuntimeError(f"Remote size is required for resumable download: {url}")
    if destination.exists() and destination.stat().st_size > expected_size:
        destination.unlink()

    offset = destination.stat().st_size if destination.exists() else 0
    chunk_size = 4 * 1024 * 1024
    while offset < expected_size:
        end = min(offset + chunk_size, expected_size) - 1
        expected_chunk_size = end - offset + 1
        for attempt in range(1, max_attempts + 1):
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Range": f"bytes={offset}-{end}",
                },
            )
            try:
                with urllib.request.urlopen(
                    request,
                    context=default_ssl_context(),
                    timeout=90,
                ) as response:
                    status_code = getattr(response, "status", None)
                    content_range = response.headers.get("Content-Range", "")
                    match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+)", content_range)
                    if status_code != 206 or not match:
                        raise RuntimeError(
                            f"invalid ranged response status={status_code} range={content_range!r}"
                        )
                    actual_start, actual_end, actual_total = map(int, match.groups())
                    if (actual_start, actual_end, actual_total) != (offset, end, expected_size):
                        raise RuntimeError(
                            "ranged response mismatch "
                            f"{actual_start}-{actual_end}/{actual_total}; "
                            f"expected {offset}-{end}/{expected_size}"
                        )
                    data = response.read(expected_chunk_size + 1)
                    if len(data) != expected_chunk_size:
                        raise RuntimeError(
                            f"ranged response length {len(data)}; expected {expected_chunk_size}"
                        )
                with destination.open("ab") as handle:
                    handle.write(data)
                offset += len(data)
                print(
                    f"Downloaded {destination.name}: {offset}/{expected_size} bytes",
                    flush=True,
                )
                break
            except (OSError, urllib.error.URLError, RuntimeError) as exc:
                if attempt == max_attempts:
                    raise RuntimeError(
                        f"Failed range {offset}-{end} for {destination} after "
                        f"{max_attempts} attempts: {exc}"
                    ) from exc
                print(
                    f"Retry {attempt}/{max_attempts}: {destination.name} "
                    f"range {offset}-{end} after {type(exc).__name__}",
                    flush=True,
                )


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


def build_urfd_items(include_preview_mp4: bool, camera_filter: str = "all") -> list[DownloadItem]:
    items: list[DownloadItem] = []
    for index in range(1, 31):
        seq = f"fall-{index:02d}"
        for camera in ("cam0", "cam1"):
            if camera_filter != "all" and camera != camera_filter:
                continue
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
                if camera_filter != "all" and camera != camera_filter:
                    continue
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
        if camera_filter == "cam1":
            continue
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


def download_items(
    root: pathlib.Path,
    items: Iterable[DownloadItem],
    overwrite: bool,
    workers: int,
    max_attempts: int,
) -> None:
    def download_one(item: DownloadItem) -> None:
        destination = root / item.relative_path
        expected_size = item.expected_size if item.expected_size is not None else remote_size(item.source_url)
        if expected_size is None:
            raise RuntimeError(f"Unable to determine remote size for {item.source_url}")
        if destination.exists() and not overwrite:
            if expected_size is not None and destination.stat().st_size == expected_size:
                print(f"Skip existing: {destination}", flush=True)
                return
        print(f"Downloading: {item.source_url}", flush=True)
        download_file(item.source_url, destination, expected_size, max_attempts)
        if expected_size is not None and destination.stat().st_size != expected_size:
            raise RuntimeError(f"Incomplete download for {destination}: {destination.stat().st_size}/{expected_size} bytes.")

    item_list = list(items)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(download_one, item): item for item in item_list}
        for future in as_completed(futures):
            future.result()


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
    parser.add_argument("--workers", type=int, default=1, help="Concurrent download workers.")
    parser.add_argument(
        "--max-download-attempts",
        type=int,
        default=50,
        help="Maximum resume attempts per source file.",
    )
    parser.add_argument(
        "--camera-filter",
        choices=("all", "cam0", "cam1"),
        default="all",
        help="Download only the selected URFD camera. ADL sequences are available for cam0 only.",
    )
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    all_items: list[DownloadItem] = []
    if args.dataset in ("urfd", "all"):
        verify_urfd_index()
        all_items.extend(
            build_urfd_items(
                include_preview_mp4=args.include_preview_mp4,
                camera_filter=args.camera_filter,
            )
        )
    if args.dataset in ("pre-vfall", "all"):
        all_items.extend(build_pre_vfall_items())

    download_items(
        root,
        all_items,
        overwrite=args.overwrite,
        workers=max(1, args.workers),
        max_attempts=max(1, args.max_download_attempts),
    )
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
