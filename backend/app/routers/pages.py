"""后台页面（服务端渲染）。"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from pathlib import Path

from .. import crud, models
from ..database import get_db
from ..services.media_files import public_media_url, safe_media_path
from ..services.video_display import download_progress_display

router = APIRouter(tags=["pages"])
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse, summary="首页/概览")
def dashboard(request: Request, db: Session = Depends(get_db)):
    dl_counts = crud.counts_video_download(db)
    scripts = crud.list_scripts(db)
    recent_runs = crud.list_recent_runs(db, limit=8)
    return TEMPLATES.TemplateResponse(request, "dashboard.html", {
        "scripts": scripts,
        "dl_counts": dl_counts, "dl_labels": models.DL_STATUS_LABELS,
        "dl_order": models.DL_STATUS_ORDER,
        "run_labels": models.RUN_STATUS_LABELS,
        "recent_runs": recent_runs,
        "has_running": crud.has_running_scripts(db),
        "active": "dashboard",
    })


def _video_items(rows: list[models.Video]) -> list[dict]:
    items = []
    for v in rows:
        file_url = public_media_url(v.file_path) if v.file_path else None
        has_file = safe_media_path(v.file_path) is not None
        cover = v.cover_url or (file_url if has_file else None)
        prog = download_progress_display(v)
        items.append({
            "v": v,
            "cover_url": cover,
            "play_url": file_url or f"/api/media/video/{v.id}",
            "has_file": has_file,
            "progress": prog["progress"],
            "indeterminate": prog["indeterminate"],
            "status_label": prog["status_label"],
        })
    return items


@router.get("/resources", response_class=HTMLResponse, summary="资源库（视频）")
def resources_page(request: Request, download_status: str | None = None,
                   source: str | None = None, db: Session = Depends(get_db)):
    rows = crud.list_videos(db, source=source, download_status=download_status, limit=500)
    dl_counts = crud.counts_video_download(db)
    total = crud.count_videos(db, source=source, download_status=download_status)
    return TEMPLATES.TemplateResponse(request, "resources.html", {
        "items": _video_items(rows),
        "total": total,
        "dl_counts": dl_counts,
        "dl_labels": models.DL_STATUS_LABELS,
        "dl_order": models.DL_STATUS_ORDER,
        "current_dl_status": download_status,
        "has_running": crud.has_running_scripts(db),
        "poll_downloads": dl_counts.get(models.DL_DOWNLOADING, 0) > 0,
        "active": "resources",
    })


@router.get("/videos", include_in_schema=False)
def videos_redirect(download_status: str | None = None, source: str | None = None):
    q = []
    if download_status:
        q.append(f"download_status={download_status}")
    if source:
        q.append(f"source={source}")
    url = "/resources" + (f"?{'&'.join(q)}" if q else "")
    return RedirectResponse(url, status_code=301)


@router.get("/scripts", response_class=HTMLResponse, summary="爬虫脚本管理页")
def scripts_page(request: Request, db: Session = Depends(get_db)):
    scripts = crud.list_scripts(db)
    recent_runs = crud.list_recent_runs(db, limit=40)
    return TEMPLATES.TemplateResponse(request, "scripts.html", {
        "scripts": scripts, "recent_runs": recent_runs,
        "run_labels": models.RUN_STATUS_LABELS,
        "has_running": crud.has_running_scripts(db),
        "active": "scripts",
    })


