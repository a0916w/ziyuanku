"""数据库模型。"""
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Boolean, JSON,
)
from sqlalchemy.orm import relationship

from .database import Base

# 资源状态机（四态）：未处理 → 已发送切片 → 切片完毕 → 已发送到项目
STATUS_PENDING = "pending"            # 未处理
STATUS_SENT_FOR_CLIP = "sent_for_clip"  # 已发送切片
STATUS_CLIP_DONE = "clip_done"        # 切片完毕
STATUS_SENT_TO_PROJECT = "sent_to_project"  # 已发送到项目

STATUS_LABELS = {
    STATUS_PENDING: "未处理",
    STATUS_SENT_FOR_CLIP: "已发送切片",
    STATUS_CLIP_DONE: "切片完毕",
    STATUS_SENT_TO_PROJECT: "已发送到项目",
}
STATUS_ORDER = [
    STATUS_PENDING, STATUS_SENT_FOR_CLIP, STATUS_CLIP_DONE, STATUS_SENT_TO_PROJECT,
]

# 脚本运行状态
RUN_RUNNING = "running"
RUN_SUCCESS = "success"
RUN_FAILED = "failed"
RUN_STATUS_LABELS = {
    RUN_RUNNING: "运行中",
    RUN_SUCCESS: "成功",
    RUN_FAILED: "失败",
}

# 视频下载状态
DL_PENDING = "pending"
DL_DOWNLOADING = "downloading"
DL_DONE = "done"
DL_FAILED = "failed"
DL_STATUS_LABELS = {
    DL_PENDING: "待下载",
    DL_DOWNLOADING: "下载中",
    DL_DONE: "已完成",
    DL_FAILED: "失败",
}
DL_STATUS_ORDER = [DL_PENDING, DL_DOWNLOADING, DL_DONE, DL_FAILED]


class Resource(Base):
    __tablename__ = "resources"

    id = Column(Integer, primary_key=True)
    # 去重键：文件内容哈希（同一文件算重复，唯一约束）
    file_hash = Column(String(64), unique=True, nullable=False, index=True)
    file_path = Column(String(1024), nullable=False)   # 媒体落盘路径
    media_type = Column(String(32), default="unknown")  # image / video / unknown
    source_account = Column(String(255), index=True)    # 来源账号
    source_url = Column(String(1024))                   # 原帖链接
    caption = Column(Text)                               # 文案
    extra = Column(JSON)                                 # 其它元数据（接口文档到位后细化）

    status = Column(String(32), default=STATUS_PENDING, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    sent_for_clip_at = Column(DateTime)
    clip_done_at = Column(DateTime)
    sent_to_project_at = Column(DateTime)


class Video(Base):
    """爬虫采集的视频元数据（封面、标题、流地址、本地文件等）。"""
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True)
    code = Column(String(128), index=True)              # 番号，优先作去重键
    title = Column(String(512), nullable=False)
    cover_url = Column(String(1024))                    # 封面图 URL
    source_url = Column(String(1024), nullable=False, index=True)  # 详情页链接
    duration = Column(String(32))
    video_url = Column(String(2048))                    # 视频流地址（m3u8 等）
    file_path = Column(String(1024))                    # 本地下载路径
    download_status = Column(String(32), default=DL_PENDING, index=True)
    download_progress = Column(Integer, default=0)        # 0–100
    download_error = Column(Text)
    downloaded_at = Column(DateTime)
    source = Column(String(64), default="missav", index=True)  # 来源站点
    extra = Column(JSON)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CrawlScript(Base):
    """爬虫脚本登记：管理可运行的爬虫脚本。"""
    __tablename__ = "crawl_scripts"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    # 运行命令（相对仓库根或绝对），例如：python3 ig_downloader.py --file usernames.txt
    command = Column(Text, nullable=False)
    description = Column(Text)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    runs = relationship("CrawlRun", back_populates="script",
                        cascade="all, delete-orphan", order_by="desc(CrawlRun.started_at)")


class CrawlRun(Base):
    """一次爬虫运行记录。"""
    __tablename__ = "crawl_runs"

    id = Column(Integer, primary_key=True)
    script_id = Column(Integer, ForeignKey("crawl_scripts.id"), nullable=False, index=True)
    status = Column(String(32), default="running")  # running / success / failed
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    finished_at = Column(DateTime)
    exit_code = Column(Integer)
    log = Column(Text)  # stdout + stderr 截断保存

    script = relationship("CrawlScript", back_populates="runs")
