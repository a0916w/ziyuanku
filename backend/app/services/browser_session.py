"""Manage the server-side Chrome session used for manual verification and CDP crawling."""
from __future__ import annotations

import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

from ..config import BASE_DIR

REPO_ROOT = BASE_DIR.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
START_SCRIPT = SCRIPTS_DIR / "start-browser-session.sh"
STOP_SCRIPT = SCRIPTS_DIR / "stop-browser-session.sh"
DEFAULT_TARGET_URL = "https://missav.ai/dm31/en/twav"
CDP_URL = os.getenv("ZIYUANKU_CDP_URL", "http://127.0.0.1:9222")
NOVNC_URL = os.getenv("ZIYUANKU_NOVNC_URL", "http://127.0.0.1:6080/vnc.html")
VNC_PASSWORD_FILE = Path(
    os.getenv("ZIYUANKU_VNC_PASSWORD_FILE", str(REPO_ROOT / "data/browser-profiles/.vnc-password.txt"))
)

BLOCKED_MARKERS = (
    "checking your browser",
    "just a moment",
    "cf-chl",
    "cloudflare",
    "verify you are human",
    "security verification",
    "请稍候",
    "验证",
)


@dataclass(frozen=True)
class BrowserStatus:
    cdp_url: str
    novnc_url: str
    cdp_available: bool
    browser: str | None = None
    tabs: list[dict] | None = None
    error: str | None = None
    vnc_password: str | None = None
    novnc_available: bool = False
    vnc_available: bool = False

    def as_dict(self) -> dict:
        return {
            "cdp_url": self.cdp_url,
            "novnc_url": self.novnc_url,
            "cdp_available": self.cdp_available,
            "browser": self.browser,
            "tabs": self.tabs or [],
            "error": self.error,
            "vnc_password": self.vnc_password,
            "novnc_available": self.novnc_available,
            "vnc_available": self.vnc_available,
        }


def _request_json(path: str, timeout: float = 2.0):
    resp = requests.get(f"{CDP_URL}{path}", timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _novnc_port() -> tuple[str, int]:
    parsed = urlparse(NOVNC_URL)
    return parsed.hostname or "127.0.0.1", parsed.port or (443 if parsed.scheme == "https" else 80)


def vnc_password() -> str | None:
    if os.getenv("ZIYUANKU_VNC_PASSWORD"):
        return os.getenv("ZIYUANKU_VNC_PASSWORD")
    try:
        if VNC_PASSWORD_FILE.exists():
            return VNC_PASSWORD_FILE.read_text(encoding="utf-8").splitlines()[0].strip()
    except Exception:
        return None
    return None


def status() -> BrowserStatus:
    novnc_host, novnc_port = _novnc_port()
    novnc_available = _port_open(novnc_host, novnc_port)
    vnc_available = _port_open("127.0.0.1", int(os.getenv("VNC_PORT", "5901")))
    try:
        version = _request_json("/json/version")
        tabs = _request_json("/json/list")
        return BrowserStatus(
            cdp_url=CDP_URL,
            novnc_url=NOVNC_URL,
            cdp_available=True,
            browser=version.get("Browser"),
            vnc_password=vnc_password(),
            novnc_available=novnc_available,
            vnc_available=vnc_available,
            tabs=[
                {
                    "id": tab.get("id"),
                    "title": tab.get("title"),
                    "url": tab.get("url"),
                    "type": tab.get("type"),
                }
                for tab in tabs
                if tab.get("type") == "page"
            ],
        )
    except Exception as exc:  # noqa: BLE001
        return BrowserStatus(
            cdp_url=CDP_URL,
            novnc_url=NOVNC_URL,
            cdp_available=False,
            error=str(exc),
            vnc_password=vnc_password(),
            novnc_available=novnc_available,
            vnc_available=vnc_available,
        )


def start(target_url: str | None = None) -> dict:
    if not START_SCRIPT.exists():
        raise RuntimeError(f"启动脚本不存在：{START_SCRIPT}")
    env = os.environ.copy()
    env.setdefault("PROJECT_DIR", str(REPO_ROOT))
    env["TARGET_URL"] = target_url or DEFAULT_TARGET_URL
    proc = subprocess.run(
        ["bash", str(START_SCRIPT)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "启动浏览器失败").strip())
    current = status()
    deadline = time.monotonic() + 8
    while not current.cdp_available and time.monotonic() < deadline:
        time.sleep(0.5)
        current = status()
    return {"ok": True, "output": proc.stdout.strip(), **current.as_dict()}


def stop() -> dict:
    if not STOP_SCRIPT.exists():
        raise RuntimeError(f"停止脚本不存在：{STOP_SCRIPT}")
    env = os.environ.copy()
    env.setdefault("PROJECT_DIR", str(REPO_ROOT))
    proc = subprocess.run(
        ["bash", str(STOP_SCRIPT)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "停止浏览器失败").strip())
    return {"ok": True, "output": proc.stdout.strip(), **status().as_dict()}


def open_tab(url: str) -> dict:
    if not status().cdp_available:
        start(url)
    try:
        resp = requests.put(f"{CDP_URL}/json/new?{quote(url, safe='')}", timeout=5)
        if resp.status_code == 405:
            resp = requests.get(f"{CDP_URL}/json/new?{quote(url, safe='')}", timeout=5)
        resp.raise_for_status()
        tab = resp.json()
        return {"ok": True, "tab": tab, **status().as_dict()}
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"打开 tab 失败：{exc}") from exc


def check_verified(url: str | None = None) -> dict:
    current = status()
    if not current.cdp_available:
        return {
            "verified": False,
            "reason": "CDP 不可用，请先启动验证浏览器。",
            **current.as_dict(),
        }
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        return {
            "verified": False,
            "reason": "后台环境缺少 playwright，无法自动检查页面验证状态。",
            **current.as_dict(),
        }

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            pages = context.pages
            page = None
            if url:
                page = next((item for item in pages if url in item.url), None)
            page = page or (pages[-1] if pages else context.new_page())
            if url and not page.url.startswith(url):
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            html = page.content().lower()
            title = page.title()
            page_url = page.url
            blocked = any(marker in html for marker in BLOCKED_MARKERS)
    except Exception as exc:  # noqa: BLE001
        return {
            "verified": False,
            "reason": f"CDP 可用，但 Playwright 无法连接这个浏览器：{exc}",
            **status().as_dict(),
        }

    refreshed = status().as_dict()
    return {
        "verified": not blocked,
        "reason": "已通过验证，可以运行采集。" if not blocked else "页面仍像验证页，请在浏览器中完成验证后再检查。",
        "page": {"title": title, "url": page_url},
        **refreshed,
    }


def command_requires_cdp(command: str) -> bool:
    lower = command.lower()
    return "missav" in lower and "--cdp-url" in lower
