"""本地数据同步 API。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.local_sync import run_all

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.post("/local", summary="扫描 data/ 目录，入库已下载资源并登记脚本")
def sync_local(db: Session = Depends(get_db)):
    return run_all(db)
