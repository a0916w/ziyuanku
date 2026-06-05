# 资源库后台（backend）

FastAPI + SQLite 的资源后台 MVP。三大块：
1. **入库接口** —— 爬虫抓完调 `POST /api/videos` 入库（封面、标题、流地址、本地文件等）。
2. **资源库** —— 统一浏览已入库视频，按下载状态筛选，支持封面/本地预览。
3. **爬虫脚本管理** —— 内置脚本自动登记、编辑命令、后台一键运行、查看运行日志。

下载状态：`待下载 → 下载中 → 已完成 / 失败`

## 运行

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000 ，API 文档在 http://127.0.0.1:8000/docs 。

## 入库接口示例

```bash
curl -X POST http://127.0.0.1:8000/api/resources \
  -H "Content-Type: application/json" \
  -d '{"file_path":"/abs/path/a.jpg","media_type":"image","source_account":"vitagennn","caption":"..."}'
```

- 传了 `file_hash` 就直接用；没传则服务端按 `file_path` 的文件内容计算 SHA-256。
- 支持单条对象，也支持对象数组批量入库。

## 视频入库接口

爬虫抓完后调 `POST /api/videos`，按 **code（番号）** 或 **source_url（详情页链接）** 去重。

```bash
# 单条（字段名兼容 twav_videos.json）
curl -X POST http://127.0.0.1:8000/api/videos \
  -H "Content-Type: application/json" \
  -d '{"title":"TWAV-D001 ...","code":"TWAV-D001","url":"https://missav.ai/...","cover":"https://.../cover-t.jpg","duration":"12:34"}'

# 批量：JSON 数组
curl -X POST http://127.0.0.1:8000/api/videos \
  -H "Content-Type: application/json" \
  -d @twav_videos.json
```

可选字段：`video_url`（m3u8 流地址）、`file_path`（本地下载路径）、`source`（来源站点，默认 `missav`）、`extra`（其它元数据）。

列表：`GET /api/videos?source=missav`；详情：`GET /api/videos/{id}`。

下载状态上报（供下载器回调）：

```bash
curl -X PATCH http://127.0.0.1:8000/api/videos/1/download \
  -H "Content-Type: application/json" \
  -d '{"download_status":"downloading"}'
# 完成后：download_status=done, file_path=/abs/path/video.mp4
```

后台页面：**概览**、**资源库**（视频列表与预览）、**爬虫脚本**（管理页 `/scripts`）。`/videos` 已合并到 `/resources`。

### 爬虫脚本管理

- 启动后台时会自动把 `scrapers/` 预设命令同步到数据库（见 `app/services/script_registry.py`）。
- 打开 http://127.0.0.1:8000/scripts ：可**同步内置脚本**、**登记/编辑/停用/删除**、**运行**并查看日志。
- 同一脚本不允许并发运行；下载类命令超时 24 小时，列表爬虫 30 分钟。
- API：`GET/POST /api/scripts`、`POST /api/scripts/sync`、`PATCH/DELETE /api/scripts/{id}`、`POST /api/scripts/{id}/run`。

## 本地数据同步（已下载文件 + 脚本登记）

扫描仓库 `data/` 目录，把 IG 图片/视频入库到 `resources`，MissAV/Pornhub 的 mp4 入库到 `videos`，并把 `scrapers/` 下脚本登记到后台：

```bash
cd backend
python3 sync_local.py
# 或 API：curl -X POST http://127.0.0.1:8000/api/sync/local
```

目录约定：`data/instagram/`、`data/missav/`、`data/pornhub/`；元数据 JSON 在 `data/metadata/`。

## 批量发送（剪片对接）

`POST /api/resources/batch-send`，请求体 `{"resource_ids":[1,2,3]}`。

> ⚠️ 下游剪片接口文档尚未提供。当前为 **stub**：未配置 `ZIYUANKU_DISPATCH_ENDPOINT` 时，
> 仅把资源状态推进到「已发送切片」并记日志，让后台按钮即刻可用。
> 文档到位后，在 `app/services/dispatch.py` 的 `_build_payload` 补齐字段、
> 设置环境变量 `ZIYUANKU_DISPATCH_ENDPOINT`（及可选 `ZIYUANKU_DISPATCH_TOKEN`）即可切到真实调用，无需改动其它代码。

## 目录

```
backend/app/
  config.py        # 配置（数据目录、剪片接口地址等，可用环境变量覆盖）
  database.py      # 引擎/会话/建表
  models.py        # Resource / CrawlScript / CrawlRun + 状态机
  schemas.py       # Pydantic
  crud.py          # 读写 + 去重
  services/
    dispatch.py    # 批量发送去剪片（接口对接位）
    crawler_runner.py  # 子进程运行爬虫脚本
  routers/         # resources / scripts / pages
  templates/       # 服务端渲染页面
  static/          # css + js
```
