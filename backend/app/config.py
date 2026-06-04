"""集中配置。可用环境变量覆盖。"""
import os
from pathlib import Path

# 项目根（backend/）
BASE_DIR = Path(__file__).resolve().parent.parent

# 数据目录：SQLite 数据库 + 入库的媒体文件
DATA_DIR = Path(os.getenv("ZIYUANKU_DATA_DIR", BASE_DIR / "data"))
MEDIA_DIR = Path(os.getenv("ZIYUANKU_MEDIA_DIR", DATA_DIR / "media"))

DB_PATH = DATA_DIR / "ziyuanku.db"
DATABASE_URL = os.getenv("ZIYUANKU_DATABASE_URL", f"sqlite:///{DB_PATH}")

# 下游「剪片」接口（接口文档稍后提供，现在留占位）。
# 配置了 DISPATCH_ENDPOINT 才会真正发请求，否则走 stub（仅改状态、记日志）。
DISPATCH_ENDPOINT = os.getenv("ZIYUANKU_DISPATCH_ENDPOINT", "")
DISPATCH_TOKEN = os.getenv("ZIYUANKU_DISPATCH_TOKEN", "")

DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
