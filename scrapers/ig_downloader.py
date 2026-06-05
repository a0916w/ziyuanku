#!/usr/bin/env python3
"""
Instagram photo + story downloader using instaloader.
Usage:
  python3 ig_downloader.py vitagennn
  python3 ig_downloader.py vitagennn --login your_ig_account
  python3 ig_downloader.py vitagennn --cookies cookies.json
  python3 ig_downloader.py --file usernames.txt --cookies cookies.json

cookies.json 格式（从浏览器 DevTools > Application > Cookies 中获取）:
  {
    "sessionid": "...",
    "csrftoken": "...",
    "ds_user_id": "...",
    "mid": "...",
    "ig_did": "..."
  }
"""

import argparse
import json
import sys
import time
import logging
from pathlib import Path
from getpass import getpass
from urllib.parse import unquote

import instaloader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def build_loader(download_dir: Path) -> instaloader.Instaloader:
    return instaloader.Instaloader(
        dirname_pattern=str(download_dir / "{target}"),
        filename_pattern="{date_utc:%Y%m%d_%H%M%S}_{shortcode}",
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        post_metadata_txt_pattern="",
        compress_json=False,
        request_timeout=30,
        sleep=True,
        quiet=False,
        sanitize_paths=True,
    )


def do_login_with_cookies(loader: instaloader.Instaloader, cookies_path: str) -> bool:
    """通过浏览器 Cookie JSON 文件注入会话，无需密码。"""
    try:
        raw = json.loads(Path(cookies_path).read_text(encoding="utf-8"))
    except Exception as e:
        log.error("读取 cookies 文件失败: %s", e)
        return False

    required = {"sessionid", "csrftoken", "ds_user_id"}
    missing = required - raw.keys()
    if missing:
        log.error("cookies.json 缺少必要字段: %s", missing)
        return False

    # URL 解码所有 cookie 值（浏览器复制出来的值可能含 %3A 等编码）
    cookies = {k: unquote(v) for k, v in raw.items()}

    try:
        # 直接写入底层 requests.Session，确保每个请求都携带这些 cookie
        sess = loader.context._session
        for name, value in cookies.items():
            sess.cookies.set(name, value, domain=".instagram.com")

        # 手动标记登录状态
        loader.context.username = f"user_{cookies['ds_user_id']}"
        loader.context._logged_in = True

        log.info("Cookie 注入成功 (ds_user_id=%s)", cookies["ds_user_id"])
        return True
    except Exception as e:
        log.error("Cookie 注入失败: %s", e)
        return False


def do_login(loader: instaloader.Instaloader, username: str, password: str | None) -> bool:
    """Login and cache session. Returns True on success."""
    session_file = Path.home() / ".instaloader" / f"session-{username}"
    session_file.parent.mkdir(exist_ok=True)

    if session_file.exists():
        try:
            loader.load_session_from_file(username, str(session_file))
            log.info("已从缓存恢复登录会话 (%s)", username)
            return True
        except Exception:
            log.info("缓存会话已过期，重新登录...")

    if not password:
        password = getpass(f"请输入 {username} 的 Instagram 密码: ")

    try:
        loader.login(username, password)
        loader.save_session_to_file(str(session_file))
        log.info("登录成功，会话已保存到 %s", session_file)
        return True
    except instaloader.exceptions.BadCredentialsException:
        log.error("账号或密码错误")
        return False
    except instaloader.exceptions.TwoFactorAuthRequiredException:
        code = input("请输入二步验证码: ").strip()
        loader.two_factor_login(code)
        loader.save_session_to_file(str(session_file))
        log.info("二步验证成功")
        return True
    except Exception as e:
        log.error("登录失败: %s", e)
        return False


def download_posts(loader: instaloader.Instaloader, profile: instaloader.Profile, max_posts: int | None) -> None:
    log.info("--- 开始下载帖子 (posts) ---")
    downloaded = skipped = 0
    for post in profile.get_posts():
        if max_posts and downloaded >= max_posts:
            break
        try:
            loader.download_post(post, target=profile.username)
            downloaded += 1
            if downloaded % 10 == 0:
                log.info("帖子已下载 %d 张，稍作停顿...", downloaded)
                time.sleep(3)
        except instaloader.exceptions.InstaloaderException as e:
            log.warning("跳过帖子 %s: %s", post.shortcode, e)
            skipped += 1
    log.info("帖子完成：下载 %d，跳过 %d", downloaded, skipped)


def download_stories(loader: instaloader.Instaloader, profile: instaloader.Profile, download_dir: Path) -> None:
    log.info("--- 开始下载限时动态 (stories) ---")
    if not loader.context.is_logged_in:
        log.warning("未登录，无法下载 stories，跳过")
        return
    try:
        story_dir = download_dir / f"{profile.username}_stories"
        story_dir.mkdir(exist_ok=True)
        loader.dirname_pattern = str(story_dir)
        loader.download_stories(userids=[profile.userid], filename_target=profile.username)
        log.info("Stories 下载完成")
    except instaloader.exceptions.QueryReturnedNotFoundException:
        log.info("@%s 目前没有 stories", profile.username)
    except instaloader.exceptions.InstaloaderException as e:
        log.error("Stories 下载失败: %s", e)
    finally:
        loader.dirname_pattern = str(download_dir / "{target}")


def download_highlights(loader: instaloader.Instaloader, profile: instaloader.Profile, download_dir: Path) -> None:
    log.info("--- 开始下载限时动态精选 (highlights) ---")
    if not loader.context.is_logged_in:
        log.warning("未登录，无法下载 highlights，跳过")
        return
    try:
        highlights = list(loader.get_highlights(profile))
    except instaloader.exceptions.InstaloaderException as e:
        log.error("获取 highlights 列表失败: %s", e)
        return

    if not highlights:
        log.info("@%s 没有 highlights", profile.username)
        return

    log.info("共找到 %d 个 highlight 合集", len(highlights))
    for hl in highlights:
        # Each highlight saved to its own folder: "{username}_highlights/{title}"
        safe_title = hl.title.replace("/", "_").replace("\\", "_").strip() or hl.unique_id
        hl_dir = download_dir / f"{profile.username}_highlights" / safe_title
        hl_dir.mkdir(parents=True, exist_ok=True)
        log.info("  下载 highlight「%s」...", hl.title)
        try:
            loader.dirname_pattern = str(hl_dir)
            for item in hl.get_items():
                loader.download_storyitem(item, target=hl_dir)
        except instaloader.exceptions.InstaloaderException as e:
            log.warning("  highlight「%s」下载失败: %s", hl.title, e)
        time.sleep(1)

    loader.dirname_pattern = str(download_dir / "{target}")
    log.info("Highlights 下载完成")


def process_profile(
    loader: instaloader.Instaloader,
    username: str,
    download_dir: Path,
    max_posts: int | None,
    skip_posts: bool,
    skip_stories: bool,
    skip_highlights: bool,
) -> None:
    log.info("====== @%s ======", username)
    try:
        profile = instaloader.Profile.from_username(loader.context, username)
    except instaloader.exceptions.ProfileNotExistsException:
        log.error("账号 @%s 不存在，跳过", username)
        return
    except instaloader.exceptions.PrivateProfileNotFollowedException:
        log.error("账号 @%s 是私密账号（需登录且已关注），跳过", username)
        return

    log.info("账号: %s | 帖子数: %d | 粉丝: %d", profile.full_name, profile.mediacount, profile.followers)

    if not skip_posts:
        download_posts(loader, profile, max_posts)

    if not skip_stories:
        download_stories(loader, profile, download_dir)

    if not skip_highlights:
        download_highlights(loader, profile, download_dir)


def load_usernames_from_file(path: str) -> list[str]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


def main() -> None:
    parser = argparse.ArgumentParser(description="Instagram 照片 + Stories 下载器")
    parser.add_argument("usernames", nargs="*", help="Instagram 用户名")
    parser.add_argument("-f", "--file", help="从文件读取用户名列表（每行一个）")
    parser.add_argument("-o", "--output", default="./downloads", help="保存目录（默认 ./downloads）")
    parser.add_argument("-n", "--max-posts", type=int, default=None, help="每个账号最多下载多少帖子（默认全部）")
    parser.add_argument("--login", help="你自己的 Instagram 账号（下载 stories 必填）")
    parser.add_argument("--password", help="Instagram 密码（不填则交互式输入）")
    parser.add_argument("--cookies", help="浏览器 Cookie JSON 文件路径（推荐，绕过密码登录封锁）")
    parser.add_argument("--no-posts", action="store_true", help="跳过帖子")
    parser.add_argument("--no-stories", action="store_true", help="跳过当前 stories")
    parser.add_argument("--no-highlights", action="store_true", help="跳过 highlights 精选")
    args = parser.parse_args()

    usernames: list[str] = list(args.usernames)
    if args.file:
        usernames += load_usernames_from_file(args.file)
    if not usernames:
        parser.print_help()
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    loader = build_loader(output_dir)

    if args.cookies:
        do_login_with_cookies(loader, args.cookies)
    elif args.login:
        do_login(loader, args.login, args.password)
    else:
        log.warning("未提供 --login 或 --cookies，将以匿名模式运行（无法下载 stories）")

    for i, username in enumerate(usernames):
        process_profile(
            loader, username, output_dir,
            max_posts=args.max_posts,
            skip_posts=args.no_posts,
            skip_stories=args.no_stories,
            skip_highlights=args.no_highlights,
        )
        if i < len(usernames) - 1:
            time.sleep(5)

    log.info("全部完成，文件保存在 %s", output_dir.resolve())


if __name__ == "__main__":
    main()
