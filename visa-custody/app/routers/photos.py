import mimetypes

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import assert_photo_access, get_current_user
from ..models import Authorization, Material, Order, User
from ..storage import resolve_photo_path

router = APIRouter(prefix="/api/photos", tags=["photos"])


@router.get("/material/{material_id}")
def get_material_photo(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """证件/原件照片：仅经手岗位与管理员；staff 不得跨客户。"""
    m = db.get(Material, material_id)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "材料不存在")
    order = db.get(Order, m.order_id)
    assert_photo_access(user, order.customer)
    if not m.photo_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该材料没有照片")
    path = resolve_photo_path(m.photo_path)
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "image/jpeg")


@router.get("/authorization/{auth_id}")
def get_agent_id_photo(
    auth_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """代领人证件照片：同样限制岗位 + 客户归属。"""
    auth = db.get(Authorization, auth_id)
    if not auth:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "授权不存在")
    order = db.get(Order, auth.order_id)
    assert_photo_access(user, order.customer)
    if not auth.id_doc_photo_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该授权没有证件照片")
    path = resolve_photo_path(auth.id_doc_photo_path)
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "image/jpeg")
