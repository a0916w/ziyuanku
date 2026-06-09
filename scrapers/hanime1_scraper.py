#!/usr/bin/env python3
"""hanime1.me 搜索列表爬虫。

站点有 Cloudflare 防护,curl/无头浏览器会被 403。本脚本用 Playwright **有头** Chrome
(住宅 IP + 真实浏览器可过 Cloudflare),加载搜索页后用 BeautifulSoup 解析卡片。

搜索页:https://hanime1.me/search?genre=<类型>&page=<页>
卡片结构:
    <a href=".../watch?v=ID">
      <img src=".../image/cover/ID.jpg...">
      <div class="home-rows-videos-title">标题</div>
    </a>

输出 JSON 兼容 scrapers/push_to_server.py:
    [{"title","code","url","cover","source":"hanime1","extra":{...}}, ...]

用法:
    python3 scrapers/hanime1_scraper.py --genre 裏番 --start 1 --end 3 \
        -o data/metadata/hanime1_uncensored.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlparse, parse_qs

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

SITE = "https://hanime1.me"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def search_url(genre: str, page: int) -> str:
    return f"{SITE}/search?genre={quote(genre)}&page={page}"


def is_blocked(title: str, html: str) -> bool:
    bad = ("Attention Required", "Just a moment", "Cloudflare")
    return any(s in title for s in bad) or any(s in html[:3000] for s in bad)


def parse_cards(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    seen: set[str] = set()
    for a in soup.select('a[href*="watch?v="]'):
        href = a.get("href", "")
        qs = parse_qs(urlparse(href).query)
        vid = (qs.get("v") or [None])[0]
        if not vid or vid in seen:
            continue
        title_el = a.select_one(".home-rows-videos-title")
        title = title_el.get_text(strip=True) if title_el else None
        if not title:
            continue  # 跳过非视频卡片(分页、推荐位等)
        img = a.select_one("img")
        cover = img.get("src") if img else None
        seen.add(vid)
        items.append({
            "title": title,
            "code": vid,
            "url": f"{SITE}/watch?v={vid}",
            "cover": cover,
            "source": "hanime1",
            "extra": {},
        })
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="hanime1.me 搜索列表爬虫")
    parser.add_argument("--genre", default="裏番", help="类型(对应 URL 的 genre),默认 裏番")
    parser.add_argument("--start", type=int, default=1, help="起始页,默认 1")
    parser.add_argument("--end", type=int, help="结束页(含)。与 --pages 二选一")
    parser.add_argument("--pages", type=int, help="从 start 起抓的页数。与 --end 二选一")
    parser.add_argument("-o", "--output", default="data/metadata/hanime1.json", help="输出 JSON 路径")
    parser.add_argument("--sleep", type=float, default=1.5, help="每页间隔秒数,默认 1.5")
    parser.add_argument("--headless", action="store_true", help="无头模式(通常会被 Cloudflare 拦,默认有头)")
    args = parser.parse_args()

    if args.end is None:
        args.end = args.start + (args.pages or 1) - 1
    if args.end < args.start:
        print("[错误] end 不能小于 start", file=sys.stderr)
        return 1

    all_items: list[dict] = []
    seen: set[str] = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=args.headless, channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(locale="zh-TW", user_agent=UA)
        page = ctx.new_page()
        for n in range(args.start, args.end + 1):
            url = search_url(args.genre, n)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            html = ""
            for _ in range(20):  # 等 Cloudflare 验证通过
                page.wait_for_timeout(1500)
                html = page.content()
                if not is_blocked(page.title(), html):
                    break
            if is_blocked(page.title(), html):
                print(f"第 {n} 页:仍被 Cloudflare 拦截,跳过", file=sys.stderr)
                continue
            cards = parse_cards(html)
            new = 0
            for it in cards:
                if it["code"] in seen:
                    continue
                seen.add(it["code"])
                all_items.append(it)
                new += 1
            print(f"第 {n} 页:解析 {len(cards)} 张卡片,新增 {new}(累计 {len(all_items)})")
            if n < args.end:
                time.sleep(args.sleep)
        browser.close()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成:共 {len(all_items)} 条 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
