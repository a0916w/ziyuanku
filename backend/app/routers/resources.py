"""资源相关 API：入库、列表、批量发送。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, models
from ..database import get_db
from ..schemas import ResourceIn, ResourceOut, IngestResult, BatchSendIn
from ..services.dispatch import send_to_clip

router = APIRouter(prefix="/api/resources", tags=["resources"])


def _to_out(r: models.Resource) -> ResourceOut:
    return ResourceOut(
        id=r.id, file_hash=r.file_hash, file_path=r.file_path,
        media_type=r.media_type, source_account=r.source_account,
        source_url=r.source_url, caption=r.caption, status=r.status,
        status_label=models.STATUS_LABELS.get(r.status, r.status),
        created_at=r.created_at,
    )


@router.post("", response_model=IngestResult, summary="爬虫入库（单条或批量）")
def ingest(payload: ResourceIn | list[ResourceIn], db: Session = Depends(get_db)):
    """爬虫抓完后调用。按文件哈希去重，已存在则跳过。"""
    items = payload if isinstance(payload, list) else [payload]
    created, dup, ids = 0, 0, []
    for item in items:
        res, is_new = crud.ingest_resource(db, item)
        ids.append(res.id)
        created += int(is_new)
        dup += int(not is_new)
    return IngestResult(created=created, duplicated=dup, ids=ids)


@router.get("", response_model=list[ResourceOut], summary="资源列表（可按状态/账号筛选）")
def list_resources(status: str | None = None, account: str | None = None,
                   limit: int = 200, db: Session = Depends(get_db)):
    rows = crud.list_resources(db, status=status, account=account, limit=limit)
    return [_to_out(r) for r in rows]


@router.post("/batch-send", summary="批量发送去剪片（接口文档到位前为 stub）")
def batch_send(payload: BatchSendIn, db: Session = Depends(get_db)):
    if not payload.resource_ids:
        raise HTTPException(400, "resource_ids 不能为空")
    resources = [db.get(models.Resource, rid) for rid in payload.resource_ids]
    resources = [r for r in resources if r is not None]
    if not resources:
        raise HTTPException(404, "未找到任何资源")
    result = send_to_clip(db, resources)
    return result
