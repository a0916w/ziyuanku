"""视频库 API：入库、列表、去水印。"""
from datetime import datetime
import csv
import io
from pathlib import Path
from threading import Lock, Thread
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import crud, models
from ..database import get_db, SessionLocal
from ..schemas import VideoIn, VideoOut, VideoIngestResult, VideoDownloadUpdate
from ..services.cover_gen import generate_cover_from_video
from ..services.video_display import download_progress_display
from ..services.watermark import process_cover
from .. import config as _cfg

router = APIRouter(prefix="/api/videos", tags=["videos"])

_WM_JOB_LOCK = Lock()
_WM_JOB_STATE = {
    "running": False,
    "total": 0,
    "processed": 0,
    "failed": 0,
    "started_at": None,
    "finished_at": None,
    "message": "",
}

_COVER_JOB_LOCK = Lock()
_COVER_JOB_STATE = {
    "running": False,
    "total": 0,
    "processed": 0,
    "failed": 0,
    "started_at": None,
    "finished_at": None,
    "message": "",
}


def _wm_set_state(**kwargs):
    with _WM_JOB_LOCK:
        _WM_JOB_STATE.update(kwargs)


def _cover_set_state(**kwargs):
    with _COVER_JOB_LOCK:
        _COVER_JOB_STATE.update(kwargs)


def _to_out(v: models.Video) -> VideoOut:
    return VideoOut(
        id=v.id, code=v.code, title=v.title, cover_url=v.cover_url,
        cover_path=v.cover_path, cover_clean_path=v.cover_clean_path,
        source_url=v.source_url, duration=v.duration, video_url=v.video_url,
        file_path=v.file_path, source=v.source, extra=v.extra,
        download_status=v.download_status or models.DL_PENDING,
        download_status_label=models.DL_STATUS_LABELS.get(
            v.download_status or models.DL_PENDING, v.download_status or ""),
        download_progress=download_progress_display(v)["progress"],
        download_error=v.download_error, downloaded_at=v.downloaded_at,
        created_at=v.created_at, updated_at=v.updated_at,
    )


@router.post("", response_model=VideoIngestResult, summary="视频入库（单条或批量）")
def ingest(payload: VideoIn | list[VideoIn], db: Session = Depends(get_db)):
    """爬虫抓完后调用。按 code 或 source_url 去重，已存在则跳过。"""
    items = payload if isinstance(payload, list) else [payload]
    created, dup, ids = 0, 0, []
    for item in items:
        video, is_new = crud.ingest_video(db, item)
        ids.append(video.id)
        created += int(is_new)
        dup += int(not is_new)
    return VideoIngestResult(created=created, duplicated=dup, ids=ids)


@router.get("/stats", summary="视频下载状态统计")
def video_stats(db: Session = Depends(get_db)):
    counts = crud.counts_video_download(db)
    return {
        "counts": counts,
        "labels": models.DL_STATUS_LABELS,
        "order": models.DL_STATUS_ORDER,
    }


@router.get("", response_model=list[VideoOut], summary="视频列表")
def list_videos(source: str | None = None, download_status: str | None = None,
                category_id: int | None = None, uncategorized: bool = False,
                keyword: str | None = None,
                trash_only: bool = False,
                limit: int = 200, db: Session = Depends(get_db)):
    rows = crud.list_videos(
        db, source=source, download_status=download_status,
        category_id=category_id, uncategorized=uncategorized, keyword=keyword,
        trash_only=trash_only, limit=limit,
    )
    return [_to_out(v) for v in rows]


@router.patch("/{video_id}/download", response_model=VideoOut, summary="更新下载状态")
def update_download(video_id: int, payload: VideoDownloadUpdate,
                    db: Session = Depends(get_db)):
    video = crud.update_video_download(
        db, video_id,
        download_status=payload.download_status,
        download_progress=payload.download_progress,
        file_path=payload.file_path,
        video_url=payload.video_url,
        download_error=payload.download_error,
    )
    if not video:
        raise HTTPException(404, "视频不存在")
    return _to_out(video)


@router.get("/download-status", summary="下载进度（供列表轮询）")
def download_status(db: Session = Depends(get_db)):
    rows = crud.list_videos(db, limit=500)
    return [
        {
            "id": v.id,
            "download_status": v.download_status or models.DL_PENDING,
            **download_progress_display(v),
        }
        for v in rows
    ]


@router.get("/{video_id}", response_model=VideoOut, summary="视频详情")
def get_video(video_id: int, db: Session = Depends(get_db)):
    video = db.get(models.Video, video_id)
    if not video:
        raise HTTPException(404, "视频不存在")
    return _to_out(video)


class WatermarkRemoveIn(BaseModel):
    """去水印请求体。regions 为空时使用来源预设。"""
    regions: Optional[list[tuple[float, float, float, float]]] = None
    force: bool = False  # True = 即使已处理也重新执行


class VideoUpdateIn(BaseModel):
    title: Optional[str] = None
    code: Optional[str] = None
    source_url: Optional[str] = None
    cover_url: Optional[str] = None
    duration: Optional[str] = None
    source: Optional[str] = None
    note: Optional[str] = None
    tags: Optional[list[str]] = None
    category_ids: Optional[list[int]] = None


class VideoBatchIdsIn(BaseModel):
    ids: list[int]


class VideoBatchStatusIn(BaseModel):
    ids: list[int]
    download_status: str


class VideoBatchCategoryIn(BaseModel):
    ids: list[int]
    category_ids: list[int]


@router.post("/{video_id}/remove-watermark", response_model=VideoOut,
             summary="下载封面并去除水印")
def remove_watermark(video_id: int, payload: WatermarkRemoveIn = WatermarkRemoveIn(),
                     db: Session = Depends(get_db)):
    """
    下载视频封面图，用 OpenCV inpainting 去除水印，保存到本地。
    - 首次调用：下载原图 + 生成去水印图，写入 cover_path / cover_clean_path。
    - 重复调用：直接返回已有结果（除非传 force=true）。
    """
    video = db.get(models.Video, video_id)
    if not video:
        raise HTTPException(404, "视频不存在")

    if not video.cover_url:
        raise HTTPException(400, "该视频没有 cover_url，无法处理封面")

    # 已处理且不强制重跑 → 直接返回
    if not payload.force and video.cover_clean_path and Path(video.cover_clean_path).exists():
        return _to_out(video)

    covers_dir = _cfg.DATA_DIR / "covers"
    orig_path, clean_path = process_cover(
        cover_url=video.cover_url,
        source=video.source or "default",
        covers_dir=covers_dir,
        video_id=video_id,
        custom_regions=payload.regions,
    )

    if not clean_path:
        raise HTTPException(500, "去水印处理失败，请检查日志")

    video = crud.update_video_cover(
        db, video_id,
        cover_path=orig_path,
        cover_clean_path=clean_path,
    )
    return _to_out(video)


@router.patch("/{video_id}", response_model=VideoOut, summary="编辑视频信息")
def update_video(video_id: int, payload: VideoUpdateIn, db: Session = Depends(get_db)):
    video = db.get(models.Video, video_id)
    if not video:
        raise HTTPException(404, "视频不存在")

    for field in ("title", "code", "source_url", "cover_url", "duration", "source"):
        val = getattr(payload, field)
        if val is not None:
            setattr(video, field, val)

    extra = dict(video.extra or {})
    if payload.note is not None:
        extra["note"] = payload.note
    if payload.tags is not None:
        extra["tags"] = [t.strip() for t in payload.tags if t and t.strip()]
    if payload.note is not None or payload.tags is not None:
        video.extra = extra

    db.commit()
    if payload.category_ids is not None:
        crud.set_video_categories(db, video_id, payload.category_ids)
    db.refresh(video)
    return _to_out(video)


@router.post("/batch/update-status", summary="批量更新下载状态")
def batch_update_status(payload: VideoBatchStatusIn, db: Session = Depends(get_db)):
    if not payload.ids:
        raise HTTPException(400, "ids 不能为空")
    done = 0
    for vid in payload.ids:
        v = crud.update_video_download(db, vid, download_status=payload.download_status)
        if v:
            done += 1
    return {"updated": done, "total": len(payload.ids)}


@router.post("/batch/update-categories", summary="批量更新分类")
def batch_update_categories(payload: VideoBatchCategoryIn, db: Session = Depends(get_db)):
    if not payload.ids:
        raise HTTPException(400, "ids 不能为空")
    done = 0
    for vid in payload.ids:
        v = crud.set_video_categories(db, vid, payload.category_ids)
        if v:
            done += 1
    return {"updated": done, "total": len(payload.ids)}


@router.post("/batch/delete", summary="批量删除视频")
def batch_delete(payload: VideoBatchIdsIn, db: Session = Depends(get_db)):
    if not payload.ids:
        raise HTTPException(400, "ids 不能为空")
    done = crud.soft_delete_videos(db, payload.ids)
    return {"deleted": done, "total": len(payload.ids)}


@router.post("/batch/restore", summary="回收站批量恢复")
def batch_restore(payload: VideoBatchIdsIn, db: Session = Depends(get_db)):
    if not payload.ids:
        raise HTTPException(400, "ids 不能为空")
    done = crud.restore_videos(db, payload.ids)
    return {"restored": done, "total": len(payload.ids)}


@router.post("/batch/purge", summary="回收站批量彻底删除")
def batch_purge(payload: VideoBatchIdsIn, db: Session = Depends(get_db)):
    if not payload.ids:
        raise HTTPException(400, "ids 不能为空")
    done = crud.purge_videos(db, payload.ids)
    return {"purged": done, "total": len(payload.ids)}


@router.post("/batch/export", summary="批量导出 CSV")
def batch_export(payload: VideoBatchIdsIn, db: Session = Depends(get_db)):
    if not payload.ids:
        raise HTTPException(400, "ids 不能为空")
    rows = db.query(models.Video).filter(models.Video.id.in_(payload.ids)).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "code", "title", "source", "source_url", "duration", "file_path", "download_status"])
    for v in rows:
        w.writerow([
            v.id, v.code or "", v.title or "", v.source or "", v.source_url or "",
            v.duration or "", v.file_path or "", v.download_status or "",
        ])
    out = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    return StreamingResponse(
        out,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=videos_export.csv"},
    )


def _run_batch_remove_watermark():
    from sqlalchemy import or_, select

    db = SessionLocal()
    try:
        rows = db.execute(
            select(models.Video).where(
                models.Video.cover_url.isnot(None),
                or_(
                    models.Video.cover_clean_path.is_(None),
                    models.Video.cover_clean_path == "",
                )
            )
        ).scalars().all()
        covers_dir = _cfg.DATA_DIR / "covers"
        _wm_set_state(
            running=True,
            total=len(rows),
            processed=0,
            failed=0,
            started_at=datetime.utcnow().isoformat(),
            finished_at=None,
            message="处理中",
        )

        processed, failed = 0, 0
        for video in rows:
            orig_path, clean_path = process_cover(
                cover_url=video.cover_url,
                source=video.source or "default",
                covers_dir=covers_dir,
                video_id=video.id,
            )
            if clean_path:
                crud.update_video_cover(
                    db, video.id, cover_path=orig_path, cover_clean_path=clean_path
                )
                processed += 1
            else:
                failed += 1
            _wm_set_state(processed=processed, failed=failed)

        _wm_set_state(
            running=False,
            finished_at=datetime.utcnow().isoformat(),
            message="完成",
        )
    except Exception as e:  # noqa: BLE001
        _wm_set_state(
            running=False,
            finished_at=datetime.utcnow().isoformat(),
            message=f"失败: {e}",
        )
    finally:
        db.close()


@router.post("/batch-remove-watermark", summary="批量去水印（后台队列执行）")
def batch_remove_watermark():
    """异步启动批量去水印任务。"""
    with _WM_JOB_LOCK:
        if _WM_JOB_STATE["running"]:
            return {"ok": False, "detail": "已有任务在运行", **_WM_JOB_STATE}
        _WM_JOB_STATE.update(
            {
                "running": True,
                "total": 0,
                "processed": 0,
                "failed": 0,
                "started_at": datetime.utcnow().isoformat(),
                "finished_at": None,
                "message": "已启动",
            }
        )
    Thread(target=_run_batch_remove_watermark, daemon=True).start()
    return {"ok": True, **_WM_JOB_STATE}


@router.get("/batch-remove-watermark/status", summary="批量去水印任务状态")
def batch_remove_watermark_status():
    with _WM_JOB_LOCK:
        return dict(_WM_JOB_STATE)


@router.post("/{video_id}/generate-cover", response_model=VideoOut, summary="从本地视频生成封面")
def generate_cover(video_id: int, db: Session = Depends(get_db)):
    video = db.get(models.Video, video_id)
    if not video:
        raise HTTPException(404, "视频不存在")
    if not video.file_path:
        raise HTTPException(400, "该视频没有本地文件路径，无法生成封面")

    covers_dir = _cfg.DATA_DIR / "covers"
    cover_path = generate_cover_from_video(video.file_path, covers_dir, video.id)
    if not cover_path:
        raise HTTPException(500, "封面生成失败")

    video = crud.update_video_cover(db, video.id, cover_path=cover_path)
    return _to_out(video)


def _run_batch_generate_cover():
    from sqlalchemy import or_, select

    db = SessionLocal()
    try:
        rows = db.execute(
            select(models.Video).where(
                models.Video.file_path.isnot(None),
                or_(
                    models.Video.cover_path.is_(None),
                    models.Video.cover_path == "",
                ),
            )
        ).scalars().all()
        covers_dir = _cfg.DATA_DIR / "covers"
        _cover_set_state(
            running=True,
            total=len(rows),
            processed=0,
            failed=0,
            started_at=datetime.utcnow().isoformat(),
            finished_at=None,
            message="处理中",
        )
        processed, failed = 0, 0
        for video in rows:
            path = generate_cover_from_video(video.file_path, covers_dir, video.id)
            if path:
                crud.update_video_cover(db, video.id, cover_path=path)
                processed += 1
            else:
                failed += 1
            _cover_set_state(processed=processed, failed=failed)
        _cover_set_state(
            running=False,
            finished_at=datetime.utcnow().isoformat(),
            message="完成",
        )
    except Exception as e:  # noqa: BLE001
        _cover_set_state(
            running=False,
            finished_at=datetime.utcnow().isoformat(),
            message=f"失败: {e}",
        )
    finally:
        db.close()


@router.post("/batch-generate-cover", summary="批量补封面（仅无 cover_path 的视频）")
def batch_generate_cover():
    with _COVER_JOB_LOCK:
        if _COVER_JOB_STATE["running"]:
            return {"ok": False, "detail": "已有任务在运行", **_COVER_JOB_STATE}
        _COVER_JOB_STATE.update(
            {
                "running": True,
                "total": 0,
                "processed": 0,
                "failed": 0,
                "started_at": datetime.utcnow().isoformat(),
                "finished_at": None,
                "message": "已启动",
            }
        )
    Thread(target=_run_batch_generate_cover, daemon=True).start()
    return {"ok": True, **_COVER_JOB_STATE}


@router.get("/batch-generate-cover/status", summary="批量补封面任务状态")
def batch_generate_cover_status():
    with _COVER_JOB_LOCK:
        return dict(_COVER_JOB_STATE)
