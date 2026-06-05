"""视频内容分类 API。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, models
from ..database import get_db
from ..schemas import (
    VideoCategoryOut, VideoCategoriesAssign, VideoCategoryBind,
    VideoCategoryCreate, VideoCategoryUpdate,
)
from ..services.content_category_registry import sync_default_categories

router = APIRouter(prefix="/api/video-categories", tags=["video-categories"])


def _cat_dict(cat: models.VideoCategory, db: Session, *, with_children: bool = False) -> dict:
    out = {
        "id": cat.id,
        "name": cat.name,
        "parent_id": cat.parent_id,
        "sort_order": cat.sort_order,
        "video_count": crud.count_videos_in_category(db, cat.id),
    }
    if with_children:
        out["children"] = [
            {
                "id": ch.id,
                "name": ch.name,
                "parent_id": ch.parent_id,
                "sort_order": ch.sort_order,
                "video_count": crud.count_videos_in_category(db, ch.id),
            }
            for ch in cat.children
        ]
    return out


@router.get("", summary="分类树")
def list_categories(db: Session = Depends(get_db)):
    roots = crud.list_video_categories(db, roots_only=True)
    return [_cat_dict(r, db, with_children=True) for r in roots]


@router.post("/sync", summary="同步预设分类树")
def sync_categories(db: Session = Depends(get_db)):
    return sync_default_categories(db)


@router.post("", summary="新建分类")
def create_category(payload: VideoCategoryCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "分类名称不能为空")
    if payload.parent_id is not None:
        parent = crud.get_video_category(db, payload.parent_id)
        if not parent:
            raise HTTPException(404, "父分类不存在")
        if parent.parent_id is not None:
            raise HTTPException(400, "仅支持二级分类，子分类下不能再建子分类")
    if crud.get_video_category_by_name(db, name, parent_id=payload.parent_id):
        raise HTTPException(409, "同级已存在同名分类")
    cat = crud.create_video_category(
        db, name, parent_id=payload.parent_id, sort_order=payload.sort_order,
    )
    return _cat_dict(cat, db, with_children=False)


@router.patch("/{category_id}", summary="编辑分类")
def patch_category(category_id: int, payload: VideoCategoryUpdate, db: Session = Depends(get_db)):
    cat = crud.get_video_category(db, category_id)
    if not cat:
        raise HTTPException(404, "分类不存在")
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        new_name = (updates.get("name") or "").strip()
        if not new_name:
            raise HTTPException(400, "分类名称不能为空")
        dup = crud.get_video_category_by_name(db, new_name, parent_id=cat.parent_id)
        if dup and dup.id != cat.id:
            raise HTTPException(409, "同级已存在同名分类")
        updates["name"] = new_name
    cat = crud.update_video_category(db, cat, **updates)
    return _cat_dict(cat, db, with_children=False)


@router.delete("/{category_id}", summary="删除分类")
def remove_category(category_id: int, db: Session = Depends(get_db)):
    cat = crud.get_video_category(db, category_id)
    if not cat:
        raise HTTPException(404, "分类不存在")
    crud.delete_video_category(db, cat)
    return {"ok": True}


@router.patch("/videos/{video_id}", summary="设置视频所属分类（覆盖）")
def assign_video_categories(
    video_id: int, payload: VideoCategoriesAssign, db: Session = Depends(get_db),
):
    video = crud.set_video_categories(db, video_id, payload.category_ids)
    if not video:
        raise HTTPException(404, "视频不存在")
    return {
        "id": video.id,
        "category_ids": [c.id for c in video.content_categories],
        "category_names": [c.name for c in video.content_categories],
    }


@router.post("/videos/{video_id}/bind", summary="绑定视频到子分类")
def bind_video(video_id: int, payload: VideoCategoryBind, db: Session = Depends(get_db)):
    video = crud.add_video_to_category(db, video_id, payload.category_id)
    if not video:
        raise HTTPException(404, "视频或分类不存在（只能绑定到子分类）")
    return {
        "id": video.id,
        "category_ids": [c.id for c in video.content_categories],
    }


@router.post("/videos/{video_id}/unbind", summary="从子分类移除视频")
def unbind_video(video_id: int, payload: VideoCategoryBind, db: Session = Depends(get_db)):
    video = crud.remove_video_from_category(db, video_id, payload.category_id)
    if not video:
        raise HTTPException(404, "视频或分类不存在")
    return {"ok": True}
