"""集中配置。可用环境变量覆盖。"""
import os
import shutil
import sqlite3
from pathlib import Path

# backend/
BASE_DIR = Path(__file__).resolve().parent.parent
# 仓库根（igcollect/）
REPO_ROOT = BASE_DIR.parent

# 统一数据目录：数据库 + 已下载媒体（instagram / missav / pornhub）
DATA_DIR = Path(os.getenv("ZIYUANKU_DATA_DIR", REPO_ROOT / "data"))
FILES_DIR = Path(os.getenv("ZIYUANKU_FILES_DIR", DATA_DIR))
MEDIA_DIR = Path(os.getenv("ZIYUANKU_MEDIA_DIR", DATA_DIR / "media"))

DB_PATH = DATA_DIR / "ziyuanku.db"
DATABASE_URL = os.getenv("ZIYUANKU_DATABASE_URL", f"sqlite:///{DB_PATH}")

# 旧版数据库位置（backend/data/），启动时自动迁移到 DATA_DIR
LEGACY_DB_PATH = BASE_DIR / "data" / "ziyuanku.db"

DISPATCH_ENDPOINT = os.getenv("ZIYUANKU_DISPATCH_ENDPOINT", "")
DISPATCH_TOKEN = os.getenv("ZIYUANKU_DISPATCH_TOKEN", "")


def _db_resource_count(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        con = sqlite3.connect(str(path))
        row = con.execute(
            "SELECT COUNT(*) FROM resources"
        ).fetchone()
        con.close()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def migrate_legacy_database() -> bool:
    """仅当 data/ziyuanku.db 尚不存在时，从 backend/data/ 迁移一次。"""
    legacy = LEGACY_DB_PATH.resolve()
    target = DB_PATH.resolve()
    if legacy == target or not legacy.is_file() or target.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, target)
    return True


DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
