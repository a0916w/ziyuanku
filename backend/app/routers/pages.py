"""后台页面（服务端渲染）。"""
from math import ceil
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from pathlib import Path

PAGE_SIZE = 100

from .. import crud, models
from ..database import get_db
from ..services.media_files import public_media_url, safe_media_path
from ..services.video_display import download_progress_display

router = APIRouter(tags=["pages"])
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse, summary="首页/概览")
def dashboard(request: Request, db: Session = Depends(get_db)):
    dl_counts = crud.counts_video_download(db)
    return TEMPLATES.TemplateResponse(request, "dashboard.html", {
        "dl_counts": dl_counts, "dl_labels": models.DL_STATUS_LABELS,
        "dl_order": models.DL_STATUS_ORDER,
        "active": "dashboard",
    })


def _video_items(rows: list[models.Video]) -> list[dict]:
    items = []
    for v in rows:
        file_url = public_media_url(v.file_path) if v.file_path else None
        has_file = safe_media_path(v.file_path) is not None
        cover_local = public_media_url(v.cover_path) if v.cover_path else None
        cover_clean_local = public_media_url(v.cover_clean_path) if v.cover_clean_path else None
        # 优先显示去水印封面，其次原封面，最后回退视频首帧
        cover = cover_clean_local or cover_local or v.cover_url or (file_url if has_file else None)
        prog = download_progress_display(v)
        items.append({
            "v": v,
            "cover_url": cover,
            "cover_clean_url": cover_clean_local,
            "cover_raw_url": cover_local or v.cover_url,
            "play_url": file_url or f"/api/media/video/{v.id}",
            "has_file": has_file,
            "has_clean_cover": bool(cover_clean_local),
            "progress": prog["progress"],
            "indeterminate": prog["indeterminate"],
            "status_label": prog["status_label"],
        })
    return items


def _resources_url(page: int = 1, *, download_status: str | None = None,
                   source: str | None = None,
                   keyword: str | None = None,
                   trash_only: bool = False) -> str:
    params: dict[str, str | int] = {"page": max(1, page)}
    if download_status:
        params["download_status"] = download_status
    if source:
        params["source"] = source
    if keyword:
        params["keyword"] = keyword
    if trash_only:
        params["trash"] = 1
    return "/resources?" + urlencode(params)


@router.get("/resources", response_class=HTMLResponse, summary="资源库（视频）")
def resources_page(request: Request, page: int = 1,
                   download_status: str | None = None,
                   source: str | None = None,
                   keyword: str | None = None,
                   trash: int = 0,
                   db: Session = Depends(get_db)):
    trash_only = bool(trash)
    page = max(1, page)
    total = crud.count_videos(
        db, source=source, download_status=download_status, keyword=keyword, trash_only=trash_only
    )
    total_pages = max(1, ceil(total / PAGE_SIZE)) if total else 1
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * PAGE_SIZE
    rows = crud.list_videos(
        db, source=source, download_status=download_status,
        keyword=keyword,
        trash_only=trash_only,
        limit=PAGE_SIZE, offset=offset,
    )
    dl_counts = crud.counts_video_download(db)
    all_cats = crud.list_video_categories(db)
    selectable_categories = [c for c in all_cats if c.parent_id is not None]
    return TEMPLATES.TemplateResponse(request, "resources.html", {
        "items": _video_items(rows),
        "total": total,
        "page": page,
        "page_size": PAGE_SIZE,
        "total_pages": total_pages,
        "prev_url": _resources_url(
            page - 1, download_status=download_status, source=source, keyword=keyword, trash_only=trash_only
        ) if page > 1 else None,
        "next_url": _resources_url(
            page + 1, download_status=download_status, source=source, keyword=keyword, trash_only=trash_only
        ) if page < total_pages else None,
        "dl_counts": dl_counts,
        "dl_labels": models.DL_STATUS_LABELS,
        "dl_order": models.DL_STATUS_ORDER,
        "current_dl_status": download_status,
        "current_source": source,
        "current_keyword": keyword or "",
        "trash_only": trash_only,
        "selectable_categories": selectable_categories,
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


def _browse_url(page: int = 1, *, category_id: int | None = None,
                uncategorized: bool = False) -> str:
    params: dict[str, str | int] = {"page": max(1, page)}
    if uncategorized:
        params["uncategorized"] = 1
    elif category_id:
        params["category_id"] = category_id
    return "/browse?" + urlencode(params)


@router.get("/browse", response_class=HTMLResponse, summary="分类浏览")
def browse_page(
    request: Request,
    page: int = 1,
    category_id: int | None = None,
    uncategorized: int = 0,
    db: Session = Depends(get_db),
):
    page = max(1, page)
    is_uncat = bool(uncategorized)
    total = crud.count_videos(
        db, category_id=category_id if not is_uncat else None,
        uncategorized=is_uncat,
    )
    total_pages = max(1, ceil(total / PAGE_SIZE)) if total else 1
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * PAGE_SIZE
    rows = crud.list_videos(
        db,
        category_id=category_id if not is_uncat else None,
        uncategorized=is_uncat,
        limit=PAGE_SIZE,
        offset=offset,
        load_categories=True,
    )
    roots = crud.list_video_categories(db, roots_only=True)
    category_tree = []
    for root in roots:
        category_tree.append({
            "id": root.id,
            "name": root.name,
            "video_count": crud.count_videos_in_category(db, root.id),
            "children": [
                {
                    "id": ch.id,
                    "name": ch.name,
                    "video_count": crud.count_videos_in_category(db, ch.id),
                }
                for ch in root.children
            ],
        })
    current_cat = crud.get_video_category(db, category_id) if category_id else None
    items = _video_items(rows)
    for item in items:
        item["categories"] = [
            {"id": c.id, "name": c.name} for c in item["v"].content_categories
        ]
    return TEMPLATES.TemplateResponse(request, "browse.html", {
        "items": items,
        "total": total,
        "page": page,
        "page_size": PAGE_SIZE,
        "total_pages": total_pages,
        "prev_url": _browse_url(page - 1, category_id=category_id, uncategorized=is_uncat) if page > 1 else None,
        "next_url": _browse_url(page + 1, category_id=category_id, uncategorized=is_uncat) if page < total_pages else None,
        "category_tree": category_tree,
        "current_category_id": category_id,
        "current_category": current_cat,
        "uncategorized": is_uncat,
        "uncategorized_count": crud.count_uncategorized_videos(db),
        "total_videos": crud.count_videos(db),
        "active": "browse",
    })


@router.get("/category-editor", response_class=HTMLResponse, summary="分类编辑")
def category_editor_page(request: Request, db: Session = Depends(get_db)):
    roots = crud.list_video_categories(db, roots_only=True)
    category_tree = []
    for root in roots:
        category_tree.append({
            "id": root.id,
            "name": root.name,
            "video_count": crud.count_videos_in_category(db, root.id),
            "children": [
                {
                    "id": ch.id,
                    "name": ch.name,
                    "video_count": crud.count_videos_in_category(db, ch.id),
                }
                for ch in root.children
            ],
        })
    return TEMPLATES.TemplateResponse(request, "category_editor.html", {
        "category_tree": category_tree,
        "root_categories": [{"id": r.id, "name": r.name} for r in roots],
        "total_categories": sum(1 + len(item["children"]) for item in category_tree),
        "active": "category-editor",
    })


