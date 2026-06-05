"""Browser verification session API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import browser_session

router = APIRouter(prefix="/api/browser", tags=["browser"])


class BrowserUrlIn(BaseModel):
    url: str = Field(default=browser_session.DEFAULT_TARGET_URL)


@router.get("/status", summary="浏览器验证会话状态")
def browser_status():
    return browser_session.status().as_dict()


@router.post("/start", summary="启动验证浏览器")
def start_browser(payload: BrowserUrlIn):
    try:
        return browser_session.start(payload.url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc


@router.post("/open-tab", summary="在验证浏览器打开指定 tab")
def open_browser_tab(payload: BrowserUrlIn):
    try:
        return browser_session.open_tab(payload.url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc


@router.post("/check-verified", summary="检查验证是否已完成")
def check_browser_verified(payload: BrowserUrlIn):
    return browser_session.check_verified(payload.url)


@router.post("/stop", summary="停止验证浏览器")
def stop_browser():
    try:
        return browser_session.stop()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc
