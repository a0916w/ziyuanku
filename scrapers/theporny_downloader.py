#!/usr/bin/env python3
"""theporny.com 视频下载器：抓详情 → 存全部文字信息 + 封面图 + 视频文件。

每个视频输出到 data/theporny/{id}/:
    info.json   —— 详情接口返回的全部字段(标题/番号/时长/标签/作者/播放地址…)
    cover.jpg   —— 封面图
    {id}.mp4    —— 由 m3u8 用 ffmpeg 下载合并的视频

用法:
    # 下载某个列表 JSON 里的前 2 部
    python3 scrapers/theporny_downloader.py --from-json data/metadata/theporny_c0.json --limit 2

    # 直接按视频 id 下载
    python3 scrapers/theporny_downloader.py --ids GQiBF6DGwU ZszdKvYgw

    # 只要封面+信息,不下视频
    python3 scrapers/theporny_downloader.py --ids GQiBF6DGwU --no-video

    # 下载后顺便推送线上入库(免交互,密码读环境变量)
    ZIYUANKU_PUSH_PASSWORD=xxxx python3 scrapers/theporny_downloader.py \\
        --from-json data/metadata/theporny_c0.json --limit 50 --push
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from theporny_scraper import SITE, HEADERS, fetch_detail  # noqa: E402
from push_to_server import (  # noqa: E402
    DEFAULT_SERVER, DEFAULT_USER, PushError, normalize, push_items,
)

# 始终输出到仓库根的 data/theporny,与其它爬虫一致(不受运行目录影响)
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = REPO_ROOT / "data" / "theporny"


def pick_m3u8(detail: dict) -> str | None:
    m3u8s = detail.get("m3u8s") or []
    if m3u8s:
        return m3u8s[0]
    return detail.get("m3u8") or None


def download_cover(detail: dict, out_dir: Path) -> str | None:
    thumbs = detail.get("thumbnails") or detail.get("thumbNails") or []
    if not thumbs:
        return None
    url = thumbs[0]
    dest = out_dir / "cover.jpg"
    try:
        resp = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"],
                                          "Referer": SITE + "/"}, timeout=30)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return str(dest)
    except Exception as e:  # noqa: BLE001
        print(f"    [封面失败] {e}", file=sys.stderr)
        return None


def download_video(m3u8: str, out_dir: Path, vid: str) -> str | None:
    dest = out_dir / f"{vid}.mp4"
    if dest.exists() and dest.stat().st_size > 0:
        print(f"    视频已存在,跳过:{dest}")
        return str(dest)
    # -movflags +faststart 把 moov 原子放到文件开头,
    # 否则 macOS QuickTime/Finder 与浏览器无法边下边播,常表现为"打不开"。
    cmd = [
        "ffmpeg", "-y", "-loglevel", "warning", "-stats",
        "-headers", f"Referer: {SITE}/\r\nUser-Agent: {HEADERS['User-Agent']}\r\n",
        "-i", m3u8, "-c", "copy", "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart",
        str(dest),
    ]
    proc = subprocess.run(cmd)
    if proc.returncode != 0 or not dest.exists():
        print(f"    [视频下载失败] ffmpeg 退出码 {proc.returncode}", file=sys.stderr)
        return None
    return str(dest)


def detail_to_item(detail: dict) -> dict | None:
    """把详情接口返回的 dict 映射成入库 item(字段对齐 theporny_scraper.to_item)。"""
    vid = detail.get("vId") or detail.get("id")
    if not vid:
        return None
    thumbs = detail.get("thumbnails") or detail.get("thumbNails") or []
    cover = thumbs[0] if thumbs else None
    tags = [t.strip() for t in (detail.get("keywords_gem") or "").split(",") if t.strip()]
    return {
        "title": detail.get("title") or detail.get("title_en") or vid,
        "code": vid,
        "url": f"{SITE}/video/{vid}",
        "cover": cover,
        "duration": detail.get("durationStr") or "",
        "source": "theporny",
        "extra": {
            "title_en": detail.get("title_en"),
            "user": detail.get("user"),
            "views": detail.get("views"),
            "size": detail.get("size"),
            "time": detail.get("time"),
            "video_type": detail.get("videoType"),
            "tags": tags,
        },
    }


def process(vid: str, with_video: bool) -> tuple[bool, dict | None]:
    """返回 (是否成功, 入库 item dict 或 None)。"""
    print(f"[{vid}] 抓详情…")
    try:
        detail = fetch_detail(vid)
    except RuntimeError as e:
        print(f"    [失败] {e}", file=sys.stderr)
        return False, None

    out_dir = OUT_ROOT / vid
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "info.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
    title = detail.get("title") or vid
    print(f"    标题:{title} | 时长:{detail.get('durationStr')} | 大小:{detail.get('size')}")

    cover = download_cover(detail, out_dir)
    print(f"    封面:{cover or '无'}")

    if with_video:
        m3u8 = pick_m3u8(detail)
        if not m3u8:
            print("    [警告] 无 m3u8 播放地址,跳过视频", file=sys.stderr)
        else:
            print(f"    下载视频:{m3u8}")
            path = download_video(m3u8, out_dir, vid)
            if path:
                size_mb = Path(path).stat().st_size / 1024 / 1024
                print(f"    视频已保存:{path}（{size_mb:.1f} MB）")
            else:
                return False, None
    return True, detail_to_item(detail)


def collect_ids(args) -> list[str]:
    if args.ids:
        return args.ids
    if args.from_json:
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        ids = [x.get("code") or x.get("id") or x.get("vId") for x in data]
        ids = [i for i in ids if i]
        if args.limit:
            ids = ids[:args.limit]
        return ids
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="theporny.com 视频下载器")
    parser.add_argument("--ids", nargs="*", help="视频 id 列表")
    parser.add_argument("--from-json", help="从列表 JSON(theporny_scraper 产出)读取 id")
    parser.add_argument("--limit", type=int, help="配合 --from-json,只取前 N 个")
    parser.add_argument("--no-video", action="store_true", help="只下封面+信息,不下视频")
    parser.add_argument("--push", action="store_true",
                        help="下载完顺便推送到线上 /api/videos 入库(免交互)")
    parser.add_argument("--push-server", default=DEFAULT_SERVER,
                        help=f"推送目标服务器,默认 {DEFAULT_SERVER}")
    parser.add_argument("--push-user", default=DEFAULT_USER,
                        help=f"推送 basic auth 用户名,默认 {DEFAULT_USER}")
    parser.add_argument("--push-batch-size", type=int, default=100,
                        help="推送分批大小,默认 100")
    parser.add_argument("--push-insecure", action="store_true",
                        help="推送时跳过 TLS 证书校验(自签时用)")
    args = parser.parse_args()

    if args.push and not os.getenv("ZIYUANKU_PUSH_PASSWORD"):
        print("[错误] --push 需要在环境变量 ZIYUANKU_PUSH_PASSWORD 里提供密码",
              file=sys.stderr)
        return 1

    ids = collect_ids(args)
    if not ids:
        print("[错误] 请用 --ids 或 --from-json 指定视频", file=sys.stderr)
        return 1

    ok = 0
    items: list[dict] = []
    for vid in ids:
        success, item = process(vid, with_video=not args.no_video)
        if success:
            ok += 1
            if item:
                norm = normalize(item, "theporny", keep_local=False)
                if norm:
                    items.append(norm)
        print()
    print(f"完成:成功 {ok}/{len(ids)} 部，输出目录 {OUT_ROOT}/")

    if args.push:
        if not items:
            print("[推送] 无可推送条目,跳过")
        else:
            print(f"[推送] 准备向 {args.push_server} 推送 {len(items)} 条…")
            try:
                created, dup = push_items(
                    items,
                    server=args.push_server,
                    user=args.push_user,
                    password=os.getenv("ZIYUANKU_PUSH_PASSWORD", ""),
                    batch_size=args.push_batch_size,
                    insecure=args.push_insecure,
                )
            except PushError as e:
                print(f"[推送失败] {e}", file=sys.stderr)
                return e.exit_code
            print(f"[推送] 完成:新增 {created} 条,重复 {dup} 条")

    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
