"""数据库读写操作，去重逻辑集中在此。"""
import hashlib
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .schemas import ResourceIn


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


def list_resources(db: Session, status: Optional[str] = None,
                   account: Optional[str] = None, limit: int = 200):
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


# ---- 爬虫脚本 ----

def list_scripts(db: Session):
    return list(db.execute(
        select(models.CrawlScript).order_by(models.CrawlScript.created_at.desc())
    ).scalars().all())


def get_script(db: Session, script_id: int) -> Optional[models.CrawlScript]:
    return db.get(models.CrawlScript, script_id)


def create_script(db: Session, name: str, command: str,
                  description: str = None, enabled: bool = True) -> models.CrawlScript:
    s = models.CrawlScript(name=name, command=command,
                           description=description, enabled=enabled)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s
