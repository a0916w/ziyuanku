"""封面图水印去除服务。

策略：按来源站点使用预设的水印区域（相对坐标），用 OpenCV Telea 算法 inpainting 填充。
支持自定义区域覆盖预设。

预设区域格式：list of (x_ratio, y_ratio, w_ratio, h_ratio)，比例相对于图像宽高。
例如 (0.0, 0.85, 0.35, 0.15) 表示：左下角、宽35%、高15%。
"""

import hashlib
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import requests
from PIL import Image

log = logging.getLogger(__name__)

# 各来源站点的水印预设区域（可叠加多个区域）
WATERMARK_PRESETS: dict[str, list[tuple[float, float, float, float]]] = {
    "missav": [
        (0.0, 0.88, 0.30, 0.12),   # 左下角 "MISSAV.COM"
    ],
    "pornhub": [
        (0.0, 0.0, 0.28, 0.10),    # 左上角 "PORNHUB"
    ],
    "default": [
        (0.0, 0.88, 0.35, 0.12),   # 左下角（通用回退）
    ],
}

_DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://missav.ai/",
}


def _regions_to_mask(img_h: int, img_w: int,
                     regions: list[tuple[float, float, float, float]]) -> np.ndarray:
    """把相对坐标区域列表转为 uint8 掩码（255 = 水印区域）。"""
    mask = np.zeros((img_h, img_w), dtype=np.uint8)
    for xr, yr, wr, hr in regions:
        x = int(xr * img_w)
        y = int(yr * img_h)
        w = int(wr * img_w)
        h = int(hr * img_h)
        # 稍微扩展 2px，避免边缘残留
        x = max(0, x - 2)
        y = max(0, y - 2)
        w = min(img_w - x, w + 4)
        h = min(img_h - y, h + 4)
        mask[y:y + h, x:x + w] = 255
    return mask


def remove_watermark_from_array(
    img_bgr: np.ndarray,
    regions: list[tuple[float, float, float, float]],
    inpaint_radius: int = 5,
) -> np.ndarray:
    """对 BGR numpy 数组做 inpainting，返回处理后的 BGR 数组。"""
    h, w = img_bgr.shape[:2]
    mask = _regions_to_mask(h, w, regions)
    result = cv2.inpaint(img_bgr, mask, inpaint_radius, cv2.INPAINT_TELEA)
    return result


def download_cover(url: str, save_to: Optional[Path] = None) -> Optional[np.ndarray]:
    """下载封面图，返回 BGR numpy 数组；可选同时保存原图到 save_to。"""
    try:
        resp = requests.get(url, headers=_DOWNLOAD_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.content
        if save_to:
            save_to.parent.mkdir(parents=True, exist_ok=True)
            save_to.write_bytes(data)
        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        log.error("下载封面失败 %s: %s", url, e)
        return None


def process_cover(
    cover_url: str,
    source: str,
    covers_dir: Path,
    video_id: int,
    custom_regions: Optional[list[tuple[float, float, float, float]]] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    完整流程：下载封面 → 去水印 → 保存。

    Returns:
        (cover_path, cover_clean_path) — 原图路径和处理后路径（相对 covers_dir 的字符串，
        或绝对路径，视调用方需要）。失败时对应值为 None。
    """
    orig_path = covers_dir / f"{video_id}_orig.jpg"
    clean_path = covers_dir / f"{video_id}_clean.jpg"

    # 已处理过则直接返回
    if clean_path.exists() and orig_path.exists():
        log.info("封面已存在，跳过处理 video_id=%s", video_id)
        return str(orig_path), str(clean_path)

    img_bgr = download_cover(cover_url, save_to=orig_path)
    if img_bgr is None:
        return None, None

    regions = custom_regions or WATERMARK_PRESETS.get(source, WATERMARK_PRESETS["default"])
    log.info("去水印 video_id=%s source=%s regions=%s", video_id, source, regions)

    clean_bgr = remove_watermark_from_array(img_bgr, regions)
    cv2.imwrite(str(clean_path), clean_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])

    return str(orig_path), str(clean_path)
