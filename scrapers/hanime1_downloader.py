#!/usr/bin/env python3
"""hanime1.me 视频下载器：进 watch 详情页 → 存全部文字信息 + 封面 + 视频。

详情页在 Cloudflare 后,用 Playwright 有头 Chrome 加载并过验证;页面 <source> 标签
直接给出多清晰度 mp4 直链(带签名,CDN 无 CF),用 requests 流式下载即可。

每个视频输出到 data/hanime1/{id}/:
    info.json   —— 标题/简介/标签/番组/上传者/观看数/上传日期/时长/各清晰度直链
    cover.jpg   —— 封面图(og:image 缩略图)
    {id}.mp4    —— 选定清晰度的视频文件

用法:
    python3 scrapers/hanime1_downloader.py --ids 166752 166751
    python3 scrapers/hanime1_downloader.py --from-json data/metadata/hanime1.json --limit 2
    python3 scrapers/hanime1_downloader.py --ids 166752 --quality 1080 --no-video
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

SITE = "https://hanime1.me"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = REPO_ROOT / "data" / "hanime1"


def fetch_watch_html(page, vid: str) -> str:
    page.goto(f"{SITE}/watch?v={vid}", wait_until="domcontentloaded", timeout=60000)
    html = ""
    for _ in range(20):
        page.wait_for_timeout(1500)
        html = page.content()
        t = page.title()
        if "Cloudflare" not in t and "Just a moment" not in t and "Attention Required" not in t:
            break
    return html


def parse_watch(html: str, vid: str) -> dict:
    s = BeautifulSoup(html, "html.parser")

    def meta(prop: str):
        e = s.select_one(f'meta[property="{prop}"]') or s.select_one(f'meta[name="{prop}"]')
        return e.get("content") if e and e.get("content") else None

    # 各清晰度 mp4 直链
    sources = {}
    for src in s.select("source[src]"):
        q = src.get("size") or src.get("label") or ""
        sources[str(q)] = src.get("src")

    title_el = s.select_one("#shareBtn-title") or s.select_one(".video-details-wrapper h3")
    title = (title_el.get_text(strip=True) if title_el else None) or meta("og:title") or vid

    # 标签:第一个一般是番组(#xxx),其余是内容标签
    tag_els = [t.get_text(strip=True) for t in s.select(".single-video-tag")]
    brand = None
    tags = []
    _ui_labels = {"add", "remove", ""}
    for t in tag_els:
        if t.startswith("#"):
            brand = t.lstrip("#")
            continue
        name = re.sub(r"\(\d+\)$", "", t).strip()  # 去掉计数后缀
        if name.lower() in _ui_labels:
            continue  # 跳过 add/remove 等 UI 按钮
        tags.append(name)

    panel = s.select_one(".video-description-panel")
    panel_text = panel.get_text(" ", strip=True) if panel else ""
    views = None
    mv = re.search(r"觀看次數[：:]\s*([\d.]+\s*[萬万]?次)", panel_text)
    if mv:
        views = mv.group(1)
    upload_date = None
    md = re.search(r"(\d{4}-\d{1,2}-\d{1,2})", panel_text)
    if md:
        upload_date = md.group(1)
    cap = s.select_one(".video-caption-text")
    uploader = None
    if cap:
        mu = re.search(r"由(.+?)上[傳传]", cap.get_text(strip=True))
        if mu:
            uploader = mu.group(1)

    return {
        "id": vid,
        "title": title,
        "url": f"{SITE}/watch?v={vid}",
        "description": meta("description") or meta("og:description"),
        "cover": meta("og:image"),
        "duration_sec": int(meta("og:video:duration")) if meta("og:video:duration") else None,
        "brand": brand,
        "tags": tags,
        "uploader": uploader,
        "views": views,
        "upload_date": upload_date,
        "sources": sources,
        "source": "hanime1",
    }


def pick_source(sources: dict, quality: str) -> str | None:
    if not sources:
        return None
    if quality in sources:
        return sources[quality]
    order = sorted(sources.keys(), key=lambda q: int(q) if q.isdigit() else 0, reverse=True)
    return sources[order[0]] if order else None


def download_file(url: str, dest: Path, referer: bool = False) -> bool:
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = SITE + "/"
    try:
        with requests.get(url, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            done = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100 // total
                        print(f"\r    下载 {dest.name}: {pct}% ({done/1048576:.1f}/{total/1048576:.1f} MB)",
                              end="", flush=True)
            if total:
                print()
        return dest.exists() and dest.stat().st_size > 0
    except Exception as e:  # noqa: BLE001
        print(f"\n    [下载失败] {e}", file=sys.stderr)
        return False


def process(page, vid: str, quality: str, with_video: bool) -> bool:
    print(f"[{vid}] 加载详情页…")
    html = fetch_watch_html(page, vid)
    if any(x in html[:3000] for x in ("Attention Required", "Just a moment")):
        print("    [失败] 被 Cloudflare 拦截", file=sys.stderr)
        return False
    info = parse_watch(html, vid)
    out_dir = OUT_ROOT / vid
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    dur = info.get("duration_sec")
    print(f"    标题:{info['title']}")
    print(f"    番组:{info.get('brand')} | 时长:{dur and f'{dur//60}:{dur%60:02d}'} | 清晰度:{list(info['sources'].keys())}")

    if info.get("cover"):
        ok = download_file(info["cover"], out_dir / "cover.jpg")
        print(f"    封面:{'已存' if ok else '失败'}")

    if with_video:
        url = pick_source(info["sources"], quality)
        if not url:
            print("    [警告] 无 mp4 直链", file=sys.stderr)
            return False
        dest = out_dir / f"{vid}.mp4"
        if dest.exists() and dest.stat().st_size > 0:
            print(f"    视频已存在,跳过")
            return True
        if not download_file(url, dest):
            return False
        print(f"    视频已保存:{dest}（{dest.stat().st_size/1048576:.1f} MB）")
    return True


def collect_ids(args) -> list[str]:
    if args.ids:
        return [str(i) for i in args.ids]
    if args.from_json:
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        ids = [str(x.get("code") or x.get("id")) for x in data if (x.get("code") or x.get("id"))]
        return ids[:args.limit] if args.limit else ids
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="hanime1.me 视频下载器")
    parser.add_argument("--ids", nargs="*", help="视频 id 列表(watch?v= 后的数字)")
    parser.add_argument("--from-json", help="从列表 JSON(hanime1_scraper 产出)读取 id")
    parser.add_argument("--limit", type=int, help="配合 --from-json,只取前 N 个")
    parser.add_argument("--quality", default="1080", help="清晰度偏好(1080/720/480),取不到则用最高")
    parser.add_argument("--no-video", action="store_true", help="只下封面+信息,不下视频")
    parser.add_argument("--headless", action="store_true", help="无头(通常被 CF 拦,默认有头)")
    args = parser.parse_args()

    ids = collect_ids(args)
    if not ids:
        print("[错误] 请用 --ids 或 --from-json 指定视频", file=sys.stderr)
        return 1

    ok = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=args.headless, channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(locale="zh-TW", user_agent=UA)
        page = ctx.new_page()
        for vid in ids:
            try:
                if process(page, vid, args.quality, with_video=not args.no_video):
                    ok += 1
            except Exception as e:  # noqa: BLE001
                print(f"    [异常] {e}", file=sys.stderr)
            print()
        browser.close()
    print(f"完成:成功 {ok}/{len(ids)} 部，输出目录 {OUT_ROOT}/")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
