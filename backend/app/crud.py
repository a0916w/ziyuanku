"""数据库读写操作，去重逻辑集中在此。"""
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from . import models
from .schemas import ResourceIn, VideoIn


def compute_file_hash(path: str, chunk: int = 1 << 20) -> str:
    """按文件内容算 SHA-256，作为去重键。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def get_resource_by_hash(db: Session, file_hash: str) -> Optional[models.Resource]:
    return db.execute(
        select(models.Resource).where(models.Resource.file_hash == file_hash)
    ).scalar_one_or_none()


def ingest_resource(db: Session, payload: ResourceIn) -> tuple[Optional[models.Resource], bool]:
    """入库单条资源。

    返回 (resource, created)。created=False 表示命中去重、已存在。
    去重依据：文件内容哈希（同一文件算重复）。
    """
    file_hash = payload.file_hash
    if not file_hash:
        # 未提供哈希则由服务端按文件内容计算
        file_hash = compute_file_hash(payload.file_path)

    existing = get_resource_by_hash(db, file_hash)
    if existing:
        return existing, False

    res = models.Resource(
        file_hash=file_hash,
        file_path=payload.file_path,
        media_type=payload.media_type,
        source_account=payload.source_account,
        source_url=payload.source_url,
        caption=payload.caption,
        extra=payload.extra,
        status=models.STATUS_PENDING,
    )
    db.add(res)
    db.commit()
    db.refresh(res)
    return res, True


def count_resources(db: Session, status: Optional[str] = None,
                    account: Optional[str] = None) -> int:
    from sqlalchemy import func
    stmt = select(func.count()).select_from(models.Resource)
    if status:
        stmt = stmt.where(models.Resource.status == status)
    if account:
        stmt = stmt.where(models.Resource.source_account == account)
    return db.execute(stmt).scalar_one()


def list_resources(db: Session, status: Optional[str] = None,
                   account: Optional[str] = None, limit: int = 500):
    stmt = select(models.Resource).order_by(models.Resource.created_at.desc())
    if status:
        stmt = stmt.where(models.Resource.status == status)
    if account:
        stmt = stmt.where(models.Resource.source_account == account)
    stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars().all())


def counts_by_status(db: Session) -> dict[str, int]:
    out = {s: 0 for s in models.STATUS_ORDER}
    for res in db.execute(select(models.Resource.status)).scalars().all():
        out[res] = out.get(res, 0) + 1
    return out


# ---- 视频库 ----

def _resolve_download_status(file_path: Optional[str], status: Optional[str] = None) -> str:
    if status in models.DL_STATUS_ORDER:
        return status
    if file_path and Path(file_path).is_file():
        return models.DL_DONE
    return models.DL_PENDING


def get_video_by_code(db: Session, code: str) -> Optional[models.Video]:
    if not code:
        return None
    return db.execute(
        select(models.Video).where(models.Video.code == code)
    ).scalar_one_or_none()


def get_video_by_source_url(db: Session, source_url: str) -> Optional[models.Video]:
    return db.execute(
        select(models.Video).where(models.Video.source_url == source_url)
    ).scalar_one_or_none()


def ingest_video(db: Session, payload: VideoIn) -> tuple[models.Video, bool]:
    """入库单条视频。返回 (video, created)。去重：code 优先，否则 source_url。"""
    existing = None
    if payload.code:
        existing = get_video_by_code(db, payload.code)
    if not existing:
        existing = get_video_by_source_url(db, payload.source_url)
    if existing:
        changed = False
        if payload.file_path and Path(payload.file_path).is_file():
            if existing.file_path != payload.file_path:
                existing.file_path = payload.file_path
                changed = True
            if existing.download_status != models.DL_DONE:
                existing.download_status = models.DL_DONE
                existing.download_progress = 100
                existing.downloaded_at = datetime.utcnow()
                existing.download_error = None
                changed = True
        for attr in ("title", "cover_url", "video_url", "duration"):
            val = getattr(payload, attr, None)
            if val and getattr(existing, attr) != val:
                setattr(existing, attr, val)
                changed = True
        if changed:
            db.commit()
            db.refresh(existing)
        return existing, False

    dl_status = _resolve_download_status(payload.file_path, payload.download_status)
    dl_progress = 100 if dl_status == models.DL_DONE else 0
    video = models.Video(
        code=payload.code,
        title=payload.title,
        cover_url=payload.cover_url,
        source_url=payload.source_url,
        duration=payload.duration,
        video_url=payload.video_url,
        file_path=payload.file_path,
        download_status=dl_status,
        download_progress=dl_progress,
        downloaded_at=datetime.utcnow() if dl_status == models.DL_DONE else None,
        source=payload.source,
        extra=payload.extra,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video, True


def count_videos(db: Session, source: Optional[str] = None,
                 download_status: Optional[str] = None) -> int:
    from sqlalchemy import func
    stmt = select(func.count()).select_from(models.Video)
    if source:
        stmt = stmt.where(models.Video.source == source)
    if download_status:
        stmt = stmt.where(models.Video.download_status == download_status)
    return db.execute(stmt).scalar_one()


def list_videos(db: Session, source: Optional[str] = None,
                download_status: Optional[str] = None, limit: int = 200):
    stmt = select(models.Video).order_by(models.Video.created_at.desc())
    if source:
        stmt = stmt.where(models.Video.source == source)
    if download_status:
        stmt = stmt.where(models.Video.download_status == download_status)
    stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars().all())


def counts_video_download(db: Session) -> dict[str, int]:
    out = {s: 0 for s in models.DL_STATUS_ORDER}
    for status in db.execute(select(models.Video.download_status)).scalars().all():
        out[status] = out.get(status, 0) + 1
    return out


def update_video_download(db: Session, video_id: int, *,
                          download_status: str,
                          download_progress: Optional[int] = None,
                          file_path: Optional[str] = None,
                          video_url: Optional[str] = None,
                          download_error: Optional[str] = None) -> Optional[models.Video]:
    video = db.get(models.Video, video_id)
    if not video:
        return None
    video.download_status = download_status
    if file_path is not None:
        video.file_path = file_path
    if video_url is not None:
        video.video_url = video_url
    video.download_error = download_error
    if download_progress is not None:
        video.download_progress = max(0, min(100, download_progress))
    elif download_status == models.DL_DONE:
        video.download_progress = 100
    elif download_status == models.DL_PENDING:
        video.download_progress = 0
    if download_status == models.DL_DONE:
        video.downloaded_at = datetime.utcnow()
        video.download_error = None
    db.commit()
    db.refresh(video)
    return video


def list_recent_runs(db: Session, limit: int = 30) -> list[models.CrawlRun]:
    stmt = (
        select(models.CrawlRun)
        .options(joinedload(models.CrawlRun.script))
        .order_by(models.CrawlRun.started_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().unique().all())


def has_running_scripts(db: Session) -> bool:
    row = db.execute(
        select(models.CrawlRun.id)
        .where(models.CrawlRun.status == models.RUN_RUNNING)
        .limit(1)
    ).scalar_one_or_none()
    return row is not None


# ---- 爬虫脚本 ----

def list_scripts(db: Session):
    stmt = (
        select(models.CrawlScript)
        .options(joinedload(models.CrawlScript.runs))
        .order_by(models.CrawlScript.created_at.desc())
    )
    return list(db.execute(stmt).scalars().unique().all())


def get_script(db: Session, script_id: int) -> Optional[models.CrawlScript]:
    stmt = (
        select(models.CrawlScript)
        .options(joinedload(models.CrawlScript.runs))
        .where(models.CrawlScript.id == script_id)
    )
    return db.execute(stmt).scalars().unique().one_or_none()


def get_script_by_name(db: Session, name: str) -> Optional[models.CrawlScript]:
    return db.execute(
        select(models.CrawlScript).where(models.CrawlScript.name == name)
    ).scalar_one_or_none()


def create_script(db: Session, name: str, command: str,
                  description: str = None, enabled: bool = True) -> models.CrawlScript:
    s = models.CrawlScript(name=name, command=command,
                           description=description, enabled=enabled)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def upsert_script(db: Session, name: str, command: str,
                  description: str = None, enabled: bool = True) -> tuple[models.CrawlScript, bool]:
    """按名称登记脚本。返回 (script, created)。"""
    existing = get_script_by_name(db, name)
    if existing:
        existing.command = command
        existing.description = description
        existing.enabled = enabled
        db.commit()
        db.refresh(existing)
        return existing, False
    return create_script(db, name, command, description, enabled), True


def update_script(db: Session, script: models.CrawlScript, **fields) -> models.CrawlScript:
    for key, value in fields.items():
        if value is not None and hasattr(script, key):
            setattr(script, key, value)
    db.commit()
    db.refresh(script)
    return script


def delete_script(db: Session, script: models.CrawlScript) -> None:
    db.delete(script)
    db.commit()


def script_is_running(db: Session, script_id: int) -> bool:
    row = db.execute(
        select(models.CrawlRun.id)
        .where(
            models.CrawlRun.script_id == script_id,
            models.CrawlRun.status == models.RUN_RUNNING,
        )
        .limit(1)
    ).scalar_one_or_none()
    return row is not None
