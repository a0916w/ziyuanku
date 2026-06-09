"""爬虫脚本分类 API。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, models
from ..database import get_db
from ..schemas import ScriptCategoryIn, ScriptCategoryUpdate

router = APIRouter(prefix="/api/script-categories", tags=["script-categories"])


def _category_dict(cat: models.ScriptCategory, script_count: int) -> dict:
    return {
        "id": cat.id,
        "name": cat.name,
        "description": cat.description,
        "sort_order": cat.sort_order,
        "script_count": script_count,
        "created_at": cat.created_at,
    }


@router.get("", summary="分类列表")
def list_categories(db: Session = Depends(get_db)):
    cats = crud.list_script_categories(db)
    return [
        _category_dict(cat, crud.count_scripts_in_category(db, cat.id))
        for cat in cats
    ]


@router.post("", summary="添加分类")
def create_category(payload: ScriptCategoryIn, db: Session = Depends(get_db)):
    if crud.get_script_category_by_name(db, payload.name):
        raise HTTPException(409, "同名分类已存在")
    cat = crud.create_script_category(
        db, payload.name, payload.description, payload.sort_order,
    )
    return _category_dict(cat, 0)


@router.patch("/{category_id}", summary="更新分类")
def patch_category(
    category_id: int, payload: ScriptCategoryUpdate, db: Session = Depends(get_db),
):
    cat = crud.get_script_category(db, category_id)
    if not cat:
        raise HTTPException(404, "分类不存在")
    if payload.name and payload.name != cat.name:
        if crud.get_script_category_by_name(db, payload.name):
            raise HTTPException(409, "同名分类已存在")
    crud.update_script_category(db, cat, **payload.model_dump(exclude_unset=True))
    return _category_dict(cat, crud.count_scripts_in_category(db, cat.id))


@router.delete("/{category_id}", summary="删除分类")
def remove_category(category_id: int, db: Session = Depends(get_db)):
    cat = crud.get_script_category(db, category_id)
    if not cat:
        raise HTTPException(404, "分类不存在")
    crud.delete_script_category(db, cat)
    return {"ok": True}
