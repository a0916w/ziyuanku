#!/usr/bin/env python3
"""Telegram 频道资源下载器(基于 Telethon / MTProto)。

抓指定频道(公开 / 私有都支持)的全部历史消息 + 所有附件,首次跑全量、
后续靠 state.json 自动增量,断点续传不重复下载。

输出结构
--------
data/tg/{channel_slug}_{channel_id}/
    info.json         频道元信息(标题/用户名/原始引用/参与人数)
    state.json        增量游标(last_message_id, total_seen, last_run_at)
    messages.jsonl    每条消息一行 JSON(id/date/text/媒体类型/转发源/回复/...)
    media/            所有下载下来的媒体文件
        {msg_id}.{ext}       照片/视频/语音/动画:消息 id + 推断扩展名
        {msg_id}_{name}      文档:保留原文件名,前缀消息 id 防重名

凭证(必读)
-----------
脚本不在仓库里保存任何登录信息。首次运行前:

1. 在 https://my.telegram.org 自助申请 api_id 和 api_hash(免费,几分钟)。
2. 推荐设环境变量(写到 ~/.zshrc / ~/.bashrc):
       export TG_API_ID=123456
       export TG_API_HASH=0123456789abcdef0123456789abcdef
   也可以临时用 CLI: --api-id 123456 --api-hash xxx

3. 首次执行会要求交互输入:手机号 → 短信/TG 内验证码 → 两步验证密码(若开)。
   登录成功后 session 文件保存到 ~/.ziyuanku/tg/{label}.session,后续自动复用、
   免再次登录。**session 文件含登录态,千万别拷给别人、别 commit 进仓库**。

用法
----
    python3 scrapers/tg_downloader.py --channel "https://t.me/+xxxxxxxx"
    python3 scrapers/tg_downloader.py --channel @somepublic --limit 100
    python3 scrapers/tg_downloader.py --channels-file scrapers/tg_channels.txt
    python3 scrapers/tg_downloader.py --channel xxx --metadata-only   # 只记 jsonl
    python3 scrapers/tg_downloader.py --channel xxx --force-full      # 忽略 state

依赖
----
    pip install telethon
    (或 pip install -r scrapers/requirements_tg.txt)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Telethon 是新依赖。导入失败时不让脚本崩,先把异常存着、--help 仍可看,
# 真要 run 才提示装包。
_TELETHON_IMPORT_ERROR: Exception | None = None
try:
    from telethon import TelegramClient, errors
    from telethon.tl.functions.messages import CheckChatInviteRequest
    from telethon.tl.types import (
        ChatInviteAlready,
        ChatInvite,
        DocumentAttributeAudio,
        DocumentAttributeFilename,
        DocumentAttributeVideo,
        MessageMediaDocument,
        MessageMediaPhoto,
        PeerChannel,
    )
except ImportError as _e:  # noqa: BLE001
    _TELETHON_IMPORT_ERROR = _e


REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = REPO_ROOT / "data" / "tg"
SESSION_DIR = Path.home() / ".ziyuanku" / "tg"
DEFAULT_SESSION = "default"


# ---------------- 频道引用解析 ----------------

INVITE_RE = re.compile(
    r"(?:t\.me|telegram\.me)/(?:\+|joinchat/)(?P<hash>[A-Za-z0-9_-]+)"
)
USERNAME_RE = re.compile(r"^@?(?P<name>[A-Za-z][A-Za-z0-9_]{3,31})$")
TME_USERNAME_RE = re.compile(r"t\.me/(?P<name>[A-Za-z][A-Za-z0-9_]{3,31})/?$")


def parse_channel_ref(ref: str) -> dict:
    """把用户输入归一化成 {kind: invite|username|id, value: ..., raw: ...}"""
    ref = ref.strip()
    if not ref:
        raise ValueError("空的频道引用")
    if re.fullmatch(r"-?\d+", ref):
        return {"kind": "id", "value": int(ref), "raw": ref}
    m = INVITE_RE.search(ref)
    if m:
        return {"kind": "invite", "value": m.group("hash"), "raw": ref}
    m = TME_USERNAME_RE.search(ref)
    if m:
        return {"kind": "username", "value": m.group("name"), "raw": ref}
    m = USERNAME_RE.match(ref)
    if m:
        return {"kind": "username", "value": m.group("name"), "raw": ref}
    raise ValueError(f"无法识别频道引用: {ref}")


def slugify(s: str | None) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "channel"


def read_channels_file(path: Path) -> list[str]:
    refs: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        refs.append(line)
    return refs


# ---------------- 频道 entity 解析 ----------------

async def resolve_channel(client, ref: dict):
    kind = ref["kind"]
    if kind == "id":
        # 频道数字 id 在 Telethon 内部存为正数,加 PeerChannel 包一下
        raw = abs(int(ref["value"]))
        return await client.get_entity(PeerChannel(raw))
    if kind == "username":
        return await client.get_entity(ref["value"])
    if kind == "invite":
        try:
            res = await client(CheckChatInviteRequest(ref["value"]))
        except errors.InviteHashExpiredError as e:
            raise RuntimeError(f"邀请链接已过期: {ref.get('raw')}") from e
        except errors.InviteHashInvalidError as e:
            raise RuntimeError(f"邀请链接无效: {ref.get('raw')}") from e
        if isinstance(res, ChatInviteAlready):
            return res.chat
        if isinstance(res, ChatInvite):
            raise RuntimeError(
                f"账号尚未加入此频道。请先在 Telegram 客户端打开 "
                f"{ref.get('raw')} 加入后再重试。"
            )
        raise RuntimeError(f"无法识别邀请链接返回结果: {type(res).__name__}")
    raise ValueError(f"unknown kind: {kind}")


# ---------------- 消息 → JSON ----------------

def media_kind(msg) -> str:
    if not msg.media:
        return "text"
    if isinstance(msg.media, MessageMediaPhoto):
        return "photo"
    if isinstance(msg.media, MessageMediaDocument):
        doc = msg.media.document
        if not doc:
            return "document"
        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                return "video"
            if isinstance(attr, DocumentAttributeAudio):
                return "voice" if attr.voice else "audio"
        mime = (doc.mime_type or "").lower()
        if mime.startswith("image/"):
            return "photo"
        return "document"
    return type(msg.media).__name__.lower().replace("messagemedia", "") or "other"


def document_filename(msg) -> str | None:
    if not isinstance(msg.media, MessageMediaDocument) or not msg.media.document:
        return None
    for attr in msg.media.document.attributes:
        if isinstance(attr, DocumentAttributeFilename):
            return attr.file_name
    return None


def media_size_bytes(msg) -> int:
    if isinstance(msg.media, MessageMediaDocument) and msg.media.document:
        return int(msg.media.document.size or 0)
    if isinstance(msg.media, MessageMediaPhoto) and msg.media.photo:
        sizes = getattr(msg.media.photo, "sizes", []) or []
        return max((int(getattr(s, "size", 0) or 0) for s in sizes), default=0)
    return 0


def message_to_jsonable(msg) -> dict:
    fwd = msg.forward
    fwd_info = None
    if fwd:
        fwd_info = {
            "date": fwd.date.isoformat() if fwd.date else None,
            "from_id": str(fwd.from_id) if fwd.from_id else None,
            "from_name": fwd.from_name,
            "chat_id": getattr(fwd.chat, "id", None) if fwd.chat else None,
            "post_author": fwd.post_author,
            "channel_post": fwd.channel_post,
        }
    return {
        "id": msg.id,
        "date": msg.date.isoformat() if msg.date else None,
        "text": msg.message or None,
        "media_kind": media_kind(msg),
        "media_size": media_size_bytes(msg),
        "document_filename": document_filename(msg),
        "grouped_id": msg.grouped_id,
        "reply_to_msg_id": (
            getattr(msg.reply_to, "reply_to_msg_id", None) if msg.reply_to else None
        ),
        "views": msg.views,
        "forwards": msg.forwards,
        "edit_date": msg.edit_date.isoformat() if msg.edit_date else None,
        "forward": fwd_info,
    }


# ---------------- 媒体下载 ----------------

_INVALID_FNAME = re.compile(r"[/\\\x00]")


async def download_message_media(client, msg, media_dir: Path, log_prefix: str) -> str | None:
    """下载一条消息的媒体,返回相对仓库根的路径(text 消息或下载失败返回 None)。"""
    if not msg.media or media_kind(msg) == "text":
        return None

    fname = document_filename(msg)
    if fname:
        safe = _INVALID_FNAME.sub("_", fname)
        out_path = media_dir / f"{msg.id}_{safe}"
    else:
        kind = media_kind(msg)
        ext = {
            "photo": ".jpg",
            "video": ".mp4",
            "audio": ".mp3",
            "voice": ".ogg",
        }.get(kind, ".bin")
        out_path = media_dir / f"{msg.id}{ext}"

    if out_path.exists() and out_path.stat().st_size > 0:
        return str(out_path.relative_to(REPO_ROOT))

    size = media_size_bytes(msg)
    last_print = time.time()

    def progress(current: int, total: int) -> None:
        nonlocal last_print
        now = time.time()
        if now - last_print > 1.0 and total:
            pct = current / total * 100
            print(
                f"    {log_prefix} {pct:5.1f}% "
                f"({current / 1048576:.1f}/{total / 1048576:.1f} MB)",
                end="\r",
                flush=True,
            )
            last_print = now

    cb = progress if size > 5 * 1048576 else None
    try:
        await client.download_media(msg, file=str(out_path), progress_callback=cb)
    except errors.FloodWaitError as e:
        print(f"\n    [FloodWait {e.seconds}s] {log_prefix} 等待…", file=sys.stderr)
        await asyncio.sleep(e.seconds + 1)
        await client.download_media(msg, file=str(out_path), progress_callback=cb)

    if out_path.exists() and out_path.stat().st_size > 0:
        size_mb = out_path.stat().st_size / 1048576
        print(f"    {log_prefix} ✓ {out_path.name} ({size_mb:.1f} MB)" + " " * 20)
        return str(out_path.relative_to(REPO_ROOT))
    print(f"    {log_prefix} ✗ 下载失败 / 空文件", file=sys.stderr)
    return None


# ---------------- 输出与状态 ----------------

@dataclass
class ChannelOutput:
    root: Path
    info_path: Path
    state_path: Path
    messages_path: Path
    media_dir: Path


def make_output(channel) -> ChannelOutput:
    label = (
        getattr(channel, "username", None)
        or slugify(getattr(channel, "title", str(channel.id)))
        or str(channel.id)
    )
    root = OUT_ROOT / f"{label}_{channel.id}"
    media_dir = root / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    return ChannelOutput(
        root=root,
        info_path=root / "info.json",
        state_path=root / "state.json",
        messages_path=root / "messages.jsonl",
        media_dir=media_dir,
    )


def load_state(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"  [警告] state.json 损坏,忽略并从头拉: {p}", file=sys.stderr)
            return {}
    return {}


def save_state(p: Path, state: dict) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def write_info(channel, p: Path, raw_ref: str | None) -> None:
    info = {
        "id": channel.id,
        "title": getattr(channel, "title", None),
        "username": getattr(channel, "username", None),
        "raw_ref": raw_ref,
        "broadcast": getattr(channel, "broadcast", None),
        "megagroup": getattr(channel, "megagroup", None),
        "participants_count": getattr(channel, "participants_count", None),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    p.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------- 主流程 ----------------

async def process_channel(
    client,
    ref: dict,
    *,
    limit: int | None,
    metadata_only: bool,
    force_full: bool,
) -> bool:
    raw = ref.get("raw") or str(ref["value"])
    print(f"\n[频道] 解析 {raw}")
    channel = await resolve_channel(client, ref)
    out = make_output(channel)
    write_info(channel, out.info_path, raw)
    title = getattr(channel, "title", "?")
    print(f"  → {title} (id={channel.id}) 输出: {out.root}")

    state = {} if force_full else load_state(out.state_path)
    min_id = int(state.get("last_message_id", 0))
    print(
        f"  起点: min_id={min_id}, limit={limit}, "
        f"模式={'仅元数据' if metadata_only else '元数据+媒体'}"
    )

    count = 0
    max_seen = min_id
    t0 = time.time()
    last_save = t0

    # reverse=True 从老到新拉,min_id 过滤 > min_id 的消息
    with out.messages_path.open("a", encoding="utf-8") as f:
        async for msg in client.iter_messages(
            channel, reverse=True, min_id=min_id, limit=limit
        ):
            try:
                rec = message_to_jsonable(msg)
                media_path = None
                if not metadata_only and msg.media:
                    log = f"#{msg.id} [{rec['media_kind']}]"
                    media_path = await download_message_media(
                        client, msg, out.media_dir, log
                    )
                rec["media_path"] = media_path
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                count += 1
                max_seen = max(max_seen, msg.id)

                now = time.time()
                if now - last_save > 5.0:
                    save_state(
                        out.state_path,
                        {
                            "last_message_id": max_seen,
                            "last_run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "total_seen": state.get("total_seen", 0) + count,
                        },
                    )
                    last_save = now
                if count % 25 == 0:
                    elapsed = now - t0
                    print(
                        f"  进度: 已处理 {count} 条 (到 msg#{max_seen}), 耗时 {elapsed:.1f}s"
                    )
            except errors.FloodWaitError as e:
                print(f"  [FloodWait {e.seconds}s] 等待…", file=sys.stderr)
                await asyncio.sleep(e.seconds + 1)
            except Exception as e:  # noqa: BLE001
                print(
                    f"  [跳过 msg#{msg.id}] {type(e).__name__}: {e}",
                    file=sys.stderr,
                )

    if count > 0:
        save_state(
            out.state_path,
            {
                "last_message_id": max_seen,
                "last_run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "total_seen": state.get("total_seen", 0) + count,
            },
        )
    elif not out.state_path.exists():
        save_state(
            out.state_path,
            {
                "last_message_id": max_seen,
                "last_run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "total_seen": 0,
            },
        )

    print(
        f"  完成: 新增 {count} 条, 最大 msg_id={max_seen}, 耗时 {time.time() - t0:.1f}s"
    )
    return True


# ---------------- CLI ----------------

def collect_refs(args) -> list[dict]:
    refs: list[dict] = []
    if args.channel:
        refs.append(parse_channel_ref(args.channel))
    for r in (args.channels or []):
        refs.append(parse_channel_ref(r))
    if args.channels_file:
        for r in read_channels_file(Path(args.channels_file).expanduser()):
            refs.append(parse_channel_ref(r))
    seen = set()
    uniq: list[dict] = []
    for r in refs:
        key = (r["kind"], str(r["value"]))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


def get_credentials(args) -> tuple[int, str]:
    api_id = args.api_id or os.environ.get("TG_API_ID")
    api_hash = args.api_hash or os.environ.get("TG_API_HASH")
    if not api_id or not api_hash:
        sys.stderr.write(
            "[错误] 缺少 Telegram 凭证。请设置环境变量:\n"
            "       export TG_API_ID=<your_id>\n"
            "       export TG_API_HASH=<your_hash>\n"
            "  或用 --api-id / --api-hash 传入。\n"
            "  在 https://my.telegram.org 自助申请,免费。\n"
        )
        raise SystemExit(2)
    try:
        return int(api_id), str(api_hash)
    except (TypeError, ValueError) as e:
        raise SystemExit(f"[错误] TG_API_ID 必须是整数: {api_id!r}") from e


async def amain(args) -> int:
    if _TELETHON_IMPORT_ERROR is not None:
        sys.stderr.write(
            f"[错误] 缺少依赖 telethon: {_TELETHON_IMPORT_ERROR}\n"
            f"请执行:pip install telethon\n"
        )
        return 2

    refs = collect_refs(args)
    if not refs:
        sys.stderr.write(
            "[错误] 没有频道。用 --channel / --channels / --channels-file 指定\n"
        )
        return 1

    api_id, api_hash = get_credentials(args)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    session_path = SESSION_DIR / f"{args.session}.session"

    client = TelegramClient(str(session_path), api_id, api_hash)
    print(f"连接 Telegram (session: {session_path}) …")
    await client.start()
    me = await client.get_me()
    print(f"已登录: {me.first_name} (@{me.username}, id={me.id})")

    ok = 0
    try:
        for ref in refs:
            try:
                if await process_channel(
                    client,
                    ref,
                    limit=args.limit,
                    metadata_only=args.metadata_only,
                    force_full=args.force_full,
                ):
                    ok += 1
            except KeyboardInterrupt:
                print("\n[中断] 用户取消", file=sys.stderr)
                return 130
            except Exception as e:  # noqa: BLE001
                print(
                    f"[频道异常] {ref.get('raw')}: {type(e).__name__}: {e}",
                    file=sys.stderr,
                )
    finally:
        await client.disconnect()

    print(f"\n完成: {ok}/{len(refs)} 个频道")
    return 0 if ok == len(refs) else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Telegram 频道资源下载器(Telethon)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 scrapers/tg_downloader.py --channel 'https://t.me/+xxxxx'\n"
            "  python3 scrapers/tg_downloader.py --channel @some_channel --limit 100\n"
            "  python3 scrapers/tg_downloader.py --channels-file scrapers/tg_channels.txt\n"
        ),
    )
    parser.add_argument(
        "--channel",
        help="单个频道引用(邀请链接 / @username / 数字 id)",
    )
    parser.add_argument(
        "--channels",
        nargs="+",
        help="多个频道引用(空格分隔)",
    )
    parser.add_argument(
        "--channels-file",
        help="频道列表文件,每行一个引用(# 开头为注释)",
    )
    parser.add_argument(
        "--api-id",
        type=int,
        help="Telegram api_id(默认读环境变量 TG_API_ID)",
    )
    parser.add_argument(
        "--api-hash",
        help="Telegram api_hash(默认读环境变量 TG_API_HASH)",
    )
    parser.add_argument(
        "--session",
        default=DEFAULT_SESSION,
        help="会话标签(默认 default,session 文件:~/.ziyuanku/tg/{label}.session)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="每个频道最多拉多少条新消息(默认全部)",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="只记 messages.jsonl,不下载媒体文件",
    )
    parser.add_argument(
        "--force-full",
        action="store_true",
        help="忽略 state.json,从头全量拉(谨慎:会重复写 jsonl)",
    )
    args = parser.parse_args()

    try:
        return asyncio.run(amain(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
