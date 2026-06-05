#!/usr/bin/env python3
"""把 SQLite 数据迁移到 MySQL。

用法：
  cd backend
  python3 migrate_sqlite_to_mysql.py

可选参数：
  --source-sqlite /abs/path/to/ziyuanku.db
  --target-url mysql+pymysql://user:pass@host:3306/dbname?charset=utf8mb4
  --keep-target-data   # 默认会先清空目标表
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from sqlalchemy import MetaData, create_engine, select, text

from app.config import DATABASE_URL, DB_PATH
from app.database import Base

# 确保模型注册到 Base.metadata
from app import models  # noqa: F401


def _chunked(items: list[dict], size: int) -> Iterable[list[dict]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SQLite -> MySQL 数据迁移")
    parser.add_argument(
        "--source-sqlite",
        default=str(DB_PATH),
        help="SQLite 文件路径（默认读取 app.config.DB_PATH）",
    )
    parser.add_argument(
        "--target-url",
        default=DATABASE_URL,
        help="目标 MySQL URL（默认读取 app.config.DATABASE_URL）",
    )
    parser.add_argument(
        "--keep-target-data",
        action="store_true",
        help="保留目标库原有数据（默认会先清空目标表）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="批量写入大小，默认 500",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    src_path = Path(args.source_sqlite).expanduser().resolve()
    if not src_path.is_file():
        raise SystemExit(f"SQLite 文件不存在: {src_path}")

    target_url = args.target_url.strip()
    if not target_url.startswith("mysql"):
        raise SystemExit(
            "目标数据库不是 MySQL。请设置 --target-url 或 ZIYUANKU_DATABASE_URL 为 mysql+pymysql://..."
        )

    src_engine = create_engine(f"sqlite:///{src_path}", future=True)
    dst_engine = create_engine(target_url, future=True)

    # 先在 MySQL 建表（幂等）
    Base.metadata.create_all(bind=dst_engine)

    src_meta = MetaData()
    dst_meta = MetaData()
    src_meta.reflect(bind=src_engine)
    dst_meta.reflect(bind=dst_engine)

    table_names = [t.name for t in Base.metadata.sorted_tables]
    print(f"将迁移 {len(table_names)} 张表: {', '.join(table_names)}")

    with dst_engine.begin() as dst_conn:
        if not args.keep_target_data:
            print("清空目标库已有数据...")
            dst_conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for name in reversed(table_names):
                if name in dst_meta.tables:
                    dst_conn.execute(text(f"DELETE FROM `{name}`"))
            dst_conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    total_rows = 0
    with src_engine.connect() as src_conn, dst_engine.begin() as dst_conn:
        for name in table_names:
            src_table = src_meta.tables.get(name)
            dst_table = dst_meta.tables.get(name)
            if src_table is None or dst_table is None:
                print(f"[跳过] {name}: 源或目标表不存在")
                continue

            src_rows = src_conn.execute(select(src_table)).mappings().all()
            if not src_rows:
                print(f"[完成] {name}: 0 行")
                continue

            dst_cols = {c.name for c in dst_table.columns}
            rows = []
            for row in src_rows:
                rows.append({k: v for k, v in row.items() if k in dst_cols})

            inserted = 0
            for batch in _chunked(rows, max(1, args.batch_size)):
                dst_conn.execute(dst_table.insert(), batch)
                inserted += len(batch)
            total_rows += inserted
            print(f"[完成] {name}: {inserted} 行")

    print(f"\n迁移完成，总计 {total_rows} 行。")


if __name__ == "__main__":
    main()
