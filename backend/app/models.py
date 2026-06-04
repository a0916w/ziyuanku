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
