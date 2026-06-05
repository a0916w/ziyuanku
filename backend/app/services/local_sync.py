"""扫描本地 data/ 目录，把已下载媒体同步进数据库。"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from .. import crud, models
from ..config import BASE_DIR
from ..schemas import VideoIn

log = logging.getLogger(__name__)

REPO_ROOT = BASE_DIR.parent
DATA_DIR = REPO_ROOT / "data"
METADATA_DIR = DATA_DIR / "metadata"

MISSAV_CODE_RE = re.compile(r"^([A-Z0-9]+-[A-Z0-9]+)", re.I)


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


def run_all(db: Session) -> dict:
    """执行全量同步，返回各模块统计。"""
    return {
        "missav": sync_missav(db),
        "pornhub": sync_pornhub(db),
    }
