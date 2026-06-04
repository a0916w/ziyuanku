# 资源库后台（backend）

FastAPI + SQLite 的资源后台 MVP。三大块：
1. **入库接口** —— 爬虫抓完调 `POST /api/resources` 入库，按**文件哈希**去重。
2. **资源库** —— 浏览/按状态筛选，多选后**批量发送去剪片**（接口文档到位前为 stub）。
3. **爬虫脚本管理** —— 登记脚本、一键运行、查看运行日志。

资源状态机（四态）：`未处理 → 已发送切片 → 切片完毕 → 已发送到项目`

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
