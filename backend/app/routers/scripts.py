"""爬虫脚本管理 API：登记、列表、触发运行、查看运行记录。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, models
from ..database import get_db
from ..schemas import ScriptIn
from ..services.crawler_runner import start_run

router = APIRouter(prefix="/api/scripts", tags=["scripts"])


@router.get("", summary="脚本列表")
def list_scripts(db: Session = Depends(get_db)):
    out = []
    for s in crud.list_scripts(db):
        last = s.runs[0] if s.runs else None
        out.append({
            "id": s.id, "name": s.name, "command": s.command,
            "description": s.description, "enabled": s.enabled,
            "last_run": None if not last else {
                "id": last.id, "status": last.status,
                "started_at": last.started_at, "finished_at": last.finished_at,
            },
        })
    return out


@router.post("", summary="登记一个爬虫脚本")
def create_script(payload: ScriptIn, db: Session = Depends(get_db)):
    s = crud.create_script(db, payload.name, payload.command,
                           payload.description, payload.enabled)
    return {"id": s.id, "name": s.name}


@router.post("/{script_id}/run", summary="立即运行脚本")
def run_script(script_id: int, db: Session = Depends(get_db)):
    s = crud.get_script(db, script_id)
    if not s:
        raise HTTPException(404, "脚本不存在")
    if not s.enabled:
        raise HTTPException(400, "脚本已停用")
    run = start_run(db, s)
    return {"run_id": run.id, "status": run.status}


@router.get("/{script_id}/runs", summary="脚本的运行记录")
def script_runs(script_id: int, db: Session = Depends(get_db)):
    s = crud.get_script(db, script_id)
    if not s:
        raise HTTPException(404, "脚本不存在")
    return [
        {"id": r.id, "status": r.status, "exit_code": r.exit_code,
         "started_at": r.started_at, "finished_at": r.finished_at,
         "log": r.log}
        for r in s.runs
    ]
