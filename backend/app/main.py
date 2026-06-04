"""资源库后台 FastAPI 入口。

启动：
    cd backend
    uvicorn app.main:app --reload
打开 http://127.0.0.1:8000
"""
import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .database import init_db
from .routers import resources, scripts, pages

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# 建表（create_all 幂等）。模块加载即执行，保证 uvicorn 与测试下表都已就绪。
init_db()

app = FastAPI(title="资源库后台", version="0.1.0")

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(pages.router)
app.include_router(resources.router)
app.include_router(scripts.router)


@app.get("/health", tags=["meta"])
def health():
    return {"ok": True}
