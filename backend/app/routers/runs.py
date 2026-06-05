"""脚本运行记录 API（供后台轮询刷新）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import crud, models
from ..database import get_db

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _fmt_dt(dt) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def _run_dict(r: models.CrawlRun) -> dict:
    return {
        "id": r.id,
        "script_id": r.script_id,
        "script_name": r.script.name if r.script else "",
        "status": r.status,
        "status_label": models.RUN_STATUS_LABELS.get(r.status, r.status),
        "exit_code": r.exit_code,
        "started_at": _fmt_dt(r.started_at),
        "finished_at": _fmt_dt(r.finished_at),
        "log": r.log or "",
    }


@router.get("/recent", summary="最近脚本运行记录")
def recent_runs(limit: int = 30, db: Session = Depends(get_db)):
    rows = crud.list_recent_runs(db, limit=limit)
    return {
        "runs": [_run_dict(r) for r in rows],
        "has_running": crud.has_running_scripts(db),
    }
