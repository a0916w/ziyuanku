"""爬虫共用：把封面图下载到 data/covers/{source}/。"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COVERS_ROOT = REPO_ROOT / "data" / "covers"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)


def _safe_key(key: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", key).strip()[:120]


def _ext_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        if path.endswith(ext):
            return ext
    return ".jpg"


def cover_file_path(covers_dir: Path, key: str, cover_url: str) -> Path:
    return covers_dir / f"{_safe_key(key)}{_ext_from_url(cover_url)}"


def download_cover(
    cover_url: str,
    dest: Path,
    *,
    referer: str = "",
    timeout: int = 20,
) -> Path | None:
    """下载单张封面，已存在且非空则跳过。成功返回路径。"""
    if not cover_url or not cover_url.startswith("http"):
        return None
    if dest.is_file() and dest.stat().st_size > 0:
        return dest.resolve()

    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(cover_url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        if len(resp.content) < 200:
            return None
        dest.write_bytes(resp.content)
        return dest.resolve()
    except Exception:
        return None


def download_covers_for_videos(
    videos: list[dict],
    *,
    source: str,
    covers_dir: Path | None = None,
    referer: str = "",
    key_field: str = "code",
) -> tuple[int, int]:
    """批量下载封面，写入每条记录的 cover_path。返回 (成功数, 跳过数)。"""
    root = covers_dir or (DEFAULT_COVERS_ROOT / source)
    root.mkdir(parents=True, exist_ok=True)
    ok = skip = 0

    for v in videos:
        key = v.get(key_field) or v.get("vkey") or v.get("code")
        url = v.get("cover") or v.get("cover_url")
        if not key:
            skip += 1
            continue
        dest = cover_file_path(root, str(key), url or "http://x/x.jpg")
        if dest.is_file() and dest.stat().st_size > 0:
            v["cover_path"] = str(dest.resolve())
            ok += 1
            continue
        if not url or not url.startswith("http"):
            skip += 1
            continue
        path = download_cover(url, dest, referer=referer)
        if path:
            v["cover_path"] = str(path)
            ok += 1
        else:
            skip += 1

    return ok, skip
