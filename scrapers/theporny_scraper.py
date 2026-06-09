#!/usr/bin/env python3
"""theporny.com 视频列表爬虫。

站点是 Angular 单页应用,列表数据由加密 API 返回:
    POST {base}/sevenVideos?page=N&type=TYPE   -> {"r": "<CryptoJS AES 密文>"}
响应用 CryptoJS AES(OpenSSL salted 格式、MD5 KDF、口令 "xxx")加密,
解密后是视频对象数组(title / id / durationStr / thumbNails 等)。

输出 JSON 兼容 scrapers/push_to_server.py:
    [{"title","code","url","cover","duration","source":"theporny","extra":{...}}, ...]

用法:
    # 抓 type=c0 的第 1~5 页,存到 data/metadata/theporny_c0.json
    python3 scrapers/theporny_scraper.py --type c0 --start 1 --end 5 \
        -o data/metadata/theporny_c0.json

    # 抓完直接推线上(需先 pip 无额外依赖,openssl 用系统自带)
    python3 scrapers/theporny_scraper.py --type c0 --pages 3 -o /tmp/tp.json
    ZIYUANKU_PUSH_PASSWORD=xxxx python3 scrapers/push_to_server.py /tmp/tp.json --source theporny
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

# API 主机(取自站点 main.js 的 httpNames),按顺序尝试
API_BASES = [
    "https://v2.cdn199.com",
    "https://v2.kekecdn.net",
    "https://v2.madou.ws",
    "https://v2.tianmtv.com",
    "https://v2.papapa.biz",
]
SITE = "https://theporny.com"
AES_PASSPHRASE = "xxx"  # 取自 main.js: AES.decrypt(u.r, "xxx")
HEADERS = {
    "Content-Type": "application/json",
    "Origin": SITE,
    "Referer": SITE + "/",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
}


def decrypt(cipher_b64: str) -> str:
    """用系统 openssl 解 CryptoJS AES(OpenSSL salted, aes-256-cbc, md5 KDF)。"""
    proc = subprocess.run(
        ["openssl", "enc", "-d", "-aes-256-cbc", "-md", "md5",
         "-k", AES_PASSPHRASE, "-base64", "-A"],
        input=cipher_b64.encode(), capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("openssl 解密失败: " + proc.stderr.decode(errors="ignore"))
    return proc.stdout.decode("utf-8")


def fetch_page(page: int, vtype: str, timeout: int = 25) -> list[dict]:
    """抓一页,返回解密后的视频对象数组。"""
    path = f"/sevenVideos?page={page}&type={vtype}"
    last_err = None
    for base in API_BASES:
        try:
            resp = requests.post(base + path, headers=HEADERS, json={}, timeout=timeout)
            resp.raise_for_status()
            r = resp.json().get("r")
            if not r:
                last_err = f"{base}: 响应无 r 字段"
                continue
            data = json.loads(decrypt(r))
            if isinstance(data, list):
                return data
            last_err = f"{base}: 解密结果非数组"
        except Exception as e:  # noqa: BLE001
            last_err = f"{base}: {e}"
            continue
    raise RuntimeError(f"第 {page} 页全部主机失败: {last_err}")


def to_item(v: dict) -> dict | None:
    """把 API 视频对象映射成入库字段。"""
    vid = v.get("vId") or v.get("id")
    if not vid:
        return None
    thumbs = v.get("thumbNails") or []
    cover = thumbs[0] if thumbs else None
    tags = [t.strip() for t in (v.get("keywords_gem") or "").split(",") if t.strip()]
    return {
        "title": v.get("title") or v.get("title_en") or vid,
        "code": vid,
        "url": f"{SITE}/video/{vid}",
        "cover": cover,
        "duration": v.get("durationStr") or "",
        "source": "theporny",
        "extra": {
            "title_en": v.get("title_en"),
            "user": v.get("user"),
            "views": v.get("views"),
            "size": v.get("size"),
            "time": v.get("time"),
            "video_type": v.get("videoType"),
            "tags": tags,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="theporny.com 视频列表爬虫")
    parser.add_argument("--type", default="c0", help="列表类型(对应 URL 的 type 参数),默认 c0")
    parser.add_argument("--start", type=int, default=1, help="起始页,默认 1")
    parser.add_argument("--end", type=int, help="结束页(含)。与 --pages 二选一")
    parser.add_argument("--pages", type=int, help="从 start 起抓的页数。与 --end 二选一")
    parser.add_argument("-o", "--output", default="data/metadata/theporny.json", help="输出 JSON 路径")
    parser.add_argument("--sleep", type=float, default=0.8, help="每页间隔秒数,默认 0.8")
    args = parser.parse_args()

    if args.end is None:
        args.end = args.start + (args.pages or 1) - 1
    if args.end < args.start:
        print("[错误] end 不能小于 start", file=sys.stderr)
        return 1

    seen: set[str] = set()
    items: list[dict] = []
    for page in range(args.start, args.end + 1):
        try:
            raw = fetch_page(page, args.type)
        except RuntimeError as e:
            print(f"[警告] {e}", file=sys.stderr)
            continue
        new = 0
        for v in raw:
            it = to_item(v)
            if not it or it["code"] in seen:
                continue
            seen.add(it["code"])
            items.append(it)
            new += 1
        print(f"第 {page} 页:返回 {len(raw)} 条,新增 {new} 条(累计 {len(items)})")
        if page < args.end:
            time.sleep(args.sleep)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成:共 {len(items)} 条 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
