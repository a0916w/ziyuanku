"""批量发送到「剪片」下游的对接层。

⚠️ 接口文档尚未提供 —— 这里是预留对接位（stub）：
  - 未配置 DISPATCH_ENDPOINT 时：走 stub，仅把资源状态推进到「已发送切片」并记日志，
    让后台按钮现在就能用、整条链路可演示。
  - 配置 DISPATCH_ENDPOINT 后：把 _build_payload 改成接口文档要求的字段，
    并打开真实 HTTP 调用即可，无需改其它代码。
"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from .. import models
from ..config import DISPATCH_ENDPOINT, DISPATCH_TOKEN

log = logging.getLogger(__name__)


def _build_payload(resources: list[models.Resource]) -> dict:
    """按下游接口文档构造请求体。文档到位后在此补齐字段。"""
    return {
        "items": [
            {
                "id": r.id,
                "file_path": r.file_path,
                "media_type": r.media_type,
                "source_account": r.source_account,
                "source_url": r.source_url,
                "caption": r.caption,
            }
            for r in resources
        ]
    }


def send_to_clip(db: Session, resources: list[models.Resource]) -> dict:
    """把一批资源发去剪片。返回 {sent, failed, mode}。"""
    if not resources:
        return {"sent": 0, "failed": 0, "mode": "noop"}

    payload = _build_payload(resources)

    if DISPATCH_ENDPOINT:
        # 真实调用（接口文档到位后启用）。
        import httpx
        headers = {"Authorization": f"Bearer {DISPATCH_TOKEN}"} if DISPATCH_TOKEN else {}
        try:
            resp = httpx.post(DISPATCH_ENDPOINT, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            log.error("批量发送失败：%s", e)
            return {"sent": 0, "failed": len(resources), "mode": "http", "error": str(e)}
        mode = "http"
    else:
        # stub：接口文档未到，先只在本地推进状态，方便后台按钮即刻可用。
        log.info("[stub] 批量发送 %d 条资源（接口未配置，仅本地推进状态）", len(resources))
        mode = "stub"

    now = datetime.utcnow()
    for r in resources:
        r.status = models.STATUS_SENT_FOR_CLIP
        r.sent_for_clip_at = now
    db.commit()
    return {"sent": len(resources), "failed": 0, "mode": mode}
