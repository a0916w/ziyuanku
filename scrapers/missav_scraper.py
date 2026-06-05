"""MissAV 列表页爬虫：抓取指定列表页的视频元数据（标题/链接/封面/时长/番号）。

放在仓库根，按本项目爬虫脚本约定运行：python3 missav_scraper.py
结果落盘为 JSON，可后续接入资源库入库。
"""
import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# 配置
BASE_URL = "https://missav.ai"
START_URL = "https://missav.ai/dm31/en/twav"
DEFAULT_OUTPUT = "data/metadata/twav_videos.json"
DEFAULT_CDP_URL = os.getenv("CRAWLER_CDP_URL", "")


def parse_video_list(soup):
    """从页面解析所有视频信息。"""
    videos = []
    items = soup.select('div.thumbnail.group')

    for item in items:
        try:
            link = item.select_one('a')
            if not link:
                continue

            title_tag = item.select_one('div.my-2.text-sm.text-nord4.truncate a')
            title = title_tag.get_text(strip=True) if title_tag else "未知标题"
            url = urljoin(BASE_URL, link.get('href'))

            img = item.select_one('img')
            cover = urljoin(BASE_URL, img.get('src') or img.get('data-src', '')) if img else ""

            duration_tag = item.select_one('div.absolute.bottom-1.right-1')
            duration = duration_tag.get_text(strip=True) if duration_tag else ""

            videos.append({
                "title": title,
                "url": url,
                "cover": cover,
                "duration": duration,
                "code": url.split('/')[-1].upper(),
            })
        except Exception:
            continue

    return videos


def get_next_page(soup):
    """获取下一页链接。"""
    next_link = soup.select_one('a[rel="next"]')
    if next_link:
        return urljoin(BASE_URL, next_link.get('href'))
    return None


def is_blocked_page(html: str) -> bool:
    text = html.lower()
    return any(
        marker in text
        for marker in (
            "checking your browser",
            "just a moment",
            "cf-chl",
            "cloudflare",
            "verify you are human",
            "请稍候",
            "验证",
        )
    )


def main(max_pages=10, save_to=DEFAULT_OUTPUT, start_url=START_URL, cdp_url=DEFAULT_CDP_URL):
    all_videos = []

    with sync_playwright() as p:
        connected_over_cdp = bool(cdp_url)
        if connected_over_cdp:
            print(f"连接后台验证浏览器: {cdp_url}")
            browser = p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
        else:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                locale="zh-CN",
                extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
            )
            # 隐藏 webdriver 特征
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()
        current_url = start_url
        page_num = 1

        while current_url and page_num <= max_pages:
            print(f"正在爬取: {current_url}")
            page.goto(current_url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            if is_blocked_page(page.content()):
                raise RuntimeError("页面仍在验证或被 403 拦截，请先在后台验证浏览器中完成验证。")
            # 等待视频卡片加载
            page.wait_for_selector('div.thumbnail.group', timeout=15000)

            soup = BeautifulSoup(page.content(), 'html.parser')
            videos = parse_video_list(soup)
            all_videos.extend(videos)
            print(f"第 {page_num} 页爬取完成，共 {len(videos)} 个视频")

            current_url = get_next_page(soup)
            page_num += 1
            time.sleep(1.5)

        page.close()
        if not connected_over_cdp:
            browser.close()

    Path(save_to).parent.mkdir(parents=True, exist_ok=True)
    with open(save_to, 'w', encoding='utf-8') as f:
        json.dump(all_videos, f, ensure_ascii=False, indent=2)

    print(f"\n爬取完成！共 {len(all_videos)} 个视频，已保存到 {save_to}")
    return all_videos


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MissAV 列表页爬虫")
    parser.add_argument("--start-url", default=START_URL, help="起始列表页")
    parser.add_argument("--max-pages", type=int, default=10, help="最多采集页数")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help="输出 JSON 文件")
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL, help="后台验证浏览器 CDP 地址")
    args = parser.parse_args()
    main(
        max_pages=args.max_pages,
        save_to=args.output,
        start_url=args.start_url,
        cdp_url=args.cdp_url,
    )
