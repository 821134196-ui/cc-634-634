from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import ROLE_ADMIN, ROLE_STAFF
from ..database import get_db
from ..deps import get_current_user
from ..models import (
    EVENT_RECEIVE,
    Material,
    Order,
    User,
)
from ..schemas import OrderIn
from ..serializers import (
    authorization_dict,
    handover_dict,
    material_dict,
    order_dict,
)
from ..services import add_handover, try_force_complete
from ..sms import send_sms
from ..storage import save_id_photo

router = APIRouter(prefix="/api/orders", tags=["orders"])

STAFF_ROLES = (ROLE_ADMIN, ROLE_STAFF)


def _can_view_photo(user: User, order: Order) -> bool:
    if user.role == ROLE_ADMIN:
        return True
    if user.role == ROLE_STAFF:
        return order.customer.owner_staff_id == user.id
    return False


def _load_handover_actors(db: Session, order: Order) -> dict:
    ids = {h.actor_user_id for h in order.handovers if h.actor_user_id}
    users = db.scalars(select(User).where(User.id.in_(ids))).all() if ids else []
    return {u.id: u.name for u in users}


def detail_payload(db: Session, order: Order, user: User) -> dict:
    actors = _load_handover_actors(db, order)
    include_photo = _can_view_photo(user, order)
    mat_ids = {m.id for m in order.materials}
    mat_no_by_id = {m.id: m.material_no for m in order.materials}
    handovers = []
    for h in sorted(order.handovers, key=lambda x: x.id):
        hd = handover_dict(h, actors.get(h.actor_user_id, ""))
        hd["material_no"] = mat_no_by_id.get(h.material_id, "")
        handovers.append(hd)
    return {
        "order": order_dict(order),
        "can_view_photo": include_photo,
        "materials": [material_dict(m, include_photo=include_photo) for m in order.materials],
        "handovers": handovers,
        "authorizations": [authorization_dict(a) for a in order.authorizations],
    }


@router.get("")
def list_orders(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    orders = db.scalars(select(Order).order_by(Order.id)).all()
    return [order_dict(o) for o in orders]


@router.post("", status_code=201)
def create_order(
    body: OrderIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅经手岗位可创建订单")
    from ..models import Customer

    customer = db.get(Customer, body.customer_id)
    if not customer:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "客户不存在")
    order = Order(customer_id=customer.id, embassy=body.embassy, status="active")
    db.add(order)
    db.flush()
    order.order_no = f"V{order.created_at.strftime('%Y%m%d')}-{order.id:04d}"
    send_sms(
        db, customer,
        f"您的{body.embassy}签证材料托管订单 {order.order_no} 已建立，"
        f"原件将逐件编号拍照，请凭订单号与手机号查询进度。",
        kind="order_created",
    )
    db.commit()
    db.refresh(order)
    return order_dict(order)


@router.get("/{order_id}")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "订单不存在")
    return detail_payload(db, order, user)


@router.post("/{order_id}/materials", status_code=201)
def receive_material(
    order_id: int,
    material_type: str = Form(...),
    description: str = Form(""),
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """收件：为每件原件编号、拍照，写一条 receive 交接记录（append-only）。"""
    if user.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅经手岗位可收件")
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "订单不存在")

    stored = save_id_photo(photo, "mat")
    seq = len(order.materials) + 1
    material_no = f"{order.order_no}-P{seq:02d}"
    m = Material(
        order_id=order.id,
        material_no=material_no,
        material_type=material_type,
        description=description,
        photo_path=stored,
        status="received",
    )
    db.add(m)
    db.flush()
    add_handover(
        db, order, m, event_type=EVENT_RECEIVE,
        from_party="客户本人", to_party="旅行社", actor=user,
        counterparty_name=order.customer.name, location="旅行社前台",
        note="收件拍照入库",
    )
    db.flush()
    db.commit()
    db.refresh(m)
    include_photo = _can_view_photo(user, order)
    return material_dict(m, include_photo=include_photo)


@router.post("/{order_id}/notify-receipt")
def notify_receipt(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """向客户发送模拟短信收件凭证（逐件清单）。"""
    if user.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅经手岗位可发送凭证")
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "订单不存在")
    if not order.materials:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "尚未收件，无凭证可发")
    lines = "；".join(f"{m.material_no} {m.material_type}" for m in order.materials)
    send_sms(
        db, order.customer,
        f"【收件凭证】订单 {order.order_no} 已收原件 {len(order.materials)} 件：{lines}。"
        f"可凭订单号+手机号查询当前位置，领回时按件签收。",
        kind="receipt",
    )
    db.commit()
    return {"ok": True, "message": "收件凭证短信已模拟发送"}


@router.post("/{order_id}/complete")
def force_complete(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """整单完成：只要存在缺件（未签收）就拒绝，禁止提前完成。"""
    if user.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅经手岗位可操作完成")
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "订单不存在")
    try_force_complete(db, order)
    db.commit()
    return {"ok": True, "message": "订单已全部签收并完成", "order": order_dict(order)}
