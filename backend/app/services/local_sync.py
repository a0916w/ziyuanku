"""扫描本地 data/ 目录，把已下载媒体和爬虫脚本同步进数据库。"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from .. import crud, models
from ..config import BASE_DIR
from ..schemas import ResourceIn, VideoIn

log = logging.getLogger(__name__)

REPO_ROOT = BASE_DIR.parent
DATA_DIR = REPO_ROOT / "data"
METADATA_DIR = DATA_DIR / "metadata"

MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov"}
VIDEO_EXTS = {".mp4", ".mov"}

# 帖子多图：20240827_062456_C_KchXIPv3-_3.mp4；单图/Stories/Highlights：20260310_123631_DVtEH0igDPl.jpg
IG_FILE_RE = re.compile(
    r"^(\d{8}_\d{6})_(.+?)(?:_(\d+))?\.(jpg|jpeg|png|webp|mp4|mov)$",
    re.I,
)
MISSAV_CODE_RE = re.compile(r"^([A-Z0-9]+-[A-Z0-9]+)", re.I)

from .script_registry import sync_registered_scripts


def _media_type(path: Path) -> str:
    return "video" if path.suffix.lower() in VIDEO_EXTS else "image"


def _parse_ig_account(dir_name: str) -> tuple[str, str]:
    """vitagennn_highlights → (vitagennn, highlight)"""
    if dir_name.endswith("_highlights"):
        return dir_name[: -len("_highlights")], "highlight"
    if dir_name.endswith("_stories"):
        return dir_name[: -len("_stories")], "story"
    return dir_name, "post"


def _parse_ig_file(path: Path, account: str, kind: str, highlight: Optional[str]) -> ResourceIn | None:
    m = IG_FILE_RE.match(path.name)
    if not m:
        return None
    shortcode = m.group(2).rstrip("-_")
    source_url = f"https://www.instagram.com/p/{shortcode}/"
    extra = {"kind": kind}
    if highlight:
        extra["highlight"] = highlight
    return ResourceIn(
        file_path=str(path.resolve()),
        media_type=_media_type(path),
        source_account=account,
        source_url=source_url,
        caption=path.stem,
        extra=extra,
    )


def sync_instagram(db: Session, root: Path = DATA_DIR / "instagram") -> dict:
    created = duplicated = skipped = 0
    if not root.is_dir():
        return {"created": 0, "duplicated": 0, "skipped": 0}

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in MEDIA_EXTS:
            continue
        if path.stat().st_size == 0:
            skipped += 1
            continue

        rel = path.relative_to(root)
        account_dir = rel.parts[0] if rel.parts else ""
        account, kind = _parse_ig_account(account_dir)
        highlight = rel.parts[1] if kind == "highlight" and len(rel.parts) > 2 else None

        payload = _parse_ig_file(path, account, kind, highlight)
        if not payload:
            skipped += 1
            continue

        _, is_new = crud.ingest_resource(db, payload)
        created += int(is_new)
        duplicated += int(not is_new)

    return {"created": created, "duplicated": duplicated, "skipped": skipped}


def _load_json_index(path: Path, key: str) -> dict:
    if not path.is_file():
        return {}
    items = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for item in items:
        k = item.get(key)
        if k:
            out[str(k).upper() if key == "code" else str(k)] = item
    return out


def _match_missav_file(path: Path, index: dict) -> Optional[dict]:
    m = MISSAV_CODE_RE.match(path.name)
    if not m:
        return None
    return index.get(m.group(1).upper())


def _match_pornhub_file(path: Path, index: dict) -> Optional[dict]:
    vkey = path.stem.split(" ", 1)[0]
    return index.get(vkey)


def sync_site_videos(
    db: Session,
    *,
    files_root: Path,
    metadata_json: Path,
    match_fn,
    source: str,
    code_key: str = "code",
) -> dict:
    created = duplicated = skipped = 0
    if not files_root.is_dir():
        return {"created": 0, "duplicated": 0, "skipped": 0}

    index = _load_json_index(metadata_json, code_key if source == "missav" else "vkey")

    for path in sorted(files_root.rglob("*.mp4")):
        if path.stat().st_size == 0:
            skipped += 1
            continue

        meta = match_fn(path, index)
        if meta:
            title = meta.get("title", path.stem)
            source_url = meta.get("url", "")
            cover = meta.get("cover")
            cover_path = meta.get("cover_path")
            duration = meta.get("duration")
            code = meta.get(code_key) or meta.get("vkey")
        else:
            title = path.stem
            source_url = f"file://{path.resolve()}"
            cover = duration = cover_path = None
            code = path.stem.split(" ", 1)[0] if source == "pornhub" else None

        if not cover_path and code:
            covers_dir = DATA_DIR / "covers" / source
            if covers_dir.is_dir():
                for ext in (".jpg", ".jpeg", ".png", ".webp"):
                    p = covers_dir / f"{code}{ext}"
                    if p.is_file():
                        cover_path = str(p.resolve())
                        break

        payload = VideoIn(
            title=title,
            code=code,
            source_url=source_url,
            cover=cover,
            cover_path=cover_path,
            duration=duration or None,
            file_path=str(path.resolve()),
            download_status=models.DL_DONE,
            source=source,
        )
        try:
            _, is_new = crud.ingest_video(db, payload)
            created += int(is_new)
            duplicated += int(not is_new)
        except Exception as e:
            log.warning("视频入库跳过 %s: %s", path, e)
            skipped += 1

    return {"created": created, "duplicated": duplicated, "skipped": skipped}


def sync_missav(db: Session) -> dict:
    return sync_site_videos(
        db,
        files_root=DATA_DIR / "missav",
        metadata_json=METADATA_DIR / "twav_videos.json",
        match_fn=_match_missav_file,
        source="missav",
        code_key="code",
    )


def sync_pornhub(db: Session) -> dict:
    return sync_site_videos(
        db,
        files_root=DATA_DIR / "pornhub",
        metadata_json=METADATA_DIR / "sweetie_fox_videos.json",
        match_fn=_match_pornhub_file,
        source="pornhub",
        code_key="vkey",
    )


def sync_scripts(db: Session) -> dict:
    return sync_registered_scripts(db)


def run_all(db: Session) -> dict:
    """执行全量同步，返回各模块统计。"""
    return {
        "scripts": sync_scripts(db),
        "missav": sync_missav(db),
        "pornhub": sync_pornhub(db),
    }
