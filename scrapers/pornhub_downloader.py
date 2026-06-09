"""Pornhub 视频下载器：从 JSON 列表读取链接，用 Playwright 解析 HLS 地址，ffmpeg 保存到本地。

用法：
  python3 pornhub_scraper.py "https://cn.pornhub.com/model/sweetie-fox" --max-pages 20
  python3 pornhub_downloader.py -i sweetie_fox_videos.json -o ./downloads/sweetie-fox

  # 爬取并下载（先抓列表再逐个下载）
  python3 pornhub_downloader.py --scrape "https://cn.pornhub.com/model/sweetie-fox" --max-pages 20 -o ./downloads/sweetie-fox
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import BrowserContext, Page, sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
DEFAULT_JSON = "sweetie_fox_videos.json"
DEFAULT_OUTPUT = "./downloads/pornhub"


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()[:180]


def cookie_header(context: BrowserContext) -> str:
    return "; ".join(f"{c['name']}={c['value']}" for c in context.cookies())


def dismiss_age_gate(page: Page) -> None:
    for sel in (
        "button#ageVerify",
        "button.ageGate",
        'button:has-text("18")',
        'button:has-text("进入")',
        'button:has-text("Enter")',
    ):
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible(timeout=1500):
                btn.click()
                page.wait_for_timeout(1500)
                return
        except Exception:
            continue


def _pick_best_variant(master_text: str, master_url: str) -> str:
    """从 master.m3u8 中选取最高带宽的子播放列表 URL。"""
    base = master_url.rsplit("/", 1)[0] + "/"
    best_bw = -1
    best_url = None
    lines = master_text.strip().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXT-X-STREAM-INF"):
            m = re.search(r"BANDWIDTH=(\d+)", line)
            bw = int(m.group(1)) if m else 0
            i += 1
            while i < len(lines) and (not lines[i].strip() or lines[i].startswith("#")):
                i += 1
            if i < len(lines):
                seg = lines[i].strip()
                full = seg if seg.startswith("http") else urljoin(base, seg)
                if bw >= best_bw:
                    best_bw = bw
                    best_url = full
        i += 1
    return best_url or master_url


def get_hls_url(page: Page, video_url: str, timeout_ms: int = 15000) -> str | None:
    """打开视频页，从 flashvars 取最高清 HLS 子播放列表地址。"""
    page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
    dismiss_age_gate(page)

    deadline = time.time() + timeout_ms / 1000
    flashvars = None
    while time.time() < deadline:
        flashvars = page.evaluate(
            """() => {
                const k = Object.keys(window).find(x => x.startsWith('flashvars_'));
                if (k) return window[k];
                return window.flashvars || null;
            }"""
        )
        if flashvars and flashvars.get("mediaDefinitions"):
            break
        page.wait_for_timeout(400)

    if not flashvars:
        return None

    hls_items = [x for x in flashvars.get("mediaDefinitions", []) if x.get("format") == "hls"]
    if not hls_items:
        return None

    best = max(hls_items, key=lambda x: x.get("height", 0) or 0)
    master = (best.get("videoUrl") or "").replace("\\/", "/")
    if not master:
        return None

    try:
        playlist = page.evaluate(
            """async (url) => {
                const r = await fetch(url);
                return { text: await r.text(), finalUrl: r.url };
            }""",
            master,
        )
    except Exception:
        return master

    text = playlist.get("text") or ""
    final_url = playlist.get("finalUrl") or master
    if "#EXT-X-STREAM-INF" in text:
        return _pick_best_variant(text, final_url)
    return final_url


def download_hls(
    m3u8_url: str,
    output_path: Path,
    cookies: str,
    referer: str,
) -> bool:
    """用 ffmpeg 下载 HLS 流为 mp4。"""
    headers = (
        f"Referer: {referer}\r\n"
        f"User-Agent: {USER_AGENT}\r\n"
        f"Cookie: {cookies}\r\n"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-headers",
        headers,
        "-i",
        m3u8_url,
        "-c",
        "copy",
        "-bsf:a",
        "aac_adtstoasc",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        print(f"  [错误] ffmpeg 失败:\n{err[-600:]}")
        return False
    return output_path.exists() and output_path.stat().st_size > 0


def download_all(
    videos: list[dict],
    output_dir: Path,
    skip_existing: bool = True,
    limit: int | None = None,
) -> tuple[int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if limit:
        videos = videos[:limit]

    ok, fail = 0, 0
    print(f"共 {len(videos)} 个视频，保存到 {output_dir.resolve()}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(user_agent=USER_AGENT, locale="zh-CN")
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()
        cookies = cookie_header(context)

        for i, video in enumerate(videos, 1):
            title = video.get("title", f"video_{i}")
            vkey = video.get("vkey", f"v{i}")
            url = video["url"]
            referer = f"{urlparse(url).scheme}://{urlparse(url).netloc}/"
            filename = sanitize_filename(f"{vkey} {title}") + ".mp4"
            out_path = output_dir / filename

            print(f"[{i}/{len(videos)}] {title[:60]}")

            if skip_existing and out_path.exists() and out_path.stat().st_size > 1024:
                print("  已存在，跳过")
                ok += 1
                continue

            print(f"  解析流地址: {url}")
            try:
                m3u8 = get_hls_url(page, url)
                cookies = cookie_header(context)
            except Exception as e:
                print(f"  [警告] 解析失败: {e}")
                fail += 1
                continue

            if not m3u8:
                print("  [警告] 未找到 HLS 地址，跳过")
                fail += 1
                continue

            print(f"  m3u8: {m3u8[:90]}...")
            if download_hls(m3u8, out_path, cookies, referer):
                size_mb = out_path.stat().st_size / 1024 / 1024
                print(f"  完成 ({size_mb:.1f} MB)")
                ok += 1
            else:
                fail += 1
                if out_path.exists():
                    out_path.unlink(missing_ok=True)

            time.sleep(2)

        browser.close()

    return ok, fail


def main():
    parser = argparse.ArgumentParser(description="Pornhub 视频下载器")
    parser.add_argument("-i", "--input", default=DEFAULT_JSON, help="视频列表 JSON")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help="保存目录")
    parser.add_argument("--no-skip-existing", action="store_true", help="不跳过已存在文件")
    parser.add_argument("--limit", type=int, default=None, help="只下载前 N 个（调试用）")
    parser.add_argument(
        "--scrape",
        metavar="URL",
        help="先爬取模特列表再下载（等同 pornhub_scraper + 下载）",
    )
    parser.add_argument("--max-pages", type=int, default=20, help="--scrape 时最多爬取页数")
    parser.add_argument(
        "--json-output",
        default=DEFAULT_JSON,
        help="--scrape 时列表 JSON 保存路径",
    )
    args = parser.parse_args()

    if args.scrape:
        from pornhub_scraper import scrape

        videos = scrape(args.scrape, max_pages=args.max_pages, save_to=args.json_output)
    else:
        path = Path(args.input)
        if not path.exists():
            print(f"找不到列表文件: {path}")
            print("请先运行: python3 pornhub_scraper.py")
            raise SystemExit(1)
        videos = json.loads(path.read_text(encoding="utf-8"))

    if not videos:
        print("视频列表为空")
        raise SystemExit(1)

    ok, fail = download_all(
        videos,
        Path(args.output),
        skip_existing=not args.no_skip_existing,
        limit=args.limit,
    )
    print(f"\n全部完成: 成功 {ok}, 失败 {fail}, 目录 {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
