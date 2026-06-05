"""爬虫脚本管理 API：登记、同步内置脚本、编辑、运行、查看日志。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, models
from ..database import get_db
from ..schemas import ScriptIn, ScriptUpdate
from ..services import browser_session
from ..services.crawler_runner import start_run
from ..services.script_registry import sync_registered_scripts

router = APIRouter(prefix="/api/scripts", tags=["scripts"])


def _script_dict(s: models.CrawlScript) -> dict:
    last = s.runs[0] if s.runs else None
    running = last is not None and last.status == models.RUN_RUNNING
    return {
        "id": s.id,
        "name": s.name,
        "command": s.command,
        "description": s.description,
        "enabled": s.enabled,
        "running": running,
        "last_run": None if not last else {
            "id": last.id,
            "status": last.status,
            "status_label": models.RUN_STATUS_LABELS.get(last.status, last.status),
            "started_at": last.started_at,
            "finished_at": last.finished_at,
            "exit_code": last.exit_code,
        },
    }


@router.get("", summary="脚本列表")
def list_scripts(db: Session = Depends(get_db)):
    return [_script_dict(s) for s in crud.list_scripts(db)]


@router.post("/sync", summary="同步内置爬虫脚本到数据库")
def sync_builtin_scripts(db: Session = Depends(get_db)):
    return sync_registered_scripts(db)


@router.post("", summary="登记一个爬虫脚本")
def create_script(payload: ScriptIn, db: Session = Depends(get_db)):
    if crud.get_script_by_name(db, payload.name):
        raise HTTPException(409, "同名脚本已存在")
    s = crud.create_script(db, payload.name, payload.command,
                           payload.description, payload.enabled)
    return {"id": s.id, "name": s.name}


@router.get("/{script_id}", summary="脚本详情")
def get_script_detail(script_id: int, db: Session = Depends(get_db)):
    s = crud.get_script(db, script_id)
    if not s:
        raise HTTPException(404, "脚本不存在")
    return _script_dict(s)


@router.patch("/{script_id}", summary="更新脚本")
def patch_script(script_id: int, payload: ScriptUpdate, db: Session = Depends(get_db)):
    s = crud.get_script(db, script_id)
    if not s:
        raise HTTPException(404, "脚本不存在")
    if crud.script_is_running(db, script_id):
        raise HTTPException(409, "脚本运行中，请先等待结束再编辑")
    crud.update_script(db, s, **payload.model_dump(exclude_unset=True))
    return _script_dict(s)


@router.delete("/{script_id}", summary="删除脚本")
def remove_script(script_id: int, db: Session = Depends(get_db)):
    s = crud.get_script(db, script_id)
    if not s:
        raise HTTPException(404, "脚本不存在")
    if crud.script_is_running(db, script_id):
        raise HTTPException(409, "脚本运行中，无法删除")
    crud.delete_script(db, s)
    return {"ok": True}


@router.post("/{script_id}/run", summary="立即运行脚本")
def run_script(script_id: int, db: Session = Depends(get_db)):
    s = crud.get_script(db, script_id)
    if not s:
        raise HTTPException(404, "脚本不存在")
    if not s.enabled:
        raise HTTPException(400, "脚本已停用")
    if crud.script_is_running(db, script_id):
        raise HTTPException(409, "该脚本已在运行中")
    if browser_session.command_requires_cdp(s.command) and not browser_session.status().cdp_available:
        raise HTTPException(409, "该脚本需要验证浏览器。请先在页面上启动验证浏览器并完成验证。")
    run = start_run(db, s)
    return {"run_id": run.id, "status": run.status}


@router.get("/{script_id}/runs", summary="脚本的运行记录")
def script_runs(script_id: int, db: Session = Depends(get_db)):
    s = crud.get_script(db, script_id)
    if not s:
        raise HTTPException(404, "脚本不存在")
    return [
        {"id": r.id, "status": r.status,
         "status_label": models.RUN_STATUS_LABELS.get(r.status, r.status),
         "exit_code": r.exit_code,
         "started_at": r.started_at, "finished_at": r.finished_at,
         "log": r.log}
        for r in s.runs
    ]
