#!/usr/bin/env python3
"""xchina.co 视频列表爬虫(系列/分类/列表页通用)。

站点有 Cloudflare 防护,curl/无头会被 403。用 Playwright 有头 Chrome 加载后用
BeautifulSoup 解析卡片。

列表页 URL 形如:
    https://xchina.co/videos/series-<id>/<页>.html
卡片结构:
    <div class="item video">
      <a href="/video/id-XXXX.html" title="标题">
        <div class="img" style="background-image:url('https://img.xchina.download/cover/XXXX.webp')"></div>
      </a>
      <div class="text"><div class="title"><a>标题</a></div>
        <div class="model-item">模特</div></div>
      <div class="tags"><div>分类</div>...<div><i class="fa-clock"></i>时长</div></div>
    </div>

输出 JSON 兼容 scrapers/push_to_server.py:
    [{"title","code","url","cover","duration","source":"xchina","extra":{...}}, ...]

用法:
    python3 scrapers/xchina_scraper.py "https://xchina.co/videos/series-61bf6e439fed6/1.html" \
        --pages 3 -o data/metadata/xchina_series.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

SITE = "https://xchina.co"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def page_url(sample: str, page: int) -> str:
    """把列表 URL 末尾的 /<num>.html 换成目标页码。"""
    if re.search(r"/\d+\.html$", sample):
        return re.sub(r"/\d+\.html$", f"/{page}.html", sample)
    # 没有页码后缀时,page=1 用原 URL
    return sample


def is_blocked(title: str, html: str) -> bool:
    bad = ("Attention Required", "Just a moment", "Cloudflare")
    return any(s in title for s in bad) or any(s in html[:3000] for s in bad)


def parse_cards(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    seen: set[str] = set()
    for item in soup.select("div.item.video"):
        a = item.select_one('a[href*="/video/id-"]')
        if not a:
            continue
        href = a.get("href", "")
        m = re.search(r"/video/id-([a-z0-9]+)\.html", href)
        if not m:
            continue
        vid = m.group(1)
        if vid in seen:
            continue
        title_el = item.select_one(".title a") or a
        title = (a.get("title") or title_el.get_text(strip=True) or "").strip()
        if not title:
            continue
        # 封面:.img 的 background-image
        cover = None
        img = item.select_one(".img")
        if img and img.get("style"):
            mc = re.search(r"url\(['\"]?([^'\")]+)['\"]?\)", img["style"])
            if mc:
                cover = mc.group(1)
        model = None
        model_el = item.select_one(".model-item")
        if model_el:
            model = model_el.get_text(strip=True)
        # 时长:.tags 内带 fa-clock 的格子
        duration = ""
        for d in item.select(".tags div"):
            if d.select_one("i.fa-clock") or d.select_one("i.far.fa-clock"):
                duration = re.sub(r"\s+", "", d.get_text(strip=True))
                break
        category = None
        tags_first = item.select_one(".tags > div")
        if tags_first and not tags_first.select_one("i"):
            category = tags_first.get_text(strip=True)
        seen.add(vid)
        items.append({
            "title": title,
            "code": vid,
            "url": urljoin(SITE, href),
            "cover": cover,
            "duration": duration,
            "source": "xchina",
            "extra": {"model": model, "category": category},
        })
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="xchina.co 视频列表爬虫")
    parser.add_argument("url", help="列表页 URL(第 1 页即可,形如 .../series-<id>/1.html)")
    parser.add_argument("--start", type=int, default=1, help="起始页,默认 1")
    parser.add_argument("--end", type=int, help="结束页(含)。与 --pages 二选一")
    parser.add_argument("--pages", type=int, help="从 start 起抓的页数。与 --end 二选一")
    parser.add_argument("-o", "--output", default="data/metadata/xchina.json", help="输出 JSON 路径")
    parser.add_argument("--sleep", type=float, default=1.5, help="每页间隔秒数,默认 1.5")
    parser.add_argument("--headless", action="store_true", help="无头(通常被 CF 拦,默认有头)")
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
        ctx = browser.new_context(locale="zh-CN", user_agent=UA)
        page = ctx.new_page()
        for n in range(args.start, args.end + 1):
            url = page_url(args.url, n)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            html = ""
            for _ in range(20):
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
            if not cards:
                print(f"第 {n} 页无卡片,可能已到末页,停止", file=sys.stderr)
                break
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
