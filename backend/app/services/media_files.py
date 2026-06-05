"""安全读取本地媒体文件（仅允许仓库 data/ 等目录）。"""
import mimetypes
from pathlib import Path
from urllib.parse import quote

from ..config import DATA_DIR, FILES_DIR, MEDIA_DIR, REPO_ROOT

REPO_ROOT = REPO_ROOT.resolve()
FILES_DIR = FILES_DIR.resolve()
DATA_DIR = DATA_DIR.resolve()
ALLOWED_ROOTS = tuple(
    dict.fromkeys(p for p in (REPO_ROOT, FILES_DIR, DATA_DIR, MEDIA_DIR) if p.exists())
)


def safe_media_path(file_path: str) -> Path | None:
    """解析并校验路径，通过则返回绝对 Path。"""
    if not file_path:
        return None
    try:
        p = Path(file_path).expanduser().resolve()
    except OSError:
        return None
    if not p.is_file() or p.stat().st_size == 0:
        return None
    for root in ALLOWED_ROOTS:
        try:
            if p.is_relative_to(root):
                return p
        except ValueError:
            continue
    return None


def guess_media_type(path: Path) -> str:
    mt, _ = mimetypes.guess_type(str(path))
    return mt or "application/octet-stream"


def public_media_url(file_path: str) -> str | None:
    """生成可直接用于 img/video 的静态 URL（路径含中文/emoji 会编码）。"""
    p = safe_media_path(file_path)
    if not p:
        return None
    try:
        rel = p.relative_to(FILES_DIR)
    except ValueError:
        return None
    encoded = "/".join(quote(part, safe="") for part in rel.parts)
    return f"/files/{encoded}"
