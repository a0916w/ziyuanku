#!/usr/bin/env python3
"""检测视频中的 URL 文字水印，逐帧打马赛克（像素化）。

策略
----
1. 用 EasyOCR 对采样帧做文本检测（每 N 帧一次，N 默认 5；中间帧复用上次的 bbox）。
2. 把 OCR 识别到的文本用 URL 正则筛一遍（含常见 TLD 白名单，避免误伤剧情中的普通文字）。
3. 命中的 bbox 在帧内做像素化打码（区域 downscale → upscale），适配固定水印与浮动水印。
4. OpenCV 写出无音轨临时 mp4，最后用 ffmpeg 把原视频音轨 mux 回去，加 +faststart。

输出
----
默认放回原目录，文件名加 `_clean` 后缀，不覆盖原文件。

用法
----
    python3 tools/dewatermark.py path/to/video.mp4
    python3 tools/dewatermark.py path/to/dir            # 递归处理目录所有视频
    python3 tools/dewatermark.py path/to/video.mp4 --ocr-interval 5 --pixel-size 14
    python3 tools/dewatermark.py path/to/video.mp4 --gpu                 # 用 CUDA
    python3 tools/dewatermark.py path/to/video.mp4 --reencode-h264       # 输出 H.264

依赖
----
    pip install -r tools/requirements.txt
    需本机已装 ffmpeg。

首次运行 EasyOCR 会下载模型到 `~/.EasyOCR/`（约 100MB），网络环境差需耐心等。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

# easyocr 启动慢（要 load model），延迟到第一次用时再 import
_easyocr_reader = None


# ---------------- URL 识别 ----------------

# 常见 TLD 白名单。OCR 经常把 . 看成 , 或全角符号，且会把 URL 中间的字符识错；
# 用 TLD 白名单收敛误伤——只要末尾像 .com / .net / .xxx 这类，就当作 URL 候选。
TLD_WHITELIST = (
    "com|net|org|info|biz|pro|vip|app|club|live|video|stream|site|online|top|fun|"
    "tv|cc|io|me|co|tk|ml|ga|cf|xyz|space|store|world|today|wiki|moe|asia|"
    "cn|jp|hk|tw|kr|us|uk|de|fr|ru|in|br|ca|au|"
    "porn|xxx|sex|adult|tube|cam|hub"
)

URL_PATTERNS = [
    re.compile(r"https?://\S+", re.IGNORECASE),
    re.compile(
        rf"\b[a-zA-Z0-9][\w-]{{0,40}}\.(?:{TLD_WHITELIST})\b(?:/\S*)?",
        re.IGNORECASE,
    ),
]


def looks_like_url(text: str) -> bool:
    """容错地判断 OCR 识别到的一段文字是否像 URL。"""
    if not text:
        return False
    normalized = (
        text.replace("．", ".")
        .replace("。", ".")
        .replace(",", ".")
        .replace("；", ".")
        .replace(";", ".")
    )
    normalized = re.sub(r"\s+", "", normalized)
    return any(p.search(normalized) for p in URL_PATTERNS)


# ---------------- OCR ----------------

def get_reader(use_gpu: bool):
    """惰性初始化 EasyOCR Reader（启动 5-15 秒，且要下模型）。"""
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr
        except ImportError as e:
            raise SystemExit(
                "缺少依赖 easyocr。请先执行：pip install -r tools/requirements.txt"
            ) from e
        print("  正在初始化 EasyOCR（首次会下载模型，约 100MB）…")
        # 只用英文模型，识别 URL 字符（a-z 0-9 - . /）足够，省启动时间和内存
        _easyocr_reader = easyocr.Reader(["en"], gpu=use_gpu, verbose=False)
    return _easyocr_reader


def detect_url_bboxes(
    reader, frame: np.ndarray, scale: float, min_conf: float
) -> list[tuple[int, int, int, int]]:
    """对一帧图像跑 OCR，返回所有"像 URL"的文本框 (x1, y1, x2, y2)，坐标对应原帧。"""
    if scale != 1.0:
        proc_img = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        proc_img = frame
    try:
        result = reader.readtext(proc_img, paragraph=False, detail=1)
    except Exception as e:  # noqa: BLE001
        print(f"    [OCR 异常] {e}", file=sys.stderr)
        return []

    boxes: list[tuple[int, int, int, int]] = []
    for entry in result:
        # EasyOCR 返回: [ [(x,y)×4], text, conf ]
        if len(entry) < 2:
            continue
        pts, text = entry[0], entry[1]
        conf = entry[2] if len(entry) > 2 else 1.0
        if conf is not None and conf < min_conf:
            continue
        if not looks_like_url(text):
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
        # 还原到原始坐标
        if scale != 1.0:
            x1, y1, x2, y2 = (int(v / scale) for v in (x1, y1, x2, y2))
        else:
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        boxes.append((x1, y1, x2, y2))
    return boxes


# ---------------- 打码 ----------------

def pixelate_inplace(
    frame: np.ndarray, bbox: tuple[int, int, int, int], pixel_size: int, pad: int
) -> None:
    """对帧内某区域做像素化（原地修改）。"""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(w, x2 + pad)
    y2 = min(h, y2 + pad)
    if x2 <= x1 or y2 <= y1:
        return
    roi = frame[y1:y2, x1:x2]
    rh, rw = roi.shape[:2]
    nw = max(1, rw // pixel_size)
    nh = max(1, rh // pixel_size)
    small = cv2.resize(roi, (nw, nh), interpolation=cv2.INTER_LINEAR)
    pixelated = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_NEAREST)
    frame[y1:y2, x1:x2] = pixelated


# ---------------- 主流程 ----------------

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def find_videos(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in VIDEO_EXTS else []
    if path.is_dir():
        return sorted(
            p
            for p in path.rglob("*")
            if p.is_file()
            and p.suffix.lower() in VIDEO_EXTS
            and "_clean" not in p.stem
        )
    return []


def output_path_for(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_clean{input_path.suffix}")


def mux_audio(
    video_no_audio: Path, original: Path, output: Path, reencode_h264: bool
) -> bool:
    """把原视频音轨合到打码后的视频上。reencode_h264=True 时把视频流转 H.264。"""
    if reencode_h264:
        video_codec = [
            "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
        ]
    else:
        video_codec = ["-c:v", "copy"]
    cmd = [
        "ffmpeg", "-y", "-loglevel", "warning",
        "-i", str(video_no_audio),
        "-i", str(original),
        "-map", "0:v:0", "-map", "1:a:0?",
        *video_codec,
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-shortest",
        str(output),
    ]
    proc = subprocess.run(cmd)
    return proc.returncode == 0 and output.exists() and output.stat().st_size > 0


def process_video(
    input_path: Path,
    *,
    ocr_interval: int,
    pixel_size: int,
    pad: int,
    ocr_scale: float,
    min_conf: float,
    use_gpu: bool,
    reencode_h264: bool,
    overwrite: bool,
) -> bool:
    out_path = output_path_for(input_path)
    if out_path.exists() and not overwrite:
        print(f"  [跳过] 已存在 {out_path.name}（用 --overwrite 强制重做）")
        return True

    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        print(f"  [失败] 无法打开 {input_path}", file=sys.stderr)
        return False
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if width == 0 or height == 0:
        cap.release()
        print(f"  [失败] 读取尺寸异常 ({width}x{height})", file=sys.stderr)
        return False

    print(f"  尺寸 {width}x{height} @ {fps:.2f}fps, {total} 帧")

    reader = get_reader(use_gpu)

    with tempfile.TemporaryDirectory(prefix="dewatermark_") as td:
        tmp_video = Path(td) / "noaudio.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(tmp_video), fourcc, fps, (width, height))
        if not writer.isOpened():
            cap.release()
            print("  [失败] 无法初始化 VideoWriter（mp4v 编码不可用？）", file=sys.stderr)
            return False

        boxes: list[tuple[int, int, int, int]] = []
        frame_idx = 0
        ocr_calls = 0
        hits_total = 0
        t0 = time.time()
        last_print = t0

        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_idx % ocr_interval == 0:
                    boxes = detect_url_bboxes(reader, frame, scale=ocr_scale, min_conf=min_conf)
                    ocr_calls += 1
                    if boxes:
                        hits_total += len(boxes)
                for b in boxes:
                    pixelate_inplace(frame, b, pixel_size=pixel_size, pad=pad)
                writer.write(frame)
                frame_idx += 1

                now = time.time()
                if now - last_print > 2.0:
                    elapsed = now - t0
                    fps_eff = frame_idx / elapsed if elapsed > 0 else 0
                    pct = (frame_idx / total * 100) if total else 0
                    print(
                        f"    [{frame_idx}/{total}] {pct:5.1f}% | "
                        f"{fps_eff:5.1f} fps | OCR {ocr_calls} 次，命中 {hits_total} 个 bbox",
                        end="\r",
                        flush=True,
                    )
                    last_print = now
        finally:
            cap.release()
            writer.release()

        elapsed = time.time() - t0
        print(
            f"    处理完成：{frame_idx} 帧，OCR {ocr_calls} 次，"
            f"命中 {hits_total} 个 bbox，耗时 {elapsed:.1f}s" + " " * 10
        )

        if frame_idx == 0:
            print("  [失败] 没读到任何帧", file=sys.stderr)
            return False

        print(f"  合并音轨 → {out_path.name}（{'H.264 重编码' if reencode_h264 else 'mp4v 直拷'}）")
        if not mux_audio(tmp_video, input_path, out_path, reencode_h264=reencode_h264):
            print("  [失败] ffmpeg 合并音轨失败", file=sys.stderr)
            return False

    size_mb = out_path.stat().st_size / 1048576
    print(f"  ✔ 输出 {out_path}（{size_mb:.1f} MB）")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="检测视频里的 URL 文字水印并逐帧打马赛克（像素化）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n示例：\n  python3 tools/dewatermark.py data/xchina/6a2832eb9752c/6a2832eb9752c.mp4\n  python3 tools/dewatermark.py data/xchina/ --ocr-interval 5\n",
    )
    parser.add_argument("input", help="输入视频文件或目录（目录递归找 mp4/mov/mkv/webm/avi/m4v）")
    parser.add_argument("--ocr-interval", type=int, default=5,
                        help="每隔几帧跑一次 OCR（默认 5；越大越快越漏）")
    parser.add_argument("--pixel-size", type=int, default=14,
                        help="像素化方块边长（默认 14；越大越粗糙）")
    parser.add_argument("--pad", type=int, default=6,
                        help="马赛克区域外扩像素（默认 6，防止边缘漏字）")
    parser.add_argument("--ocr-scale", type=float, default=0.6,
                        help="OCR 前对帧的缩放比例（默认 0.6，加速 OCR；bbox 自动还原原始坐标）")
    parser.add_argument("--min-conf", type=float, default=0.2,
                        help="OCR 置信度下限（默认 0.2；过滤垃圾识别）")
    parser.add_argument("--gpu", action="store_true", help="EasyOCR 用 GPU（需要 CUDA）")
    parser.add_argument("--reencode-h264", action="store_true",
                        help="ffmpeg mux 时把视频重编码为 H.264（兼容性最好；不指定则保留 mp4v）")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的 _clean 输出")
    args = parser.parse_args()

    in_path = Path(args.input).expanduser().resolve()
    if not in_path.exists():
        print(f"[错误] 路径不存在：{in_path}", file=sys.stderr)
        return 1

    videos = find_videos(in_path)
    if not videos:
        print(f"[错误] 没找到要处理的视频：{in_path}", file=sys.stderr)
        return 1

    print(f"找到 {len(videos)} 个视频待处理\n")
    ok_count = 0
    for i, v in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}] {v}")
        try:
            if process_video(
                v,
                ocr_interval=args.ocr_interval,
                pixel_size=args.pixel_size,
                pad=args.pad,
                ocr_scale=args.ocr_scale,
                min_conf=args.min_conf,
                use_gpu=args.gpu,
                reencode_h264=args.reencode_h264,
                overwrite=args.overwrite,
            ):
                ok_count += 1
        except KeyboardInterrupt:
            print("\n[中断] 用户取消", file=sys.stderr)
            return 130
        except Exception as e:  # noqa: BLE001
            print(f"  [异常] {e}", file=sys.stderr)
        print()

    print(f"完成：{ok_count}/{len(videos)} 个视频处理成功")
    return 0 if ok_count == len(videos) else 2


if __name__ == "__main__":
    raise SystemExit(main())
