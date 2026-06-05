"""视频库 API：入库、列表。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, models
from ..database import get_db
from ..schemas import VideoIn, VideoOut, VideoIngestResult, VideoDownloadUpdate
from ..services.video_display import download_progress_display

router = APIRouter(prefix="/api/videos", tags=["videos"])


def _to_out(v: models.Video) -> VideoOut:
    return VideoOut(
        id=v.id, code=v.code, title=v.title, cover_url=v.cover_url,
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
                limit: int = 200, db: Session = Depends(get_db)):
    rows = crud.list_videos(db, source=source, download_status=download_status, limit=limit)
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
