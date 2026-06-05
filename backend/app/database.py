"""SQLAlchemy 引擎与会话。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_URL, migrate_legacy_database

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    """FastAPI 依赖：每请求一个会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_sqlite_columns():
    """为已有 SQLite 库补齐新增列（create_all 不会改已有表）。"""
    if not DATABASE_URL.startswith("sqlite"):
        return
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "videos" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("videos")}
    alters = []
    if "download_status" not in existing:
        alters.append("ALTER TABLE videos ADD COLUMN download_status VARCHAR(32) DEFAULT 'pending'")
    if "download_error" not in existing:
        alters.append("ALTER TABLE videos ADD COLUMN download_error TEXT")
    if "downloaded_at" not in existing:
        alters.append("ALTER TABLE videos ADD COLUMN downloaded_at DATETIME")
    if "download_progress" not in existing:
        alters.append("ALTER TABLE videos ADD COLUMN download_progress INTEGER DEFAULT 0")
    if "cover_path" not in existing:
        alters.append("ALTER TABLE videos ADD COLUMN cover_path VARCHAR(1024)")
    if "cover_clean_path" not in existing:
        alters.append("ALTER TABLE videos ADD COLUMN cover_clean_path VARCHAR(1024)")
    if not alters:
        pass
    else:
        with engine.begin() as conn:
            for sql in alters:
                conn.execute(text(sql))

    if "crawl_scripts" in insp.get_table_names():
        script_cols = {c["name"] for c in insp.get_columns("crawl_scripts")}
        if "category_id" not in script_cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE crawl_scripts ADD COLUMN category_id INTEGER "
                    "REFERENCES script_categories(id)"
                ))


def init_db():
    """建表（MVP 阶段用 create_all，后续如需迁移再上 Alembic）。"""
    migrate_legacy_database()
    from . import models  # noqa: F401  确保模型已注册
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_columns()
