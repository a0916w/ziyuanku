"""内置爬虫脚本登记表：启动或手动同步时写入数据库。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import crud

DEFAULT_CATEGORIES = [
    {"name": "MissAV", "description": "MissAV 列表与下载", "sort_order": 10},
    {"name": "Pornhub", "description": "Pornhub 模特页爬虫", "sort_order": 20},
    {"name": "Instagram", "description": "Instagram 图片/视频下载", "sort_order": 30},
    {"name": "其它", "description": "自定义脚本", "sort_order": 99},
]

# 按名称 upsert；命令在仓库根目录执行（见 crawler_runner.REPO_ROOT）
REGISTERED_SCRIPTS: list[dict] = [
    {
        "name": "MissAV 列表爬虫",
        "command": (
            "python3 scrapers/missav_scraper.py "
            "--cdp-url http://127.0.0.1:9222 "
            "--max-pages 10 -o data/metadata/twav_videos.json"
        ),
        "description": "抓取 MissAV 列表元数据 → data/metadata/twav_videos.json（需自备可访问的浏览器 CDP）",
        "kind": "scrape",
        "category": "MissAV",
    },
    {
        "name": "MissAV 视频下载",
        "command": (
            "python3 scrapers/missav_downloader.py "
            "-i data/metadata/twav_videos.json -o data/missav/twav "
            "--cdp-url http://127.0.0.1:9222"
        ),
        "description": "从 JSON 获取 m3u8 并下载 MissAV 视频 → data/missav/twav",
        "kind": "download",
        "category": "MissAV",
    },
    {
        "name": "Pornhub 列表爬虫",
        "command": (
            'python3 scrapers/pornhub_scraper.py '
            '"https://cn.pornhub.com/model/sweetie-fox" --max-pages 20 '
            "-o data/metadata/sweetie_fox_videos.json"
        ),
        "description": "抓取模特视频列表 → data/metadata/sweetie_fox_videos.json",
        "kind": "scrape",
        "category": "Pornhub",
    },
    {
        "name": "Pornhub 视频下载",
        "command": (
            "python3 scrapers/pornhub_downloader.py "
            "-i data/metadata/sweetie_fox_videos.json -o data/pornhub/sweetie-fox"
        ),
        "description": "从 JSON 下载 Pornhub 视频 → data/pornhub/sweetie-fox（耗时长）",
        "kind": "download",
        "category": "Pornhub",
    },
    {
        "name": "Instagram 下载（示例）",
        "command": (
            "python3 scrapers/ig_downloader.py USERNAME "
            "--cookies data/cookies/instagram.json"
        ),
        "description": "将 USERNAME 换成目标账号；需自备 cookies。输出到 data/instagram/",
        "kind": "download",
        "category": "Instagram",
        "enabled": False,
    },
]


def sync_default_categories(db: Session) -> dict:
    created = updated = 0
    for spec in DEFAULT_CATEGORIES:
        _, is_new = crud.upsert_script_category(
            db,
            name=spec["name"],
            description=spec.get("description"),
            sort_order=spec.get("sort_order", 0),
        )
        if is_new:
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated, "total": len(DEFAULT_CATEGORIES)}


def _category_id(db: Session, name: str | None) -> int | None:
    if not name:
        return None
    cat = crud.get_script_category_by_name(db, name)
    return cat.id if cat else None


def sync_registered_scripts(db: Session) -> dict:
    """把内置分类与脚本同步进数据库。"""
    cat_stats = sync_default_categories(db)
    created = updated = 0
    for spec in REGISTERED_SCRIPTS:
        _, is_new = crud.upsert_script(
            db,
            name=spec["name"],
            command=spec["command"],
            description=spec.get("description"),
            enabled=spec.get("enabled", True),
            category_id=_category_id(db, spec.get("category")),
        )
        if is_new:
            created += 1
        else:
            updated += 1
    return {
        "categories": cat_stats,
        "created": created,
        "updated": updated,
        "total": len(REGISTERED_SCRIPTS),
    }
