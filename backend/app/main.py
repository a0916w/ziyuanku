"""资源库后台 FastAPI 入口。

启动：
    cd backend
    uvicorn app.main:app --reload
打开 http://127.0.0.1:8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .config import FILES_DIR
from .database import SessionLocal, init_db
from .routers import (
    resources, video_categories, pages, videos, sync, media
)
from .services.content_category_registry import sync_default_categories

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# 建表（create_all 幂等）。模块加载即执行，保证 uvicorn 与测试下表都已就绪。
init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时同步默认视频分类。"""
    db = SessionLocal()
    try:
        cat_stats = sync_default_categories(db)
        logging.getLogger(__name__).info(
            "视频内容分类已同步：共 %s 个",
            cat_stats.get("total", 0),
        )
    finally:
        db.close()
    yield


app = FastAPI(title="资源库后台", version="0.1.0", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if FILES_DIR.is_dir():
    app.mount("/files", StaticFiles(directory=str(FILES_DIR)), name="files")

app.include_router(pages.router)
app.include_router(resources.router)
app.include_router(media.router)
app.include_router(videos.router)
app.include_router(sync.router)
app.include_router(video_categories.router)


@app.get("/health", tags=["meta"])
def health():
    return {"ok": True}
