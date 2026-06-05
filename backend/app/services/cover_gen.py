"""从本地视频截帧生成封面图。"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _run_ffmpeg(video_path: Path, out_path: Path, seek_seconds: int) -> bool:
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(seek_seconds),
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0


def generate_cover_from_video(video_path: str, covers_dir: Path, video_id: int) -> str | None:
    """从本地视频截帧生成封面，返回绝对路径；失败返回 None。"""
    src = Path(video_path).expanduser().resolve()
    if not src.is_file() or src.stat().st_size == 0:
        return None

    out_dir = covers_dir / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{video_id}.jpg"

    # 已存在则复用
    if out.is_file() and out.stat().st_size > 0:
        return str(out.resolve())

    # 多个时间点尝试，提升命中率（避免黑帧）
    for sec in (3, 1, 0):
        if _run_ffmpeg(src, out, sec):
            return str(out.resolve())

    return None
