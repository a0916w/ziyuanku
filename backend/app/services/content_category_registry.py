"""视频内容分类预设与同步。"""
from sqlalchemy.orm import Session

from .. import crud

# 预设分类树（与用户提供的 JSON 一致）
DEFAULT_CATEGORY_TREE: list[dict] = [
    {
        "name": "国产",
        "subcategories": [
            "国产传媒",
            "探花大神",
            "真实自拍 / 素人",
            "偷拍 / 酒店系列",
            "美女主播",
        ],
    },
    {
        "name": "日韩精选",
        "subcategories": [
            "日本AV",
            "亚洲无码",
            "韩国 / 台湾无码",
            "欧美专区",
        ],
    },
    {
        "name": "世界杯专题",
        "subcategories": [
            "啦啦队 & 足球宝贝",
            "球衣制服诱惑",
        ],
    },
    {
        "name": "动漫",
        "subcategories": [
            "经典动漫",
            "3D动漫",
        ],
    },
    {
        "name": "直播录屏",
        "subcategories": [
            "裸播大秀",
        ],
    },
    {
        "name": "特殊玩法",
        "subcategories": [
            "黑丝玉足",
            "SM调教",
        ],
    },
    {
        "name": "短视频专区",
        "subcategories": [
            "竖屏短视频，快手/抖音风福利",
            "60秒高能片段",
        ],
    },
    {
        "name": "其他",
        "subcategories": [
            "AI换脸",
        ],
    },
]


def sync_default_categories(db: Session) -> dict:
    """将预设分类树写入数据库（按名称 upsert）。"""
    created, updated = 0, 0
    for i, group in enumerate(DEFAULT_CATEGORY_TREE):
        parent, is_new = crud.upsert_video_category(
            db, group["name"], parent_id=None, sort_order=(i + 1) * 10,
        )
        created += int(is_new)
        updated += int(not is_new)
        for j, sub_name in enumerate(group.get("subcategories") or []):
            _, sub_new = crud.upsert_video_category(
                db, sub_name, parent_id=parent.id, sort_order=(j + 1) * 10,
            )
            created += int(sub_new)
            updated += int(not sub_new)
    total = len(crud.list_video_categories(db, roots_only=False))
    return {"created": created, "updated": updated, "total": total}
