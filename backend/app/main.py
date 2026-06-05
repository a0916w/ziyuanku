"""资源库后台 FastAPI 入口。

启动：
    cd backend
    uvicorn app.main:app --reload
打开 http://127.0.0.1:8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .config import FILES_DIR
from .database import SessionLocal, init_db
from .routers import (
    video_categories, pages, videos, sync, media
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
app.include_router(media.router)
app.include_router(videos.router)
app.include_router(sync.router)
app.include_router(video_categories.router)


@app.get("/health", tags=["meta"], include_in_schema=False)
def health():
    return {"ok": True}


def _collect_refs(node, acc: set[str]) -> None:
    """递归收集 schema 里引用到的 components 名称。"""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                acc.add(value.rsplit("/", 1)[-1])
            else:
                _collect_refs(value, acc)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, acc)


def custom_openapi():
    """API 文档只暴露视频入库接口 POST /api/videos，其余接口照常工作但不在文档展示。"""
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)

    ingest = schema.get("paths", {}).get("/api/videos", {})
    schema["paths"] = {"/api/videos": {"post": ingest["post"]}} if "post" in ingest else {}

    # 仅保留入库接口引用到的 component schemas，保持文档干净
    all_schemas = schema.get("components", {}).get("schemas", {})
    if all_schemas:
        needed: set[str] = set()
        _collect_refs(schema["paths"], needed)
        frontier = set(needed)
        while frontier:
            name = frontier.pop()
            found: set[str] = set()
            _collect_refs(all_schemas.get(name, {}), found)
            new = found - needed
            needed |= new
            frontier |= new
        schema["components"]["schemas"] = {
            k: v for k, v in all_schemas.items() if k in needed
        }

    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
