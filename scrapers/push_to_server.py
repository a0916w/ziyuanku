#!/usr/bin/env python3
"""把本机爬虫产出的视频元数据 JSON 推送到线上资源库入库接口。

适用场景：服务器机房 IP 过不了 MissAV 的 Cloudflare，于是在**本机**跑爬虫，
再用本脚本把结果通过 `POST /api/videos` 入库到线上数据库（按 code/source_url 去重）。

爬虫输出 JSON 形如（missav_scraper.py / pornhub_scraper.py 的产物）：
    [{"title": "...", "url": "https://...", "cover": "https://...",
      "duration": "12:34", "code": "ABC-123"}, ...]
这些字段会被入库接口直接识别（url→source_url，cover→cover_url）。

用法示例：
    python3 scrapers/push_to_server.py data/metadata/twav_videos.json \
        --source missav --password 'xxxx'

    # 密码也可用环境变量，避免出现在命令历史里：
    ZIYUANKU_PUSH_PASSWORD='xxxx' python3 scrapers/push_to_server.py \
        data/metadata/sweetie_fox_videos.json --source pornhub
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

import requests

DEFAULT_SERVER = os.getenv("ZIYUANKU_SERVER", "http://13.212.221.77")
DEFAULT_USER = os.getenv("ZIYUANKU_PUSH_USER", "admin")


def load_items(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        # 兼容 {"videos": [...]} 或单条
        if isinstance(data.get("videos"), list):
            data = data["videos"]
        else:
            data = [data]
    if not isinstance(data, list):
        raise ValueError("JSON 顶层应为数组或 {videos:[...]}")
    return data


def normalize(item: dict, source: str, keep_local: bool = False) -> dict | None:
    """补齐 source；确保有 source_url（url）与 title。无效项返回 None。

    默认剥掉本机绝对路径字段（cover_path/file_path），它们在服务器上无意义。
    """
    out = dict(item)
    out.setdefault("source", source)
    if not keep_local:
        out.pop("cover_path", None)
        out.pop("file_path", None)
    if not (out.get("source_url") or out.get("url")):
        return None
    if not out.get("title"):
        out["title"] = out.get("code") or out.get("url") or out.get("source_url")
    return out


def chunked(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def main() -> int:
    parser = argparse.ArgumentParser(description="把本机爬虫 JSON 推送到线上入库接口")
    parser.add_argument("json_file", help="爬虫输出的视频 JSON 文件")
    parser.add_argument("--source", default="missav", help="来源标识（missav/pornhub/instagram…），缺省 missav")
    parser.add_argument("--server", default=DEFAULT_SERVER, help=f"线上服务器地址，默认 {DEFAULT_SERVER}")
    parser.add_argument("--user", default=DEFAULT_USER, help=f"basic auth 用户名，默认 {DEFAULT_USER}")
    parser.add_argument("--password", default=os.getenv("ZIYUANKU_PUSH_PASSWORD"),
                        help="basic auth 密码（也可用环境变量 ZIYUANKU_PUSH_PASSWORD）")
    parser.add_argument("--batch-size", type=int, default=100, help="每批推送条数，默认 100")
    parser.add_argument("--insecure", action="store_true", help="跳过 TLS 证书校验（https 自签时用）")
    parser.add_argument("--keep-local-paths", action="store_true",
                        help="保留 cover_path/file_path 本机路径（默认剥掉）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要推送的条数，不实际发送")
    args = parser.parse_args()

    path = Path(args.json_file)
    if not path.exists():
        print(f"[错误] 找不到文件：{path}", file=sys.stderr)
        return 1

    raw = load_items(path)
    items = [x for x in (normalize(it, args.source, args.keep_local_paths) for it in raw) if x]
    skipped = len(raw) - len(items)
    print(f"读取 {len(raw)} 条，有效 {len(items)} 条" + (f"，跳过 {skipped} 条（缺 url）" if skipped else ""))

    if not items:
        print("没有可推送的有效数据。")
        return 0

    if args.dry_run:
        print("dry-run：示例第一条 →")
        print(json.dumps(items[0], ensure_ascii=False, indent=2))
        return 0

    password = args.password
    if not password:
        password = getpass.getpass(f"{args.user}@{args.server} 的密码：")

    url = args.server.rstrip("/") + "/api/videos"
    auth = (args.user, password)
    total_created = total_dup = 0

    for idx, batch in enumerate(chunked(items, args.batch_size), 1):
        try:
            resp = requests.post(
                url, json=batch, auth=auth, timeout=60,
                verify=not args.insecure,
            )
        except requests.RequestException as e:
            print(f"[批 {idx}] 请求失败：{e}", file=sys.stderr)
            return 2
        if resp.status_code == 401:
            print("[错误] 鉴权失败（401）：用户名或密码不对。", file=sys.stderr)
            return 3
        if not resp.ok:
            print(f"[批 {idx}] 入库失败 HTTP {resp.status_code}：{resp.text[:300]}", file=sys.stderr)
            return 4
        data = resp.json()
        total_created += data.get("created", 0)
        total_dup += data.get("duplicated", 0)
        print(f"[批 {idx}] 本批 {len(batch)} 条 → 新增 {data.get('created', 0)}，重复 {data.get('duplicated', 0)}")

    print(f"\n完成：共新增 {total_created} 条，重复（已存在）{total_dup} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
