# Changelog

本项目所有重要修改都记录在此文件。
遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- 资源库新增“回收站”能力：
  - 批量删除改为软删除（进入回收站）。
  - 新增批量恢复与批量彻底删除接口：`/api/videos/batch/restore`、`/api/videos/batch/purge`。
  - 资源页新增“资源库 / 回收站”视图切换。
- 资源库新增“筛选方案”：
  - 支持保存、应用、删除筛选方案（本地存储 localStorage）。
- 资源库页面增强（编辑 + 多选 + 批量）：
  - 新增多选能力（全选/反选）与批量操作：批量改状态、批量改分类、批量导出 CSV、批量删除。
  - 新增单条编辑弹窗：可编辑标题、番号、来源、时长、链接、封面、备注、标签、分类。
  - 新增后端接口：`PATCH /api/videos/{id}`、`POST /api/videos/batch/update-status`、`POST /api/videos/batch/update-categories`、`POST /api/videos/batch/export`、`POST /api/videos/batch/delete`。
- 资源库补封面功能：
  - 新增 `POST /api/videos/{id}/generate-cover`：从本地视频截帧生成封面图。
  - 新增 `POST /api/videos/batch-generate-cover` + `GET /api/videos/batch-generate-cover/status`：批量补封面（后台队列 + 进度查询）。
  - 新增 `backend/app/services/cover_gen.py`，基于 `ffmpeg` 生成封面。
- 资源库页面增强：
  - 新增“批量补封面图”按钮与单条“补封面”操作。
  - 新增关键词搜索（标题/番号/source_url）并支持与来源、状态筛选联动。
- 后端新增 MySQL 支持：
  - `backend/app/config.py` 支持通过 `ZIYUANKU_DATABASE_URL` 或 `ZIYUANKU_MYSQL_*` 环境变量切换 MySQL。
  - `backend/requirements.txt` 增加 `pymysql` 依赖。
- 新增 SQLite -> MySQL 迁移脚本：`backend/migrate_sqlite_to_mysql.py`（按表迁移，默认先清空目标库）。
- `backend/README.md` 补充 MySQL 配置与迁移使用说明。
- 资源库后台 MVP 骨架（`backend/`，FastAPI + SQLAlchemy + SQLite + Jinja2）：
  - **入库接口** `POST /api/resources`：单条/批量入库，按**文件哈希**去重（同一文件只入一次）。
  - **资源库** `/resources`：网格列表 + 按状态筛选；多选后**批量发送去剪片**按钮。
  - **批量发送** `POST /api/resources/batch-send`：下游剪片接口为 **stub** 占位（未配置 `ZIYUANKU_DISPATCH_ENDPOINT` 时仅本地推进状态），接口文档到位后在 `services/dispatch.py` 接真实调用。
  - **爬虫脚本管理** `/scripts`：登记脚本、一键运行（子进程）、记录运行状态与日志。
  - 资源状态机（四态）：未处理 → 已发送切片 → 切片完毕 → 已发送到项目。
  - 概览页状态计数卡片、API 文档 `/docs`、健康检查 `/health`。
  - 端到端冒烟测试通过：入库/去重/批量发送/状态推进/脚本登记/页面渲染/静态资源。
- `.gitignore` 增加后台运行时数据（`backend/data/`、`*.db`）排除规则。

### Changed
- 为兼容 MySQL `utf8mb4` 索引长度限制，将 `videos.source_url` 列长度从 `1024` 调整为 `512`（仍保留索引）。
- 记录已确认的关键决策（2026-06-05）于 `资源库需求.md`：
  - 批量分发：通过下游接口发送，后台以按钮触发（接口文档待提供，先留对接位）。
  - 去重依据：按文件内容哈希去重。
  - 资源状态机（四态）：未处理 → 已发送切片 → 切片完毕 → 已发送到项目。
- 更新需求文档的"待明确 / 已解决"清单。

### Added
- 初始化 git 仓库并接入 GitHub 远程（硬指标：版本控制 + GitHub）。
- 新增 `.gitignore`：排除机密（`cookies.json`、令牌）、大体积媒体（`downloads/`）、Python 缓存。
- 新增 `CHANGELOG.md`：建立"每次修改必有 changelog"的工程规范。
- 安装 BMAD-METHOD v6.8.0（core + bmm 模块，44 个 skill，中文交流/文档）。
- 新增 `资源库需求.md`：记录资源库 / 资源后台项目需求与硬指标。

### 现有基础（接管前已存在）
- `ig_downloader.py`：基于 instaloader 的 Instagram 图片/Story 下载脚本。
- `requirements.txt`、`usernames.txt`：依赖与目标账号清单。
