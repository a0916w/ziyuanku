# Changelog

本项目所有重要修改都记录在此文件。
遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- 新增 `tools/dewatermark.py`:视频 URL 文字水印检测 + 像素化打码工具。用 EasyOCR 每 N 帧(默认 5)采样一次,识别命中 URL 正则(含常见 TLD 白名单,覆盖 `.com/.net/.xxx/.tv/.cc` 等任意 `name.tld` 组合)的文本框,对该区域做像素化(可调 `--pixel-size`),并把识别到的 bbox 沿用到接下来的中间帧——这样既能处理固定水印、也能跟上浮动水印的近距离移动。OpenCV 写无音轨临时 mp4,最后用 ffmpeg 把原视频音轨 mux 回去并加 `+faststart`(可选 `--reencode-h264` 输出 H.264 提高兼容性)。输出文件加 `_clean` 后缀,**不覆盖原文件**。配套 `tools/requirements.txt`(easyocr/opencv-python/numpy),与 backend/根目录依赖解耦,避免把 PyTorch 重依赖塞进后端 venv。
- `scrapers/theporny_downloader.py` 新增 `--push` 一键推送线上入库:下载完成后把成功条目映射成入库 item,直接调用 `/api/videos` 批量入库,**无需写中转 JSON、无需再单独跑 `push_to_server.py`**。密码读环境变量 `ZIYUANKU_PUSH_PASSWORD`(免交互);缺密码时立即报错退出,不会阻塞等待 — 适合无人值守 cron / 后台脚本板块。配套参数:`--push-server` / `--push-user` / `--push-batch-size` / `--push-insecure`。
- `scrapers/push_to_server.py` 抽出可复用的 `push_items(items, *, server, user, password, ...)` 函数与 `PushError` 异常,CLI 行为对外完全兼容;`theporny_downloader.py` 等下游脚本可直接 import 复用推送逻辑。

### Fixed
- `backend/app/services/crawler_runner.py` 子进程 `stdin` 改为 `subprocess.DEVNULL`:之前后台跑爬虫子进程时 stdin 仍指向继承环境,脚本里只要调 `getpass.getpass()` / `input()`(例如旧版 `push_to_server.py`、`ig_downloader.py`),就会一直阻塞到超时(下载类默认 24 小时)才被杀。改为 DEVNULL 后,这类交互调用会立即 EOF / 抛错 → 当场失败、当场暴露,后台脚本板块再也不会因为缺密码挂在那 24 小时。
- 修复 `scrapers/theporny_downloader.py` 下载的 mp4 在 macOS Finder/QuickTime 与浏览器中"打不开"的问题:ffmpeg 合并 m3u8 时把 `moov` 原子留到了文件末尾(非 fast-start),播放器读不到索引就放弃。ffmpeg 命令补 `-movflags +faststart`,`moov` 改放到 `ftyp` 之后、`mdat` 之前,既能秒开也能边下边播。同步对 `data/theporny/` 下已有 mp4(`GQiBF6DGwU.mp4`、`ZszdKvYgw.mp4`)做了一次零损耗 remux,布局已转为 fast-start。

### Added
- 新增 `scrapers/xchina_scraper.py`：xchina.co 视频列表爬虫(系列/分类页通用)。该站有 Cloudflare 防护，用 Playwright 有头 Chrome 加载 + BeautifulSoup 解析 `.item.video` 卡片，产出兼容 `push_to_server.py` 的 JSON（番号/标题/详情链接/封面/时长/模特/分类）。按 URL 末尾页码自动翻页。
- 新增 `scrapers/hanime1_downloader.py`：hanime1.me 视频下载器。用有头 Chrome 进 watch 详情页过 Cloudflare，解析 `<source>` 多清晰度 mp4 直链（CDN 无 CF，requests 流式下载）+ og 元信息，保存视频、封面、完整文字信息（标题/简介/标签/番组/上传者/观看数/上传日期/时长）到 `data/hanime1/{id}/`。支持 `--ids`/`--from-json`/`--quality`/`--no-video`。
- 新增 `scrapers/hanime1_scraper.py`：hanime1.me 搜索列表爬虫。该站有 Cloudflare 防护，curl/无头会被 403，脚本用 Playwright **有头** Chrome（住宅 IP 可过 CF）加载搜索页 + BeautifulSoup 解析卡片，产出兼容 `push_to_server.py` 的 JSON（番号/标题/详情链接/封面）。支持 `--genre`/`--start`/`--end` 翻页。
- 新增 `scrapers/theporny_downloader.py`：theporny.com 视频下载器。调详情接口（`POST /sevenVideos/{id}`，同样 AES 解密）拿到 m3u8 播放地址，用 ffmpeg 下载视频，并保存封面图与完整文字信息到 `data/theporny/{id}/`（`{id}.mp4` / `cover.jpg` / `info.json`）。`theporny_scraper.py` 配套新增 `fetch_detail()`。
- 新增 `scrapers/theporny_scraper.py`：theporny.com 视频列表爬虫。该站为 Angular SPA，列表走加密 API（`POST {base}/sevenVideos?page&type` 返回 CryptoJS AES 密文，口令 `xxx`），脚本直接调接口 + openssl 解密，无需浏览器，产出兼容 `push_to_server.py` 的 JSON（含番号/标题/封面/时长/标签）。
- 新增本机推送脚本 `scrapers/push_to_server.py`：在本机跑爬虫（住宅 IP + 真实浏览器可过 MissAV 的 Cloudflare），把产出的视频 JSON 批量推送到线上 `POST /api/videos` 入库（按 code/source_url 去重）。
  - 直接兼容爬虫 JSON 字段（`url`/`cover`），支持 `--source` 指定来源、basic auth（`--user`/`--password` 或环境变量 `ZIYUANKU_PUSH_PASSWORD`）、`--batch-size` 分批、`--dry-run` 预演。
  - 默认剥掉本机绝对路径字段（`cover_path`/`file_path`，服务器上无意义），可用 `--keep-local-paths` 保留。
  - 说明：因服务器机房 IP 无法通过 MissAV 的 Cloudflare 验证，采集改为「本机执行 → 推送线上入库」。
- 爬虫板块加回「验证浏览器（VNC）」会话，用于让 MissAV 过 Cloudflare：
  - 恢复 `services/browser_session.py`、`routers/browser.py`（`/api/browser/status|start|open-tab|check-verified|stop`）、`scripts/start-browser-session.sh`、`scripts/stop-browser-session.sh`。
  - 脚本页恢复「验证浏览器」面板与对应前端逻辑（启动/打开 Tab/检查验证/停止 + noVNC 链接与 VNC 密码展示）；MissAV 运行前校验 CDP 是否就绪。
  - MissAV 内置命令改回经 `--cdp-url http://127.0.0.1:9222` 复用验证浏览器；`scrapers/missav_*` 增加 `CRAWLER_HEADLESS` 开关与 Cloudflare 等待重试。
  - 说明：经实测该服务器机房 IP 下，纯无头/有头+xvfb 自动化均无法通过 MissAV 的 Cloudflare 交互验证，需经 noVNC 人工验证一次后复用会话。
- 重新加入「爬虫脚本」板块（轻量版，不含浏览器 VNC 会话）：
  - 新增脚本管理后台页 `/scripts` 与导航入口，支持脚本分类、登记/编辑/启停/删除、一键运行、运行日志查看与运行记录，运行中页面自动刷新。
  - 新增 API：`/api/scripts`（增删改查/同步/运行/运行记录）、`/api/script-categories`（分类增删改查）、`/api/runs/recent`（最近运行轮询）。
  - 恢复模型 `ScriptCategory/CrawlScript/CrawlRun`（表 `script_categories/crawl_scripts/crawl_runs`，由 `create_all` 自动建表）、相关 `crud`、`schemas`，以及 `services/crawler_runner`（子进程后台运行）与 `services/script_registry`（内置脚本登记）。
  - 恢复 `scrapers/`（missav/pornhub/instagram 采集与下载脚本、`cover_download` 等）及 `beautifulsoup4`、`playwright` 依赖。

### Removed
- **[BREAKING]** 完全移除「资源（resources）」模块（仅保留视频 videos）：
  - 删除资源入库/列表/批量发送接口 `POST|GET /api/resources`、`POST /api/resources/batch-send`。
  - 删除资源文件预览接口 `GET /api/media/resource/{id}`。
  - 删除 `Resource` 模型、四态状态机常量，及 `ResourceIn/ResourceOut/IngestResult/BatchSendIn` 等 schema。
  - 删除 `routers/resources.py`、`services/dispatch.py`，并移除 `crud` 中资源读写函数。
  - 移除 `services/local_sync.py` 中的 Instagram 资源同步逻辑（保留 MissAV/Pornhub 视频同步）。
  - 移除仅服务于剪片分发的 `ZIYUANKU_DISPATCH_ENDPOINT` / `ZIYUANKU_DISPATCH_TOKEN` 配置。
  - 数据库删除 `resources` 表。

### Fixed
- 修复视频库表格「番号」列文字溢出、与「标题」列挤在一起的问题:番号列加宽并用等宽字体 + 省略号截断。

### Changed
- 视频库筛选区改版:把「视图/搜索/方案/来源/状态」筛选控件与操作工具栏合并为一张白色「控制面板」卡片(中间用分隔线区隔),不再浮在灰底上;并统一控制面板到表格之间的间距;样式缓存版本升至 `style.css?v=18`。
- 视频库表格排版优化:微调来源/时长/状态/进度/操作等列宽,来源首字母大写、时长等宽数字、标题加粗,操作区链接行距更舒适;样式缓存版本升至 `style.css?v=17`。
- 后台界面整体视觉升级（更专业的设计风格）：引入设计变量(配色/圆角/阴影)，顶栏改为浅色玻璃质感并带品牌标识，统计卡、筛选区、工具栏、表格(粘性表头+行悬停)、状态徽章(带状态圆点)、按钮与输入框(聚焦高亮)统一打磨；样式缓存版本 `style.css?v=15`。
- API 文档（`/docs` 与 `/openapi.json`）改为只暴露视频入库接口 `POST /api/videos`，其余接口仍正常工作但不在文档展示；并为入库请求体补充 sample 示例参数。
- 视频库页面路由由 `/resources` 改名为 `/videos`（导航、首页、筛选方案等链接同步更新）；保留 `/resources → /videos` 的隐藏重定向，旧链接不失效。
- 后端数据库改为仅支持 MySQL：
  - 移除 `backend/app/config.py` 中 SQLite 回退与本地 SQLite 自动迁移逻辑。
  - 移除 `backend/app/database.py` 中 SQLite 专用建表补丁逻辑。
  - 删除 `backend/migrate_sqlite_to_mysql.py` 迁移脚本。
  - 更新 `backend/README.md` 数据库说明为 MySQL-only。

### Added
- 新增视频入库 API 文档 `docs/视频入库API.md`：聚焦 `POST /api/videos` 入库接口，含请求字段、去重与更新规则，附单条/批量/去重命中/已下载等完整请求与 JSON 响应示例、下载状态枚举、Python/Shell 集成示例及错误响应样例。
- 下线爬虫模块：
  - 前台移除“爬虫脚本”导航与概览中的脚本运行区块。
  - 后端取消挂载脚本/运行记录/浏览器验证相关路由。
  - 启动流程不再同步爬虫脚本。
  - 删除 `scrapers/` 下爬虫脚本与对应后端脚本管理文件。
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
- 清理爬虫下线后的残留实现：
  - 删除后端 `models`/`schemas`/`crud` 中已不再使用的脚本管理模型与读写逻辑。
  - 删除前端 `app.js` 中失效的 `/api/scripts`、`/api/browser`、`/api/runs` 调用代码块。
  - 移除 `backend/requirements.txt` 中爬虫残留依赖（`beautifulsoup4`、重复的 `playwright`）。
- 重写 `backend/README.md`，与当前实际能力对齐（资源/视频/分类/同步/分发），并移除已下线脚本管理内容。

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
