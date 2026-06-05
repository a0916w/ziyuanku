# 视频入库 API 文档

把爬虫/外部采集到的视频信息写入资源库。接口已内置去重，可单条或批量提交。

> 说明：入库能力由后端 `POST /api/videos` 提供（见 `backend/app/routers/videos.py`），
> 本文档描述其请求/响应契约与配套的查询、状态更新接口。

---

## 1. 接入地址

| 环境 | Base URL | 鉴权 |
|------|----------|------|
| 公网（经 Caddy） | `http://13.212.221.77` | HTTP Basic Auth |
| 服务器本机 | `http://127.0.0.1:8000` | 无 |

- 公网入口由 Caddy 反向代理到后端 `127.0.0.1:8000`，**整站启用 HTTP Basic Auth**，调用时需带账号密码。
- 在服务器本机直连 `127.0.0.1:8000` 不需要鉴权，适合内部脚本/爬虫调用。

Basic Auth 示例：

```bash
curl -u admin:<password> http://13.212.221.77/api/videos
```

---

## 2. 视频入库

### `POST /api/videos`

入库单条或批量视频。爬虫抓完即可调用。

- 单条：请求体传一个对象。
- 批量：请求体传一个对象数组。

#### 去重规则

1. 优先按 `code`（番号）去重；
2. `code` 为空或未命中时，按 `source_url` 去重。

命中去重时**不会新建**，而是按需更新已有记录：

- 若 `file_path` 指向的本地文件存在，则更新 `file_path`，并把下载状态置为 `done`、进度 100；
- `title` / `cover_url` / `cover_path` / `video_url` / `duration` 有变化时一并更新。

#### 请求字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string | 是 | 视频标题 |
| `code` | string | 否 | 番号；提供时作为首选去重键 |
| `source_url` | string | 二选一 | 详情页链接 |
| `url` | string | 二选一 | 详情页链接（`source_url` 的别名，二者至少提供一个） |
| `cover_url` | string | 否 | 封面图 URL |
| `cover` | string | 否 | 封面图 URL（`cover_url` 的别名） |
| `cover_path` | string | 否 | 封面图本地路径（文件存在才会写入） |
| `duration` | string | 否 | 时长，如 `00:12:34` |
| `video_url` | string | 否 | 视频流地址（m3u8 等） |
| `file_path` | string | 否 | 本地下载文件路径；文件存在时自动判定为已下载 |
| `download_status` | string | 否 | `pending` / `downloading` / `done` / `failed` |
| `source` | string | 否 | 来源站点标识，默认 `missav` |
| `extra` | object | 否 | 其它自定义元数据（如 `note`、`tags`） |

> 兼容性：`url` 与 `source_url`、`cover` 与 `cover_url` 互为别名，传任一即可；
> 但 `source_url`/`url` 至少要有一个，否则返回 422。

#### 响应

```json
{
  "created": 1,
  "duplicated": 0,
  "ids": [12]
}
```

| 字段 | 说明 |
|------|------|
| `created` | 本次新建条数 |
| `duplicated` | 命中去重（已存在）的条数 |
| `ids` | 涉及的视频 id 列表（新建 + 命中，顺序与请求一致） |

#### 示例

单条入库：

```bash
curl -X POST http://127.0.0.1:8000/api/videos \
  -H "Content-Type: application/json" \
  -d '{
    "title": "示例标题",
    "code": "ABC-123",
    "source_url": "https://example.com/abc-123",
    "cover": "https://example.com/abc-123.jpg",
    "duration": "00:18:00",
    "source": "missav"
  }'
```

批量入库：

```bash
curl -X POST http://127.0.0.1:8000/api/videos \
  -H "Content-Type: application/json" \
  -d '[
    {"title": "A", "code": "AAA-001", "url": "https://example.com/a"},
    {"title": "B", "code": "BBB-002", "url": "https://example.com/b"}
  ]'
```

公网调用（带 Basic Auth）：

```bash
curl -X POST http://13.212.221.77/api/videos \
  -u admin:<password> \
  -H "Content-Type: application/json" \
  -d '{"title":"示例","url":"https://example.com/x"}'
```

---

## 3. 配套接口

### `GET /api/videos` — 视频列表

查询参数（均可选）：

| 参数 | 类型 | 说明 |
|------|------|------|
| `source` | string | 按来源站点过滤 |
| `download_status` | string | 按下载状态过滤 |
| `category_id` | int | 按内容分类过滤 |
| `uncategorized` | bool | 仅未分类 |
| `keyword` | string | 标题/番号/链接模糊搜索 |
| `trash_only` | bool | 仅回收站 |
| `limit` | int | 返回条数上限，默认 200 |

### `GET /api/videos/{id}` — 视频详情

返回单条 `VideoOut`，不存在返回 404。

### `GET /api/videos/stats` — 下载状态统计

```json
{
  "counts": {"pending": 10, "downloading": 1, "done": 5, "failed": 0},
  "labels": {"pending": "待下载", "downloading": "下载中", "done": "已完成", "failed": "失败"},
  "order": ["pending", "downloading", "done", "failed"]
}
```

### `PATCH /api/videos/{id}/download` — 更新下载状态

请求体：

```json
{
  "download_status": "done",
  "download_progress": 100,
  "file_path": "/home/ziyuanku/data/media/abc-123.mp4",
  "video_url": "https://.../index.m3u8",
  "download_error": null
}
```

- `download_status` 必填；其余可选。
- 置为 `done` 时自动把进度补到 100、记录完成时间、清空错误。

---

## 4. 字段与枚举参考

### 下载状态 `download_status`

| 值 | 含义 |
|----|------|
| `pending` | 待下载 |
| `downloading` | 下载中 |
| `done` | 已完成 |
| `failed` | 失败 |

### 视频对象 `VideoOut`（响应）

`id`、`code`、`title`、`cover_url`、`cover_path`、`cover_clean_path`、`source_url`、
`duration`、`video_url`、`file_path`、`download_status`、`download_status_label`、
`download_progress`、`download_error`、`downloaded_at`、`source`、`extra`、
`created_at`、`updated_at`。

---

## 5. 错误码

| 状态码 | 场景 |
|--------|------|
| `200` | 成功 |
| `401` | 公网入口未带/带错 Basic Auth |
| `404` | 指定视频不存在（详情/更新） |
| `422` | 请求体校验失败（如缺少 `source_url`/`url`） |
