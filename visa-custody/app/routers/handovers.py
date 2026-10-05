from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import ROLE_ADMIN, ROLE_COURIER, ROLE_STAFF
from ..database import get_db
from ..deps import get_current_user
from ..models import Order, User
from ..schemas import (
    DeliverIn,
    ReturnIn,
    SelfPickupIn,
    SignIn,
    SubmitIn,
)
from ..serializers import order_dict
from ..services import (
    ServiceError,
    assign_courier,
    embassy_return,
    get_materials,
    sign_materials,
    submit_to_embassy,
    switch_self_pickup,
)
from ..sms import send_sms

router = APIRouter(prefix="/api/orders", tags=["handovers"])

STAFF = (ROLE_ADMIN, ROLE_STAFF)


def _load_order(order_id: int, db: Session) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "订单不存在")
    return order


@router.post("/{order_id}/submit")
def submit(order_id: int, body: SubmitIn, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    """递交使馆（可分批）。生成使馆回执，短信通知客户。"""
    if user.role not in STAFF:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅经手岗位可递交使馆")
    order = _load_order(order_id, db)
    materials = get_materials(db, order, body.material_ids)
    try:
        receipt = submit_to_embassy(db, order, materials, user, body.note)
    except ServiceError as e:
        db.rollback()
        raise
    send_sms(
        db, order.customer,
        f"您的订单 {order.order_no} 有 {len(materials)} 件材料已递交{order.embassy}"
        f"（使馆回执 {receipt}），进入外部办理。",
        kind="submitted",
    )
    db.commit()
    return {"ok": True, "embassy_receipt_no": receipt, "order": order_dict(order)}


@router.post("/{order_id}/return")
def embassy_return_route(order_id: int, body: ReturnIn, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """使馆退件——支持仅退回部分。其余材料仍保持‘在使馆·外部办理中’。"""
    if user.role not in STAFF:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅经手岗位可登记退件")
    order = _load_order(order_id, db)
    materials = get_materials(db, order, body.material_ids)
    embassy_return(db, order, materials, user, body.note)
    still_external = [m.material_no for m in order.materials if m.status == "submitted"]
    send_sms(
        db, order.customer,
        f"您的订单 {order.order_no} 已有 {len(materials)} 件退回到店，可预约领回。"
        + (f" 另有 {len(still_external)} 件仍在使馆办理中。" if still_external else ""),
        kind="returned",
    )
    db.commit()
    return {
        "ok": True,
        "returned": len(materials),
        "still_in_embassy": still_external,
        "order": order_dict(order),
    }


@router.post("/{order_id}/deliver")
def deliver(order_id: int, body: DeliverIn, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    """交配送员送达（可分批）。"""
    if user.role not in STAFF:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅经手岗位可安排配送")
    order = _load_order(order_id, db)
    materials = get_materials(db, order, body.material_ids)
    assign_courier(db, order, materials, user, body.courier_name, body.note)
    db.commit()
    return {"ok": True, "order": order_dict(order)}


@router.post("/{order_id}/self-pickup")
def self_pickup(order_id: int, body: SelfPickupIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """改为客户自取：只追加记录，不修改最初收件单。"""
    if user.role not in STAFF:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅经手岗位可改为自取")
    order = _load_order(order_id, db)
    materials = get_materials(db, order, body.material_ids)
    switch_self_pickup(db, order, materials, user, body.note)
    db.commit()
    return {"ok": True, "order": order_dict(order)}


@router.post("/{order_id}/sign")
def sign(order_id: int, body: SignIn, db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    """客户/代领人按件签收。代领必须通过有效授权校验。"""
    # 经手岗位与配送员可执行现场签收；授权校验在服务层
    if user.role not in (ROLE_ADMIN, ROLE_STAFF, ROLE_COURIER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "当前岗位不能办理签收")
    order = _load_order(order_id, db)
    materials = get_materials(db, order, body.material_ids)
    result = sign_materials(
        db, order, materials, user,
        body.receiver_kind, body.receiver_name, body.receiver_id_no,
        body.sign, body.note,
    )
    if body.receiver_kind == "agent":
        who = f"代领人{body.receiver_name}"
    else:
        who = f"客户{body.receiver_name}"
    if result["order_completed"]:
        send_sms(
            db, order.customer,
            f"您的订单 {order.order_no} 全部原件已由{who}签收完毕，订单完成。",
            kind="completed",
        )
    db.commit()
    return {"ok": True, **result, "order": order_dict(order)}
