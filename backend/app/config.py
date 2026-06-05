"""集中配置。可用环境变量覆盖。"""
import os
from pathlib import Path
from urllib.parse import quote_plus

# backend/
BASE_DIR = Path(__file__).resolve().parent.parent
# 仓库根（igcollect/）
REPO_ROOT = BASE_DIR.parent

# 统一数据目录：数据库 + 已下载媒体（instagram / missav / pornhub）
DATA_DIR = Path(os.getenv("ZIYUANKU_DATA_DIR", REPO_ROOT / "data"))
FILES_DIR = Path(os.getenv("ZIYUANKU_FILES_DIR", DATA_DIR))
MEDIA_DIR = Path(os.getenv("ZIYUANKU_MEDIA_DIR", DATA_DIR / "media"))

def _build_mysql_url_from_env() -> str | None:
    """从环境变量构建 MySQL URL（mysql+pymysql://...）。"""
    host = os.getenv("ZIYUANKU_MYSQL_HOST")
    if not host:
        return None
    port = os.getenv("ZIYUANKU_MYSQL_PORT", "3306")
    user = os.getenv("ZIYUANKU_MYSQL_USER", "root")
    password = os.getenv("ZIYUANKU_MYSQL_PASSWORD", "")
    database = os.getenv("ZIYUANKU_MYSQL_DB", "ziyuanku")
    charset = os.getenv("ZIYUANKU_MYSQL_CHARSET", "utf8mb4")
    return (
        f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}@"
        f"{host}:{port}/{database}?charset={charset}"
    )


DATABASE_URL = (
    os.getenv("ZIYUANKU_DATABASE_URL")
    or _build_mysql_url_from_env()
)
if not DATABASE_URL:
    raise RuntimeError(
        "未配置数据库连接。请设置 ZIYUANKU_DATABASE_URL，或提供 ZIYUANKU_MYSQL_* 环境变量。"
    )
if not DATABASE_URL.startswith("mysql+pymysql://"):
    raise RuntimeError("仅支持 MySQL（mysql+pymysql://）。请检查数据库配置。")


DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
