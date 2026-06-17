#!/usr/bin/env python3
"""sexinsex.net 列表爬虫(标签/版块通用)。

站点是 Discuz 7.x 论坛,有 Cloudflare 但内容直出,**不需要 Playwright**,
直接 requests + BeautifulSoup 即可。

注意编码:页面 meta 写 `charset=utf-8` 是**网站 bug**,实际响应是 **GBK**(URL 路径
里 `%CB%D8%C8%CB` 也是 GBK 的"素人"),要手动 `r.encoding = 'gbk'`,否则中文乱码。

列表页支持三种入口(URL 构造完全等价,只选一个即可):

    --tag <名称>          # 例:--tag 素人 → tag.php?name=<gbk_url_encoded>&page=N
    --forum <数字 id>      # 例:--forum 25  → forum-25-N.html
    --url <原始 URL>       # 任意支持分页的列表 URL,翻页时自动改 page 参数

每行 `<tr>` 结构(已侦察):
    <th>             帖子标题  <a href="thread-{tid}-1-1.html">标题</a>
    <td class=icon>  状态图标
    <td class=forum> 所属版块  <a href="forum-{fid}-1.html">版块名</a>
    <td class=author> 楼主 <cite><a href="space-uid-{uid}.html">名</a></cite>
                      <em>发帖时间</em>
    <td class=nums>  <strong>回复数</strong> / <em>查看数</em>
    <td class=lastpost> <em><a href="redirect.php?tid={tid}&goto=lastpost">时间</a></em>
                         <cite><a href="space-username-...">用户</a></cite>

输出 JSON 与 `scrapers/push_to_server.py` 兼容(title/code/url/source 必有,
论坛特有字段塞在 `extra` 里):

    [
      {
        "title": "[BC30] 【维度独家素人系列】...",
        "code": "12943469",                      # tid,论坛内全站唯一
        "url": "https://sexinsex.net/bbs/thread-12943469-1-1.html",
        "source": "sexinsex",
        "cover": null,                            # 论坛列表页不带封面
        "duration": null,
        "extra": {
          "forum_id": "25",
          "forum_name": "Asia Uncensored Section | ...",
          "author": "搬搬哥",
          "author_uid": "16358343",
          "posted_at": "2026-06-13",
          "replies": 12,
          "views": 1234,
          "last_reply_at": "2026-6-13 12:55",
          "last_reply_by": "275622786",
          "tag": "素人",                         # 抓的标签(便于后续过滤)
          "page": 1                              # 哪一页抓到的
        }
      },
      ...
    ]

⚠️ 局限:scraper 只抓**列表元数据**。帖子正文/附件/网盘链接在详情页,而详情页
**需要登录 + 板块金币 ≥ 49** 才能看(实测访问 thread-12943469 的"亚洲无码区"返回
"您无权进行当前操作,访问条件: 金币 > 49")。详情页抓取留给后续的 sexinsex_downloader,
需配合账号 cookie。

用法
----
    python3 scrapers/sexinsex_scraper.py --tag 素人 --start 1 --end 3
    python3 scrapers/sexinsex_scraper.py --forum 25 --pages 5
    python3 scrapers/sexinsex_scraper.py --url 'https://sexinsex.net/bbs/forum-25-1.html' --pages 3
    python3 scrapers/sexinsex_scraper.py --tag 素人 -o data/metadata/sexinsex_suren.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

SITE = "https://sexinsex.net"
BBS = f"{SITE}/bbs"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DEFAULT_OUT = "data/metadata/sexinsex.json"


# ---------------- URL 构造 / 翻页 ----------------

def tag_url(name: str, page: int = 1) -> str:
    """构造 tag 列表页 URL。name 用 GBK URL-encode(站点用的编码)。"""
    encoded = quote(name.encode("gbk"), safe="")
    if page <= 1:
        return f"{BBS}/tag.php?name={encoded}"
    return f"{BBS}/tag.php?name={encoded}&page={page}"


def forum_url(fid: str | int, page: int = 1) -> str:
    """构造 forum 列表页 URL,例如 forum-25-1.html。"""
    return f"{BBS}/forum-{fid}-{page}.html"


def bump_page(sample_url: str, page: int) -> str:
    """把任意列表 URL 的"页码"换成目标值,纯字符串替换,**不解码 query**。

    GBK 编码的 %xx 参数(例如 `name=%CB%D8%C8%CB`)如果走 urlparse/parse_qs,
    会被按 UTF-8 强制解码 → 变成 U+FFFD 替换符,再 urlencode 就成了 %EF%BF%BD…
    因此这里只做规则替换:

    1. `forum-NN-{page}.html` 形式(Discuz rewrite)→ 改中间数字
    2. 查询串已有 `page=N` → 正则替换该段
    3. 都不匹配 → 追加 `&page=N` 或 `?page=N`
    """
    if re.search(r"forum-\d+-\d+\.html", sample_url):
        return re.sub(r"(forum-\d+-)\d+(\.html)", rf"\g<1>{page}\2", sample_url)
    if re.search(r"([?&])page=\d+", sample_url):
        return re.sub(r"([?&])page=\d+", rf"\g<1>page={page}", sample_url)
    sep = "&" if "?" in sample_url else "?"
    return f"{sample_url}{sep}page={page}"


# ---------------- HTTP ----------------

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": f"{BBS}/",
    })
    return s


def fetch_html(sess: requests.Session, url: str, timeout: float = 20.0) -> str:
    r = sess.get(url, timeout=timeout)
    r.raise_for_status()
    # 站点 meta 撒谎说自己是 utf-8,实际是 GBK,这里强制覆盖
    r.encoding = "gbk"
    return r.text


# ---------------- 解析 ----------------

THREAD_HREF_RE = re.compile(r"thread-(\d+)-")
FORUM_HREF_RE = re.compile(r"forum-(\d+)-")
UID_HREF_RE = re.compile(r"space-uid-(\d+)\.html")


def _text(el) -> str:
    return el.get_text(strip=True) if el else ""


def _int_or_none(s: str):
    if s is None:
        return None
    s = s.replace(",", "").strip()
    return int(s) if s.isdigit() else None


def parse_list(html: str, tag: str | None, page: int) -> list[dict]:
    """从列表页 HTML 解出本页所有帖子的元数据。"""
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    table = soup.find("table")
    if not table:
        return items

    for tr in table.find_all("tr"):
        # 帖子行:必有 <th> 里的 thread- 链接
        th = tr.find("th")
        if not th:
            continue
        title_a = th.find("a", href=THREAD_HREF_RE)
        if not title_a:
            continue
        m = THREAD_HREF_RE.search(title_a.get("href", ""))
        if not m:
            continue
        tid = m.group(1)
        title = _text(title_a)
        if not title:
            continue

        # forum
        forum_id = forum_name = None
        td_forum = tr.find("td", class_="forum")
        if td_forum:
            forum_a = td_forum.find("a")
            if forum_a:
                forum_name = _text(forum_a)
                fm = FORUM_HREF_RE.search(forum_a.get("href", ""))
                if fm:
                    forum_id = fm.group(1)

        # author + posted_at
        author = author_uid = posted_at = None
        td_author = tr.find("td", class_="author")
        if td_author:
            cite_a = td_author.select_one("cite a")
            if cite_a:
                author = _text(cite_a)
                um = UID_HREF_RE.search(cite_a.get("href", ""))
                if um:
                    author_uid = um.group(1)
            em = td_author.find("em")
            if em:
                posted_at = _text(em)

        # replies / views
        replies = views = None
        td_nums = tr.find("td", class_="nums")
        if td_nums:
            strong = td_nums.find("strong")
            em = td_nums.find("em")
            replies = _int_or_none(_text(strong))
            views = _int_or_none(_text(em))

        # last reply
        last_reply_at = last_reply_by = None
        td_last = tr.find("td", class_="lastpost")
        if td_last:
            em = td_last.find("em")
            if em:
                a = em.find("a")
                last_reply_at = _text(a) if a else _text(em)
            cite_a = td_last.select_one("cite a")
            if cite_a:
                last_reply_by = _text(cite_a)

        items.append({
            "title": title,
            "code": tid,
            "url": urljoin(f"{BBS}/", f"thread-{tid}-1-1.html"),
            "source": "sexinsex",
            "cover": None,
            "duration": None,
            "extra": {
                "forum_id": forum_id,
                "forum_name": forum_name,
                "author": author,
                "author_uid": author_uid,
                "posted_at": posted_at,
                "replies": replies,
                "views": views,
                "last_reply_at": last_reply_at,
                "last_reply_by": last_reply_by,
                "tag": tag,
                "page": page,
            },
        })
    return items


def detect_max_page(html: str) -> int | None:
    """从分页元素里取最大页码,辅助用户知道总页数。"""
    soup = BeautifulSoup(html, "html.parser")
    pages: list[int] = []
    for a in soup.find_all("a"):
        href = a.get("href", "") or ""
        for m in re.finditer(r"page[-=](\d+)", href):
            pages.append(int(m.group(1)))
    return max(pages) if pages else None


# ---------------- 主流程 ----------------

def resolve_base_url(args) -> tuple[str, str | None]:
    """根据 CLI 参数确定"第 1 页 URL"和"tag 名"(用于 extra)。"""
    chosen = sum(bool(x) for x in (args.tag, args.forum, args.url))
    if chosen != 1:
        raise SystemExit("[错误] --tag / --forum / --url 必须三选一")
    if args.tag:
        return tag_url(args.tag, 1), args.tag
    if args.forum:
        return forum_url(args.forum, 1), None
    return args.url, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="sexinsex.net 列表爬虫(Discuz tag/forum)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n  python3 scrapers/sexinsex_scraper.py --tag 素人 --pages 3\n  python3 scrapers/sexinsex_scraper.py --forum 25 --start 1 --end 5\n",
    )
    parser.add_argument("--tag", help="标签名(直接用中文,脚本会 GBK URL 编码)")
    parser.add_argument("--forum", help="版块 id(forum-{id}-1.html 的 id 部分)")
    parser.add_argument("--url", help="自定义列表页 URL(支持分页的任意页)")
    parser.add_argument("--start", type=int, default=1, help="起始页,默认 1")
    parser.add_argument("--end", type=int, help="结束页(含)。与 --pages 二选一")
    parser.add_argument("--pages", type=int, help="从 start 起抓的页数。与 --end 二选一")
    parser.add_argument("-o", "--output", default=DEFAULT_OUT, help=f"输出 JSON 路径(默认 {DEFAULT_OUT})")
    parser.add_argument("--sleep", type=float, default=1.5, help="每页间隔秒数,默认 1.5")
    parser.add_argument("--append", action="store_true",
                        help="追加模式:与已存在的 JSON 合并去重,而非覆盖")
    args = parser.parse_args()

    if args.end is None:
        args.end = args.start + (args.pages or 1) - 1
    if args.end < args.start:
        print("[错误] end 不能小于 start", file=sys.stderr)
        return 1

    try:
        base_url, tag_name = resolve_base_url(args)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 2

    sess = make_session()

    # 已存在文件 → 读出来用于去重(可选追加)
    existing: list[dict] = []
    seen: set[str] = set()
    out_path = Path(args.output)
    if args.append and out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            for it in existing:
                if isinstance(it, dict) and it.get("code"):
                    seen.add(it["code"])
            print(f"[append] 已读入 {len(existing)} 条,{len(seen)} 个 code 进入去重集")
        except (json.JSONDecodeError, OSError) as e:
            print(f"[append 警告] 旧文件读不了,改成覆盖模式:{e}", file=sys.stderr)
            existing = []
            seen = set()

    all_items: list[dict] = list(existing)
    print(f"目标:{base_url}")
    print(f"页范围:{args.start} ~ {args.end} → 输出 {out_path}")

    for n in range(args.start, args.end + 1):
        url = bump_page(base_url, n)
        try:
            html = fetch_html(sess, url)
        except requests.RequestException as e:
            print(f"  第 {n} 页:HTTP 错 → {e}", file=sys.stderr)
            continue
        items = parse_list(html, tag=tag_name, page=n)
        new = 0
        for it in items:
            if it["code"] in seen:
                continue
            seen.add(it["code"])
            all_items.append(it)
            new += 1
        print(f"  第 {n} 页({url}):解析 {len(items)} 条,新增 {new}(累计 {len(all_items)})")
        if n == args.start:
            mx = detect_max_page(html)
            if mx:
                print(f"  ↳ 站点显示总页数约 {mx}")
        if not items:
            print(f"  第 {n} 页无帖子,可能已到末页,停止", file=sys.stderr)
            break
        if n < args.end:
            time.sleep(args.sleep)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n完成:共 {len(all_items)} 条 → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
