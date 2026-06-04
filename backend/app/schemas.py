"""Pydantic 请求/响应模型。"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ResourceIn(BaseModel):
    """入库接口的请求体。爬虫跑完调用 POST /api/resources。

    file_hash 为必填去重键；若爬虫不便计算，可改传本地 file_path 由服务端计算。
    """
    file_hash: Optional[str] = Field(None, description="文件内容哈希（去重键）")
    file_path: str = Field(..., description="媒体文件路径（服务端可读）")
    media_type: str = "unknown"
    source_account: Optional[str] = None
    source_url: Optional[str] = None
    caption: Optional[str] = None
    extra: Optional[dict[str, Any]] = None


class ResourceOut(BaseModel):
    id: int
    file_hash: str
    file_path: str
    media_type: str
    source_account: Optional[str]
    source_url: Optional[str]
    caption: Optional[str]
    status: str
    status_label: str
    created_at: datetime

    class Config:
        from_attributes = True


class IngestResult(BaseModel):
    created: int
    duplicated: int
    ids: list[int]


class BatchSendIn(BaseModel):
    resource_ids: list[int] = Field(..., description="要批量发送的资源 id 列表")


class ScriptIn(BaseModel):
    name: str
    command: str
    description: Optional[str] = None
    enabled: bool = True
