"""内置爬虫脚本登记表：启动或手动同步时写入数据库。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import crud

# 按名称 upsert；命令在仓库根目录执行（见 crawler_runner.REPO_ROOT）
REGISTERED_SCRIPTS: list[dict] = [
    {
        "name": "MissAV 列表爬虫",
        "command": "python3 scrapers/missav_scraper.py",
        "description": "抓取 MissAV 列表元数据 → data/metadata/twav_videos.json",
        "kind": "scrape",
    },
    {
        "name": "MissAV 视频下载",
        "command": (
            "python3 scrapers/missav_downloader.py "
            "-i data/metadata/twav_videos.json -o data/missav/twav"
        ),
        "description": "从 JSON 下载 MissAV 视频 → data/missav/twav",
        "kind": "download",
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
    },
    {
        "name": "Pornhub 视频下载",
        "command": (
            "python3 scrapers/pornhub_downloader.py "
            "-i data/metadata/sweetie_fox_videos.json -o data/pornhub/sweetie-fox"
        ),
        "description": "从 JSON 下载 Pornhub 视频 → data/pornhub/sweetie-fox（耗时长）",
        "kind": "download",
    },
    {
        "name": "Instagram 下载（示例）",
        "command": (
            "python3 scrapers/ig_downloader.py USERNAME "
            "--cookies data/cookies/instagram.json"
        ),
        "description": "将 USERNAME 换成目标账号；需自备 cookies。输出到 data/instagram/",
        "kind": "download",
        "enabled": False,
    },
]


def sync_registered_scripts(db: Session) -> dict:
    """把内置脚本同步进 crawl_scripts 表。"""
    created = updated = 0
    for spec in REGISTERED_SCRIPTS:
        _, is_new = crud.upsert_script(
            db,
            name=spec["name"],
            command=spec["command"],
            description=spec.get("description"),
            enabled=spec.get("enabled", True),
        )
        if is_new:
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated, "total": len(REGISTERED_SCRIPTS)}
