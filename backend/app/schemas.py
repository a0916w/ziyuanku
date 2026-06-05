"""Pydantic 请求/响应模型。"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


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


class VideoIn(BaseModel):
    """视频入库请求体。兼容爬虫 JSON 字段名（url / cover）。"""
    title: str = Field(..., description="视频标题")
    code: Optional[str] = Field(None, description="番号，有则作为去重键")
    source_url: Optional[str] = Field(None, description="详情页链接")
    url: Optional[str] = Field(None, description="详情页链接（与 source_url 二选一）")
    cover: Optional[str] = Field(None, description="封面图 URL")
    cover_url: Optional[str] = Field(None, description="封面图 URL（与 cover 二选一）")
    cover_path: Optional[str] = Field(None, description="封面图本地路径")
    duration: Optional[str] = None
    video_url: Optional[str] = Field(None, description="视频流地址（m3u8 等）")
    file_path: Optional[str] = Field(None, description="本地下载文件路径")
    download_status: Optional[str] = Field(None, description="下载状态：pending/downloading/done/failed")
    source: str = Field("missav", description="来源站点标识")
    extra: Optional[dict[str, Any]] = None

    @model_validator(mode="after")
    def _normalize_fields(self) -> "VideoIn":
        if not self.source_url and self.url:
            object.__setattr__(self, "source_url", self.url)
        if not self.cover_url and self.cover:
            object.__setattr__(self, "cover_url", self.cover)
        if not self.source_url:
            raise ValueError("source_url 或 url 至少提供一个")
        return self


class VideoOut(BaseModel):
    id: int
    code: Optional[str]
    title: str
    cover_url: Optional[str]
    cover_path: Optional[str]
    cover_clean_path: Optional[str]
    source_url: str
    duration: Optional[str]
    video_url: Optional[str]
    file_path: Optional[str]
    download_status: str
    download_status_label: str
    download_progress: int = 0
    download_error: Optional[str]
    downloaded_at: Optional[datetime]
    source: str
    extra: Optional[dict[str, Any]]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class VideoDownloadUpdate(BaseModel):
    download_status: str = Field(..., description="pending / downloading / done / failed")
    download_progress: Optional[int] = Field(None, ge=0, le=100)
    file_path: Optional[str] = None
    video_url: Optional[str] = None
    download_error: Optional[str] = None


class VideoIngestResult(BaseModel):
    created: int
    duplicated: int
    ids: list[int]


class VideoCategoryOut(BaseModel):
    id: int
    name: str
    parent_id: Optional[int]
    sort_order: int
    video_count: int = 0
    children: list["VideoCategoryOut"] = []

    class Config:
        from_attributes = True


class VideoCategoriesAssign(BaseModel):
    category_ids: list[int] = Field(..., description="子分类 id 列表（会覆盖原绑定）")


class VideoCategoryBind(BaseModel):
    category_id: int = Field(..., description="子分类 id")


class VideoCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    parent_id: Optional[int] = Field(None, description="为空表示一级分类")
    sort_order: int = 0


class VideoCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    sort_order: Optional[int] = None
