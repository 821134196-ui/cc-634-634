from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import ROLE_ADMIN, ROLE_STAFF
from ..database import get_db
from ..deps import get_current_user
from ..models import Authorization, Order, User
from ..schemas import AuthorizationIn, RevokeIn
from ..serializers import authorization_dict
from ..storage import save_id_photo

router = APIRouter(prefix="/api/orders", tags=["authorizations"])

STAFF = (ROLE_ADMIN, ROLE_STAFF)


def _load_order(order_id: int, db: Session) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "订单不存在")
    return order


@router.post("/{order_id}/authorizations", status_code=201)
def create_authorization(
    order_id: int,
    body: AuthorizationIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """登记一份代领授权（含有效期、代领人姓名与证件号）。"""
    if user.role not in STAFF:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅经手岗位可登记授权")
    order = _load_order(order_id, db)
    if body.valid_until <= body.valid_from:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "授权结束时间必须晚于开始时间")
    auth = Authorization(
        order_id=order.id,
        agent_name=body.agent_name,
        agent_id_no=body.agent_id_no,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        created_by=user.id,
        status="active",
    )
    db.add(auth)
    db.commit()
    db.refresh(auth)
    return authorization_dict(auth)


@router.post("/{order_id}/authorizations/{auth_id}/revoke")
def revoke_authorization(
    order_id: int,
    auth_id: int,
    body: RevokeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """撤销授权（只追加撤销状态，不删除记录）。"""
    if user.role not in STAFF:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅经手岗位可撤销授权")
    _load_order(order_id, db)
    auth = db.get(Authorization, auth_id)
    if not auth or auth.order_id != order_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "授权不存在")
    if auth.status == "revoked":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "授权已处于撤销状态")
    auth.status = "revoked"
    auth.revoked_at = datetime.utcnow()
    auth.revoke_reason = body.reason
    db.commit()
    return {"ok": True, "authorization": authorization_dict(auth)}


@router.post("/{order_id}/authorizations/{auth_id}/id-photo", status_code=201)
def upload_agent_id_photo(
    order_id: int,
    auth_id: int,
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """上传代领人证件照片：受与客户证件相同的岗位+客户范围限制。"""
    if user.role not in STAFF:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅经手岗位可上传证件资料")
    order = _load_order(order_id, db)
    auth = db.get(Authorization, auth_id)
    if not auth or auth.order_id != order_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "授权不存在")
    # 经手岗位只能处理本人名下客户
    if user.role == ROLE_STAFF and order.customer.owner_staff_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "不能跨客户操作证件资料")
    auth.id_doc_photo_path = save_id_photo(photo, "agent")
    db.commit()
    return {"ok": True, "has_id_photo": True}
