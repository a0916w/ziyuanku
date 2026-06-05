"""Pornhub 模特/频道视频列表爬虫：抓取指定页面的视频元数据（标题/链接/封面/时长/观看数）。

放在仓库根，按本项目爬虫脚本约定运行：
  python3 pornhub_scraper.py
  python3 pornhub_scraper.py "https://cn.pornhub.com/model/sweetie-fox" --max-pages 20
  python3 pornhub_downloader.py -i sweetie_fox_videos.json -o ./downloads/sweetie-fox

结果落盘为 JSON；视频文件请用 pornhub_downloader.py 下载到本地。
"""
import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from cover_download import REPO_ROOT, download_covers_for_videos

DEFAULT_JSON = REPO_ROOT / "data" / "metadata" / "sweetie_fox_videos.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)


def normalize_model_url(url: str) -> tuple[str, str]:
    """将模特主页 URL 规范为 /videos 列表页，并返回 (base_origin, videos_url)。"""
    parsed = urlparse(url.strip())
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)

    base = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")

    # /model/name 或 /channels/name 等 → 追加 /videos
    if not path.endswith("/videos"):
        if re.search(r"/(model|channels|users|pornstar)/[^/]+$", path, re.I):
            path = path + "/videos"
        elif path.endswith("/videos/"):
            path = path.rstrip("/")

    videos_url = urljoin(base, path + (f"?{parsed.query}" if parsed.query else ""))
    return base, videos_url


def _list_container(soup: BeautifulSoup):
    """模特真实视频列表容器（排除页面上的推荐/广告视频）。"""
    return (
        soup.select_one(".videoUList")
        or soup.select_one(".mostRecentPornstarVideos")
        or soup.select_one("ul#mostRecentVideosSection")
    )


def parse_video_list(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """从页面解析视频列表（按 viewkey 去重）。"""
    videos = []
    seen: set[str] = set()

    container = _list_container(soup)
    items = container.select("li.pcVideoListItem") if container else soup.select("li.pcVideoListItem")

    for item in items:
        vkey = item.get("data-video-vkey")
        if not vkey:
            link = item.select_one('a[href*="viewkey="]')
            if link:
                m = re.search(r"viewkey=([^&]+)", link.get("href", ""))
                vkey = m.group(1) if m else None
        if not vkey or vkey in seen:
            continue
        seen.add(vkey)

        title_tag = item.select_one("span.title a") or item.select_one("a.linkVideoThumb")
        title = ""
        if title_tag:
            title = title_tag.get("title") or title_tag.get_text(strip=True)
        if not title:
            title = "未知标题"

        video_url = urljoin(base_url, f"/view_video.php?viewkey={vkey}")

        img = item.select_one("img")
        cover = ""
        if img:
            cover = img.get("src") or img.get("data-image") or img.get("data-src") or ""
            if cover and not cover.startswith("http"):
                cover = urljoin(base_url, cover)

        duration_tag = item.select_one("var.duration")
        duration = duration_tag.get_text(strip=True) if duration_tag else ""

        views_tag = item.select_one(".views .value, .videoViews, span.views")
        views = views_tag.get_text(strip=True) if views_tag else ""

        videos.append({
            "title": title,
            "url": video_url,
            "vkey": vkey,
            "cover": cover,
            "duration": duration,
            "views": views,
        })

    return videos


def get_next_page(soup: BeautifulSoup, base_url: str, current_url: str) -> str | None:
    """获取下一页链接。"""
    next_link = soup.select_one('li.page_next a, a.page_next, a[rel="next"]')
    if next_link and next_link.get("href"):
        return urljoin(base_url, next_link["href"])

    # 从当前 URL 推断页码并尝试下一页（部分页面省略 page_next）
    parsed = urlparse(current_url)
    m = re.search(r"[?&]page=(\d+)", parsed.query or "")
    current_page = int(m.group(1)) if m else 1
    next_page = current_page + 1

    # 检查分页里是否存在下一页数字
    page_links = soup.select(".pagination3 a, ul.page_numbers a")
    max_page = current_page
    for a in page_links:
        text = (a.get_text() or "").strip()
        if text.isdigit():
            max_page = max(max_page, int(text))

    if next_page <= max_page:
        base_path = parsed.path
        return urljoin(base_url, f"{base_path}?page={next_page}")

    return None


def dismiss_age_gate(page) -> None:
    """尝试关闭年龄验证弹窗。"""
    selectors = [
        "button#ageVerify",
        "button.ageGate",
        'button:has-text("18")',
        'button:has-text("进入")',
        'button:has-text("Enter")',
        'button:has-text("I am 18")',
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible(timeout=1500):
                btn.click()
                page.wait_for_timeout(1500)
                return
        except Exception:
            continue


def scrape(
    start_url: str,
    max_pages: int = 10,
    save_to: str = "pornhub_videos.json",
) -> list[dict]:
    base_url, videos_url = normalize_model_url(start_url)
    all_videos: list[dict] = []
    seen_keys: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="zh-CN")
        page = context.new_page()
        current_url = videos_url
        page_num = 1

        while current_url and page_num <= max_pages:
            print(f"正在爬取第 {page_num} 页: {current_url}")
            page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
            dismiss_age_gate(page)
            try:
                page.wait_for_selector(
                    ".videoUList li.pcVideoListItem, .mostRecentPornstarVideos li.pcVideoListItem",
                    state="attached",
                    timeout=20000,
                )
            except Exception:
                print("  警告: 未检测到视频列表，可能需登录或页面结构已变")
            page.wait_for_timeout(2000)

            soup = BeautifulSoup(page.content(), "html.parser")
            videos = parse_video_list(soup, base_url)

            new_count = 0
            for v in videos:
                if v["vkey"] not in seen_keys:
                    seen_keys.add(v["vkey"])
                    all_videos.append(v)
                    new_count += 1

            print(f"  本页 {len(videos)} 条，新增 {new_count} 条，累计 {len(all_videos)} 条")

            if new_count == 0 and page_num > 1:
                print("  无新视频，停止分页")
                break

            current_url = get_next_page(soup, base_url, current_url)
            page_num += 1
            time.sleep(1.5)

        browser.close()

    ok, skip = download_covers_for_videos(
        all_videos, source="pornhub", referer=base_url, key_field="vkey",
    )
    print(f"封面下载: 成功 {ok}，跳过 {skip}")

    save_path = Path(save_to)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(all_videos, f, ensure_ascii=False, indent=2)

    print(f"\n爬取完成！共 {len(all_videos)} 个视频，已保存到 {save_path}")
    return all_videos


def main():
    parser = argparse.ArgumentParser(description="Pornhub 模特视频列表爬虫")
    parser.add_argument(
        "url",
        nargs="?",
        default="https://cn.pornhub.com/model/sweetie-fox",
        help="模特主页或 /videos 列表 URL",
    )
    parser.add_argument("--max-pages", type=int, default=10, help="最多爬取页数")
    parser.add_argument(
        "-o", "--output",
        default=str(DEFAULT_JSON),
        help="输出 JSON 路径",
    )
    args = parser.parse_args()

    scrape(args.url, max_pages=args.max_pages, save_to=args.output)


if __name__ == "__main__":
    main()
