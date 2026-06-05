# 视频入库 API 文档

把爬虫/外部采集到的视频信息写入资源库。接口已内置去重，可单条或批量提交。

> 入库能力由后端 `POST /api/videos` 提供（见 `backend/app/routers/videos.py`）。
> 本文档只描述视频入库接口。

---

## 目录

- [1. 接入地址与鉴权](#1-接入地址与鉴权)
- [2. 视频入库 `POST /api/videos`](#2-视频入库-post-apivideos)
- [3. 字段与枚举参考](#3-字段与枚举参考)
- [4. 集成示例（Python / Shell）](#4-集成示例python--shell)
- [5. 错误码与错误响应](#5-错误码与错误响应)

---

## 1. 接入地址与鉴权

| 环境 | Base URL | 鉴权 |
|------|----------|------|
| 公网（经 Caddy） | `http://13.212.221.77` | HTTP Basic Auth |
| 服务器本机 | `http://127.0.0.1:8000` | 无 |

- 公网入口由 Caddy 反向代理到后端 `127.0.0.1:8000`，**整站启用 HTTP Basic Auth**，调用时需带账号密码。
- 在服务器本机直连 `127.0.0.1:8000` 不需要鉴权，适合内部脚本/爬虫调用（性能也更好，少一层代理）。

公网带鉴权示例：

```bash
# -u 用户名:密码
curl -u admin:lU7qNS8goKMHRWQx10q4N6P http://13.212.221.77/api/videos
```

未带或带错鉴权会返回 `401`：

```bash
curl -i -X POST http://13.212.221.77/api/videos
# HTTP/1.1 401 Unauthorized
# WWW-Authenticate: Basic realm="restricted"
```

所有请求体均为 JSON，需带 `Content-Type: application/json`。时间字段为 UTC、ISO 8601 格式（如 `2026-06-05T12:00:00`）。

---

## 2. 视频入库 `POST /api/videos`

入库单条或批量视频。爬虫抓完即可调用。

- **单条**：请求体传一个 JSON 对象。
- **批量**：请求体传一个 JSON 数组。

### 2.1 请求字段

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `title` | string | 是 | — | 视频标题 |
| `code` | string | 否 | `null` | 番号；提供时作为**首选去重键** |
| `source_url` | string | 二选一 | — | 详情页链接 |
| `url` | string | 二选一 | — | 详情页链接（`source_url` 的别名；二者至少给一个） |
| `cover_url` | string | 否 | `null` | 封面图远程 URL |
| `cover` | string | 否 | `null` | 封面图 URL（`cover_url` 的别名） |
| `cover_path` | string | 否 | `null` | 封面图本地路径（**文件存在才会写入**） |
| `duration` | string | 否 | `null` | 时长，如 `00:12:34` |
| `video_url` | string | 否 | `null` | 视频流地址（m3u8 等） |
| `file_path` | string | 否 | `null` | 本地下载文件路径；**文件存在时自动判定为已下载** |
| `download_status` | string | 否 | 自动推断 | `pending` / `downloading` / `done` / `failed` |
| `source` | string | 否 | `missav` | 来源站点标识 |
| `extra` | object | 否 | `null` | 其它自定义元数据（如 `note`、`tags`） |

字段别名：`url`↔`source_url`、`cover`↔`cover_url`，传任一即可；但 `source_url`/`url` 至少要有一个，否则返回 `422`。

`download_status` 的自动推断：未显式传时，若 `file_path` 指向的文件真实存在 → `done`；否则 → `pending`。

### 2.2 去重与更新规则

1. 优先按 `code` 去重；
2. `code` 为空或未命中时，按 `source_url` 去重。

**命中去重时不会新建**，而是按需更新已有记录：

- 若 `file_path` 指向的本地文件存在：更新 `file_path`，并把下载状态置为 `done`、进度 100、记录完成时间、清空错误；
- `title` / `cover_url` / `cover_path` / `video_url` / `duration` 有变化时一并更新（`cover_path` 同样要求文件存在）。

### 2.3 响应体 `VideoIngestResult`

```json
{
  "created": 1,
  "duplicated": 0,
  "ids": [12]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `created` | int | 本次新建条数 |
| `duplicated` | int | 命中去重（已存在）的条数 |
| `ids` | int[] | 涉及的视频 id 列表（新建 + 命中，顺序与请求一致） |

### 2.4 示例：单条入库

请求：

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

响应 `200`：

```json
{
  "created": 1,
  "duplicated": 0,
  "ids": [12]
}
```

### 2.5 示例：批量入库

请求（注意请求体是数组）：

```bash
curl -X POST http://127.0.0.1:8000/api/videos \
  -H "Content-Type: application/json" \
  -d '[
    {"title": "片名 A", "code": "AAA-001", "url": "https://example.com/a", "cover": "https://example.com/a.jpg"},
    {"title": "片名 B", "code": "BBB-002", "url": "https://example.com/b"},
    {"title": "片名 C", "url": "https://example.com/c", "source": "pornhub"}
  ]'
```

响应 `200`（假设前两条新建、第三条此前已存在）：

```json
{
  "created": 2,
  "duplicated": 1,
  "ids": [13, 14, 9]
}
```

### 2.6 示例：去重命中（重复提交同一 `code`）

第二次提交相同 `code`，只更新不新增：

```bash
curl -X POST http://127.0.0.1:8000/api/videos \
  -H "Content-Type: application/json" \
  -d '{"title": "示例标题（已改名）", "code": "ABC-123", "url": "https://example.com/abc-123"}'
```

响应 `200`：

```json
{
  "created": 0,
  "duplicated": 1,
  "ids": [12]
}
```

此时 id=12 的记录 `title` 已被更新为「示例标题（已改名）」。

### 2.7 示例：入库即标记为已下载

`file_path` 指向的文件存在时，自动置为 `done`、进度 100：

```bash
curl -X POST http://127.0.0.1:8000/api/videos \
  -H "Content-Type: application/json" \
  -d '{
    "title": "已下载的视频",
    "code": "DEF-456",
    "url": "https://example.com/def-456",
    "file_path": "/home/ziyuanku/data/media/def-456.mp4"
  }'
```

### 2.8 示例：公网调用（带 Basic Auth）

```bash
curl -X POST http://13.212.221.77/api/videos \
  -u admin:lU7qNS8goKMHRWQx10q4N6P \
  -H "Content-Type: application/json" \
  -d '{"title":"公网示例","url":"https://example.com/x"}'
```

---

## 3. 字段与枚举参考

### 3.1 下载状态 `download_status`

| 值 | 标签 | 含义 |
|----|------|------|
| `pending` | 待下载 | 默认状态 |
| `downloading` | 下载中 | 进度 0–100 |
| `done` | 已完成 | 进度自动置 100 |
| `failed` | 失败 | 记录失败原因 |

---

## 4. 集成示例（Python / Shell）

### 4.1 Python：爬虫批量入库

```python
import requests

BASE = "http://127.0.0.1:8000"          # 服务器本机直连，无需鉴权
# 公网调用改为：
# BASE = "http://13.212.221.77"
# AUTH = ("admin", "lU7qNS8goKMHRWQx10q4N6P")
AUTH = None

def ingest(items: list[dict]) -> dict:
    """批量入库，items 为入库字段组成的字典列表。"""
    resp = requests.post(f"{BASE}/api/videos", json=items, auth=AUTH, timeout=30)
    resp.raise_for_status()
    return resp.json()

videos = [
    {
        "title": "片名 A",
        "code": "AAA-001",
        "url": "https://example.com/a",
        "cover": "https://example.com/a.jpg",
        "duration": "00:20:00",
        "source": "missav",
    },
    {
        "title": "片名 B",
        "code": "BBB-002",
        "url": "https://example.com/b",
    },
]

result = ingest(videos)
print(result)   # {'created': 2, 'duplicated': 0, 'ids': [13, 14]}
```

### 4.2 Shell：单条入库

```bash
curl -s -X POST http://127.0.0.1:8000/api/videos \
  -H "Content-Type: application/json" \
  -d '{"title":"shell 示例","code":"SH-001","url":"https://example.com/sh-001"}'
```

---

## 5. 错误码与错误响应

| 状态码 | 场景 | 响应体示例 |
|--------|------|------------|
| `200` | 成功 | 见上文各示例 |
| `401` | 公网入口未带/带错 Basic Auth | （由 Caddy 返回，非 JSON） |
| `422` | 请求体校验失败 | 见下 |

`422` 示例：缺少 `source_url`/`url` 时

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "source_url"],
      "msg": "Value error, source_url 或 url 至少提供一个",
      "input": { "title": "缺链接的视频" }
    }
  ]
}
```
