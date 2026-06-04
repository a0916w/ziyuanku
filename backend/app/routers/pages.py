"""后台页面（服务端渲染）。"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from pathlib import Path

from .. import crud, models
from ..database import get_db

router = APIRouter(tags=["pages"])
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse, summary="首页/概览")
def dashboard(request: Request, db: Session = Depends(get_db)):
    counts = crud.counts_by_status(db)
    scripts = crud.list_scripts(db)
    return TEMPLATES.TemplateResponse(request, "dashboard.html", {
        "counts": counts, "labels": models.STATUS_LABELS,
        "order": models.STATUS_ORDER, "scripts": scripts, "active": "dashboard",
    })


@router.get("/resources", response_class=HTMLResponse, summary="资源库页")
def resources_page(request: Request, status: str | None = None,
                   db: Session = Depends(get_db)):
    rows = crud.list_resources(db, status=status)
    return TEMPLATES.TemplateResponse(request, "resources.html", {
        "resources": rows, "labels": models.STATUS_LABELS,
        "order": models.STATUS_ORDER, "current_status": status, "active": "resources",
    })


@router.get("/scripts", response_class=HTMLResponse, summary="爬虫脚本管理页")
def scripts_page(request: Request, db: Session = Depends(get_db)):
    scripts = crud.list_scripts(db)
    return TEMPLATES.TemplateResponse(request, "scripts.html", {
        "scripts": scripts, "active": "scripts",
    })
