"""本地媒体文件访问（供后台预览）。"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services.media_files import guess_media_type, safe_media_path

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/video/{video_id}", summary="视频文件预览")
def serve_video_file(video_id: int, db: Session = Depends(get_db)):
    video = db.get(models.Video, video_id)
    if not video or not video.file_path:
        raise HTTPException(404, "视频不存在")
    path = safe_media_path(video.file_path)
    if not path:
        raise HTTPException(404, "文件不存在或不在允许目录内")
    return FileResponse(path, media_type=guess_media_type(path))
