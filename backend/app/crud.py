"""数据库读写操作，去重逻辑集中在此。"""
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from . import models
from .schemas import VideoIn


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
        for attr in ("title", "cover_url", "cover_path", "video_url", "duration"):
            val = getattr(payload, attr, None)
            if val and getattr(existing, attr) != val:
                setattr(existing, attr, val)
                changed = True
        if payload.cover_path and Path(payload.cover_path).is_file():
            if existing.cover_path != payload.cover_path:
                existing.cover_path = payload.cover_path
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
        cover_path=payload.cover_path,
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
                 download_status: Optional[str] = None,
                 category_id: Optional[int] = None,
                 uncategorized: bool = False,
                 keyword: Optional[str] = None,
                 trash_only: bool = False) -> int:
    from sqlalchemy import func
    stmt = select(func.count()).select_from(models.Video)
    if source:
        stmt = stmt.where(models.Video.source == source)
    if download_status:
        stmt = stmt.where(models.Video.download_status == download_status)
    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(
            models.Video.title.ilike(kw)
            | models.Video.code.ilike(kw)
            | models.Video.source_url.ilike(kw)
        )
    if uncategorized:
        stmt = stmt.where(~models.Video.content_categories.any())
    elif category_id is not None:
        cat = db.get(models.VideoCategory, category_id)
        if cat and not cat.parent_id:
            child_ids = [c.id for c in cat.children]
            if child_ids:
                stmt = stmt.where(models.Video.content_categories.any(
                    models.VideoCategory.id.in_(child_ids)
                ))
            else:
                return 0
        else:
            stmt = stmt.where(models.Video.content_categories.any(
                models.VideoCategory.id == category_id
            ))
    # deleted 标记放在 extra，为兼容 SQLite/MySQL 的 JSON 方言差异，这里用 Python 二次过滤
    if not trash_only:
        if source or download_status or category_id is not None or uncategorized or keyword:
            rows = list_videos(
                db,
                source=source,
                download_status=download_status,
                category_id=category_id,
                uncategorized=uncategorized,
                keyword=keyword,
                trash_only=False,
                limit=1000000,
                offset=0,
            )
            return len(rows)
        rows = list_videos(db, trash_only=False, limit=1000000, offset=0)
        return len(rows)
    rows = list_videos(
        db,
        source=source,
        download_status=download_status,
        category_id=category_id,
        uncategorized=uncategorized,
        keyword=keyword,
        trash_only=True,
        limit=1000000,
        offset=0,
    )
    return len(rows)


def list_videos(db: Session, source: Optional[str] = None,
                download_status: Optional[str] = None,
                category_id: Optional[int] = None,
                uncategorized: bool = False,
                keyword: Optional[str] = None,
                trash_only: bool = False,
                limit: int = 100, offset: int = 0,
                load_categories: bool = False):
    stmt = select(models.Video).order_by(models.Video.created_at.desc())
    if load_categories:
        stmt = stmt.options(joinedload(models.Video.content_categories))
    if source:
        stmt = stmt.where(models.Video.source == source)
    if download_status:
        stmt = stmt.where(models.Video.download_status == download_status)
    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(
            models.Video.title.ilike(kw)
            | models.Video.code.ilike(kw)
            | models.Video.source_url.ilike(kw)
        )
    if uncategorized:
        stmt = stmt.where(~models.Video.content_categories.any())
    elif category_id is not None:
        cat = db.get(models.VideoCategory, category_id)
        if cat and not cat.parent_id:
            child_ids = [c.id for c in cat.children]
            if child_ids:
                stmt = stmt.where(models.Video.content_categories.any(
                    models.VideoCategory.id.in_(child_ids)
                ))
            else:
                stmt = stmt.where(models.Video.id < 0)
        else:
            stmt = stmt.where(models.Video.content_categories.any(
                models.VideoCategory.id == category_id
            ))
    rows = list(db.execute(stmt).scalars().unique().all())
    def _is_deleted(v: models.Video) -> bool:
        return bool((v.extra or {}).get("deleted", False))

    rows = [v for v in rows if (_is_deleted(v) if trash_only else not _is_deleted(v))]
    rows = rows[max(0, offset): max(0, offset) + limit]
    return rows


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


def update_video_cover(db: Session, video_id: int, *,
                       cover_path: Optional[str] = None,
                       cover_clean_path: Optional[str] = None) -> Optional[models.Video]:
    """更新封面图本地路径（原图 / 去水印图）。"""
    video = db.get(models.Video, video_id)
    if not video:
        return None
    if cover_path is not None:
        video.cover_path = cover_path
    if cover_clean_path is not None:
        video.cover_clean_path = cover_clean_path
    db.commit()
    db.refresh(video)
    return video


def soft_delete_videos(db: Session, ids: list[int]) -> int:
    done = 0
    for vid in ids:
        v = db.get(models.Video, vid)
        if not v:
            continue
        extra = dict(v.extra or {})
        extra["deleted"] = True
        extra["deleted_at"] = datetime.utcnow().isoformat()
        v.extra = extra
        done += 1
    db.commit()
    return done


def restore_videos(db: Session, ids: list[int]) -> int:
    done = 0
    for vid in ids:
        v = db.get(models.Video, vid)
        if not v:
            continue
        extra = dict(v.extra or {})
        if extra.get("deleted"):
            extra["deleted"] = False
            extra.pop("deleted_at", None)
            v.extra = extra
            done += 1
    db.commit()
    return done


def purge_videos(db: Session, ids: list[int]) -> int:
    done = 0
    for vid in ids:
        v = db.get(models.Video, vid)
        if not v:
            continue
        db.delete(v)
        done += 1
    db.commit()
    return done


# ---- 视频内容分类 ----

def list_video_categories(db: Session, *, roots_only: bool = False) -> list[models.VideoCategory]:
    stmt = select(models.VideoCategory).order_by(
        models.VideoCategory.sort_order, models.VideoCategory.name,
    )
    if roots_only:
        stmt = stmt.where(models.VideoCategory.parent_id.is_(None))
    return list(db.execute(stmt).scalars().all())


def get_video_category(db: Session, category_id: int) -> Optional[models.VideoCategory]:
    return db.get(models.VideoCategory, category_id)


def get_video_category_by_name(
    db: Session, name: str, parent_id: Optional[int] = None,
) -> Optional[models.VideoCategory]:
    stmt = select(models.VideoCategory).where(models.VideoCategory.name == name)
    if parent_id is None:
        stmt = stmt.where(models.VideoCategory.parent_id.is_(None))
    else:
        stmt = stmt.where(models.VideoCategory.parent_id == parent_id)
    return db.execute(stmt).scalar_one_or_none()


def upsert_video_category(
    db: Session, name: str, *, parent_id: Optional[int] = None, sort_order: int = 0,
) -> tuple[models.VideoCategory, bool]:
    existing = get_video_category_by_name(db, name, parent_id=parent_id)
    if existing:
        existing.sort_order = sort_order
        db.commit()
        db.refresh(existing)
        return existing, False
    cat = models.VideoCategory(name=name, parent_id=parent_id, sort_order=sort_order)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat, True


def create_video_category(
    db: Session, name: str, *, parent_id: Optional[int] = None, sort_order: int = 0,
) -> models.VideoCategory:
    cat = models.VideoCategory(name=name, parent_id=parent_id, sort_order=sort_order)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def update_video_category(db: Session, category: models.VideoCategory, **fields) -> models.VideoCategory:
    for key, value in fields.items():
        if value is not None and hasattr(category, key):
            setattr(category, key, value)
    db.commit()
    db.refresh(category)
    return category


def delete_video_category(db: Session, category: models.VideoCategory) -> None:
    if category.parent_id is None:
        for child in list(category.children):
            for video in list(child.videos):
                if child in video.content_categories:
                    video.content_categories.remove(child)
            db.delete(child)
    else:
        for video in list(category.videos):
            if category in video.content_categories:
                video.content_categories.remove(category)
    db.delete(category)
    db.commit()


def count_videos_in_category(db: Session, category_id: int) -> int:
    cat = db.get(models.VideoCategory, category_id)
    if not cat:
        return 0
    if cat.parent_id is None:
        child_ids = [c.id for c in cat.children]
        if not child_ids:
            return 0
        return db.execute(
            select(func.count(func.distinct(models.Video.id)))
            .select_from(models.Video)
            .join(models.Video.content_categories)
            .where(models.VideoCategory.id.in_(child_ids))
        ).scalar_one()
    return db.execute(
        select(func.count()).select_from(models.Video)
        .where(models.Video.content_categories.any(models.VideoCategory.id == category_id))
    ).scalar_one()


def count_uncategorized_videos(db: Session) -> int:
    return db.execute(
        select(func.count()).select_from(models.Video)
        .where(~models.Video.content_categories.any())
    ).scalar_one()


def set_video_categories(db: Session, video_id: int, category_ids: list[int]) -> Optional[models.Video]:
    video = db.get(models.Video, video_id)
    if not video:
        return None
    cats = []
    for cid in category_ids:
        cat = db.get(models.VideoCategory, cid)
        if cat and cat.parent_id is not None:
            cats.append(cat)
    video.content_categories = cats
    db.commit()
    db.refresh(video)
    return video


def add_video_to_category(db: Session, video_id: int, category_id: int) -> Optional[models.Video]:
    video = db.get(models.Video, video_id)
    cat = db.get(models.VideoCategory, category_id)
    if not video or not cat or cat.parent_id is None:
        return None
    if cat not in video.content_categories:
        video.content_categories.append(cat)
        db.commit()
        db.refresh(video)
    return video


def remove_video_from_category(db: Session, video_id: int, category_id: int) -> Optional[models.Video]:
    video = db.get(models.Video, video_id)
    cat = db.get(models.VideoCategory, category_id)
    if not video or not cat:
        return None
    if cat in video.content_categories:
        video.content_categories.remove(cat)
        db.commit()
        db.refresh(video)
    return video


