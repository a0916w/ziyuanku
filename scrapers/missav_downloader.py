"""MissAV 视频下载器：从 twav_videos.json 读取链接，用 Playwright 截获 m3u8 流地址，再用 ffmpeg 下载。

用法：
  python3 missav_downloader.py                      # 下载 twav_videos.json 里所有视频
  python3 missav_downloader.py -i twav_videos.json  # 指定 JSON 文件
  python3 missav_downloader.py -o ./videos          # 指定输出目录
"""

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from playwright.sync_api import sync_playwright

M3U8_PATTERN = re.compile(r'https?://[^\s"\']+\.m3u8[^\s"\']*')
DEFAULT_JSON = "twav_videos.json"
DEFAULT_OUTPUT = "./videos"
DEFAULT_CDP_URL = os.getenv("CRAWLER_CDP_URL", "")


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()


def find_m3u8(page, video_url: str, timeout_ms: int = 12000) -> str | None:
    """打开视频页面，拦截网络请求，返回最佳 m3u8 地址。
    监听器必须在 goto 之前注册，否则会错过页面加载时的请求。
    先等到出现分辨率专属 m3u8（如 1280x720/video.m3u8），否则退化为 playlist.m3u8。
    """
    found = []

    def on_request(request):
        url = request.url
        if ".m3u8" in url and url not in found:
            found.append(url)

    page.on("request", on_request)
    try:
        page.goto(video_url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        html = page.content().lower()
        if any(
            marker in html
            for marker in (
                "checking your browser",
                "just a moment",
                "cf-chl",
                "请稍候",
                "verify you are human",
            )
        ):
            raise RuntimeError("页面仍在验证或被 403 拦截，请先在后台验证浏览器中完成验证。")
        # 等候分辨率专属 m3u8 出现，最多 timeout_ms
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            page.wait_for_timeout(300)
            if any(re.search(r'\d+x\d+', u) for u in found):
                break
    finally:
        page.remove_listener("request", on_request)

    if not found:
        return None

    # 优先选分辨率子 m3u8（含 1280x720 等），其次 playlist，最后任意
    for url in found:
        if re.search(r'\d+x\d+', url):
            return url
    for url in found:
        if "playlist" in url:
            return url
    return found[0]


HLS_HEADERS = {
    "Referer": "https://missav.ai/",
    "Origin": "https://missav.ai",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
}


def parse_segments(m3u8_url: str) -> list[str]:
    """下载并解析 m3u8，返回所有分片的绝对 URL 列表。"""
    resp = requests.get(m3u8_url, headers=HLS_HEADERS, timeout=15)
    resp.raise_for_status()
    lines = resp.text.splitlines()
    segments = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            segments.append(urljoin(m3u8_url, line))
    return segments


def download_m3u8(m3u8_url: str, output_path: Path, title: str) -> bool:
    """下载 m3u8 的所有分片（含 .jpeg 伪装），合并后用 ffmpeg 转封装为 mp4。"""
    print(f"  解析分片列表: {m3u8_url[:60]}...")
    try:
        segments = parse_segments(m3u8_url)
    except Exception as e:
        print(f"  [错误] 获取分片列表失败: {e}")
        return False

    if not segments:
        print("  [错误] 未找到任何分片")
        return False

    print(f"  共 {len(segments)} 个分片，开始下载...")

    with tempfile.TemporaryDirectory() as tmpdir:
        concat_file = Path(tmpdir) / "concat.ts"
        sess = requests.Session()
        sess.headers.update(HLS_HEADERS)

        with open(concat_file, "wb") as out:
            for idx, seg_url in enumerate(segments, 1):
                for attempt in range(3):
                    try:
                        r = sess.get(seg_url, timeout=20)
                        r.raise_for_status()
                        out.write(r.content)
                        break
                    except Exception as e:
                        if attempt == 2:
                            print(f"  [警告] 分片 {idx} 下载失败，跳过: {e}")
                if idx % 50 == 0:
                    print(f"  进度: {idx}/{len(segments)}")

        print(f"  分片下载完毕，合并为 mp4...")
        cmd = [
            "ffmpeg", "-y",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  [错误] ffmpeg 合并失败:\n{result.stderr[-600:]}")
            return False

    return True


def main():
    parser = argparse.ArgumentParser(description="MissAV 视频下载器")
    parser.add_argument("-i", "--input", default=DEFAULT_JSON, help="视频列表 JSON 文件")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help="保存目录")
    parser.add_argument("--skip-existing", action="store_true", default=True, help="已存在的文件跳过")
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL, help="后台验证浏览器 CDP 地址")
    args = parser.parse_args()

    videos = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"共 {len(videos)} 个视频，保存到 {output_dir.resolve()}\n")

    # 第一阶段：用浏览器批量获取所有 m3u8 地址
    tasks = []  # [(i, video, out_path, m3u8_url)]
    print("=== 第一阶段：获取 m3u8 地址 ===")
    with sync_playwright() as p:
        connected_over_cdp = bool(args.cdp_url)
        if connected_over_cdp:
            print(f"连接后台验证浏览器: {args.cdp_url}")
            browser = p.chromium.connect_over_cdp(args.cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
        else:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                locale="zh-CN",
            )
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()

        for i, video in enumerate(videos, 1):
            title = video.get("title", video.get("code", f"video_{i}"))
            code = video.get("code", f"V{i:03d}")
            url = video["url"]
            filename = sanitize_filename(f"{code} {title}") + ".mp4"
            out_path = output_dir / filename

            print(f"[{i}/{len(videos)}] {code} - {title[:50]}")

            if args.skip_existing and out_path.exists() and out_path.stat().st_size > 0:
                print("  已存在，跳过")
                continue

            print(f"  获取流地址: {url}")
            m3u8 = find_m3u8(page, url)

            if not m3u8:
                print("  [警告] 未找到 m3u8 地址，跳过")
                continue

            print(f"  m3u8: {m3u8[:80]}...")
            tasks.append((i, video, out_path, m3u8))

        page.close()
        if not connected_over_cdp:
            browser.close()

    # 第二阶段：关闭浏览器后再下载，避免浏览器长时间空置被杀
    print(f"\n=== 第二阶段：下载 {len(tasks)} 个视频 ===")
    for i, video, out_path, m3u8 in tasks:
        title = video.get("title", video.get("code", f"video_{i}"))
        code = video.get("code", f"V{i:03d}")
        print(f"\n[{i}/{len(videos)}] {code} - {title[:50]}")
        success = download_m3u8(m3u8, out_path, title)
        if success:
            size_mb = out_path.stat().st_size / 1024 / 1024
            print(f"  完成 ({size_mb:.1f} MB)")

    print(f"\n全部完成，文件保存在 {output_dir.resolve()}")


if __name__ == "__main__":
    main()
