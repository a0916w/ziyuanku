#!/usr/bin/env python3
"""把 data/ 下已下载的媒体和 scrapers/ 脚本同步进数据库。

用法（在 backend 目录）：
  python3 sync_local.py
"""
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")

from app.database import SessionLocal, init_db
from app.services.local_sync import run_all

if __name__ == "__main__":
    init_db()
    db = SessionLocal()
    try:
        result = run_all(db)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        db.close()
