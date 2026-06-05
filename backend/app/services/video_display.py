"""资源库卡片展示用的进度与封面逻辑。"""
from .. import models


def download_progress_display(video: models.Video) -> dict:
    """返回 progress(0-100)、indeterminate、status_label。"""
    status = video.download_status or models.DL_PENDING
    raw = video.download_progress if video.download_progress is not None else 0
    label = models.DL_STATUS_LABELS.get(status, status)

    if status == models.DL_DONE:
        return {"progress": 100, "indeterminate": False, "status_label": label}
    if status == models.DL_PENDING:
        return {"progress": 0, "indeterminate": False, "status_label": label}
    if status == models.DL_FAILED:
        return {"progress": max(0, min(100, raw)), "indeterminate": False, "status_label": label}
    if status == models.DL_DOWNLOADING:
        if raw > 0:
            return {"progress": min(100, raw), "indeterminate": False, "status_label": label}
        return {"progress": 0, "indeterminate": True, "status_label": label}
    return {"progress": 0, "indeterminate": False, "status_label": label}
