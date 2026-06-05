# 资源库后台（backend）

FastAPI + SQLAlchemy 的资源后台，聚焦三件事：

1. **资源/视频入库**：支持单条和批量入库，带去重逻辑。
2. **后台管理**：资源库列表、回收站、筛选方案、分类管理、分类浏览。
3. **下游分发**：批量发送资源到剪片环节（当前支持 stub，占位已就绪）。

## 快速启动

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- 首页：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`

## 数据库配置

仅支持 MySQL（`mysql+pymysql://`）。

### 方式一：直接指定完整 URL（优先级最高）

```bash
export ZIYUANKU_DATABASE_URL="mysql+pymysql://root:password@127.0.0.1:3306/ziyuanku?charset=utf8mb4"
```

### 方式二：分项变量拼接

```bash
export ZIYUANKU_MYSQL_HOST=127.0.0.1
export ZIYUANKU_MYSQL_PORT=3306
export ZIYUANKU_MYSQL_USER=root
export ZIYUANKU_MYSQL_PASSWORD=password
export ZIYUANKU_MYSQL_DB=ziyuanku
export ZIYUANKU_MYSQL_CHARSET=utf8mb4
```

启动前需确保 MySQL 已创建目标库并可连接。

## 核心能力

### 1) 资源入库（`/api/resources`）

- 支持单条 / 批量入库。
- 去重依据：`file_hash`（若未提供，会按 `file_path` 文件内容计算 SHA-256）。
- 支持批量发送：`POST /api/resources/batch-send`。

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/resources \
  -H "Content-Type: application/json" \
  -d '{"file_path":"/abs/path/a.jpg","media_type":"image","source_account":"demo","caption":"..."}'
```

### 2) 视频库（`/api/videos`）

- 入库去重：优先按 `code`，否则按 `source_url`。
- 支持下载状态上报、批量改状态、批量分类、批量导出 CSV、回收站删除/恢复/彻底删除。
- 支持封面处理：单条补封面、批量补封面、单条去水印、批量去水印（后台任务 + 状态查询）。

示例：

```bash
# 单条
curl -X POST http://127.0.0.1:8000/api/videos \
  -H "Content-Type: application/json" \
  -d '{"title":"TWAV-D001","code":"TWAV-D001","url":"https://missav.ai/...","cover":"https://.../cover.jpg"}'

# 批量
curl -X POST http://127.0.0.1:8000/api/videos \
  -H "Content-Type: application/json" \
  -d @twav_videos.json
```

### 3) 分类能力（`/api/video-categories`）

- 分类树查询、同步预设分类、新增/编辑/删除分类。
- 视频与分类绑定、解绑、覆盖设置。

### 4) 本地媒体同步（`/api/sync/local`）

扫描仓库 `data/`，将本地媒体同步到数据库（当前包含 MissAV/Pornhub 视频源）。

```bash
cd backend
python3 sync_local.py
# 或 API
curl -X POST http://127.0.0.1:8000/api/sync/local
```

## 页面路由

- `/`：概览
- `/resources`：资源库（含回收站、批量操作）
- `/browse`：分类浏览
- `/category-editor`：分类编辑

`/videos` 已重定向到 `/resources`。

## 下游剪片接口（stub 说明）

`POST /api/resources/batch-send` 已预留真实对接位。  
未配置 `ZIYUANKU_DISPATCH_ENDPOINT` 时，走 stub：仅推进资源状态并记录日志。  
文档到位后，在 `app/services/dispatch.py` 补齐 payload 并配置环境变量即可切换真实调用。

## 目录结构

```text
backend/app/
  config.py
  database.py
  models.py
  schemas.py
  crud.py
  routers/
    pages.py
    resources.py
    videos.py
    video_categories.py
    sync.py
    media.py
  services/
    dispatch.py
    local_sync.py
    cover_gen.py
    watermark.py
  templates/
  static/
```
