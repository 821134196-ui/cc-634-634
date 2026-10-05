"""业务服务层：交接状态机、使馆回执模拟、代领授权校验、整单完成保护。"""
import secrets
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Authorization,
    EVENT_ASSIGN_COURIER,
    EVENT_EMBASSY_RETURN,
    EVENT_FROM_STATUSES,
    EVENT_SELF_PICKUP,
    EVENT_SIGN,
    EVENT_SUBMIT,
    EVENT_TARGET_STATUS,
    Handover,
    Material,
    Order,
    STATUS_SIGNED,
    User,
)


class ServiceError(HTTPException):
    def __init__(self, detail: str, code: int = status.HTTP_409_CONFLICT):
        super().__init__(code, detail)


# ---- 查询辅助 -------------------------------------------------------------
def get_materials(db: Session, order: Order, material_ids: list[int]) -> list[Material]:
    if not material_ids:
        raise ServiceError("未选择任何材料", status.HTTP_400_BAD_REQUEST)
    seen, result = set(), []
    for mid in material_ids:
        if mid in seen:
            continue
        seen.add(mid)
        m = db.get(Material, mid)
        if not m or m.order_id != order.id:
            raise ServiceError(f"材料 {mid} 不属于本订单或不存在", status.HTTP_404_NOT_FOUND)
        result.append(m)
    return result


def assert_transition(materials: list[Material], event_type: str) -> None:
    allowed = EVENT_FROM_STATUSES[event_type]
    bad = [m.material_no for m in materials if m.status not in allowed]
    if bad:
        raise ServiceError(
            f"以下材料当前状态不允许该操作：{', '.join(bad)}"
        )


def add_handover(db: Session, order: Order, material: Material | None, *,
                 event_type, from_party, to_party, actor: User,
                 counterparty_name="", counterparty_sign="", location="",
                 note="", embassy_receipt_no="", authorization=None) -> Handover:
    h = Handover(
        order_id=order.id,
        material_id=material.id if material else None,
        event_type=event_type,
        from_party=from_party,
        to_party=to_party,
        actor_user_id=actor.id if actor else None,
        counterparty_name=counterparty_name,
        counterparty_sign=counterparty_sign,
        location=location,
        note=note,
        embassy_receipt_no=embassy_receipt_no,
        authorization_id=authorization.id if authorization else None,
    )
    db.add(h)
    return h


def maybe_complete_order(db: Session, order: Order) -> bool:
    """仅当订单内每件材料都已签收，才允许整单完成。返回是否完成。"""
    materials = order.materials
    if materials and all(m.status == STATUS_SIGNED for m in materials):
        order.status = "completed"
        order.completed_at = datetime.utcnow()
        return True
    return False


def try_force_complete(db: Session, order: Order) -> None:
    """显式整单完成：缺件（任何未签收材料）时拒绝，禁止提前完成。"""
    pending = [m.material_no for m in order.materials if m.status != STATUS_SIGNED]
    if pending:
        raise ServiceError(
            "存在尚未归还/签收的材料，禁止整单提前完成：" + ", ".join(pending)
        )
    if not order.materials:
        raise ServiceError("订单没有任何材料，无法完成")
    order.status = "completed"
    order.completed_at = datetime.utcnow()


# ---- 交接操作 -------------------------------------------------------------
def submit_to_embassy(db: Session, order: Order, materials: list[Material],
                      actor: User, note: str) -> str:
    """递交使馆。模拟生成使馆回执号，写入每件材料的交接记录。"""
    assert_transition(materials, EVENT_SUBMIT)
    # 使馆回执模拟：一个递交批次一个回执号
    receipt_no = "EMB-" + datetime.utcnow().strftime("%Y%m%d") + "-" + secrets.token_hex(3).upper()
    for m in materials:
        add_handover(
            db, order, m, event_type=EVENT_SUBMIT,
            from_party="旅行社", to_party=order.embassy, actor=actor,
            counterparty_name=order.embassy + "窗口", location=order.embassy,
            note=note, embassy_receipt_no=receipt_no,
        )
        m.status = EVENT_TARGET_STATUS[EVENT_SUBMIT]
    db.flush()
    return receipt_no


def embassy_return(db: Session, order: Order, materials: list[Material],
                   actor: User, note: str) -> None:
    """使馆退件（可部分）。仅退回所选件；其余仍保持 submitted（在外部办理）。"""
    assert_transition(materials, EVENT_EMBASSY_RETURN)
    for m in materials:
        add_handover(
            db, order, m, event_type=EVENT_EMBASSY_RETURN,
            from_party=order.embassy, to_party="旅行社", actor=actor,
            counterparty_name=order.embassy + "窗口", location="旅行社前台",
            note=note or "使馆退件",
        )
        m.status = EVENT_TARGET_STATUS[EVENT_EMBASSY_RETURN]
    db.flush()


def assign_courier(db: Session, order: Order, materials: list[Material],
                   actor: User, courier_name: str, note: str) -> None:
    """交配送员送达。"""
    assert_transition(materials, EVENT_ASSIGN_COURIER)
    for m in materials:
        add_handover(
            db, order, m, event_type=EVENT_ASSIGN_COURIER,
            from_party="旅行社", to_party="配送员", actor=actor,
            counterparty_name=courier_name or "配送员",
            location="配送途中", note=note,
        )
        m.status = EVENT_TARGET_STATUS[EVENT_ASSIGN_COURIER]
    db.flush()


def switch_self_pickup(db: Session, order: Order, materials: list[Material],
                       actor: User, note: str) -> None:
    """改为客户自取：只追加交接记录，不改动最初收件单。"""
    assert_transition(materials, EVENT_SELF_PICKUP)
    for m in materials:
        add_handover(
            db, order, m, event_type=EVENT_SELF_PICKUP,
            from_party="配送员" if m.status == "delivering" else "旅行社",
            to_party="客户自取", actor=actor,
            counterparty_name=order.customer.name, location="旅行社前台",
            note=note or "客户改为自取",
        )
        m.status = EVENT_TARGET_STATUS[EVENT_SELF_PICKUP]
    db.flush()


# ---- 代领授权 -------------------------------------------------------------
def find_valid_authorization(db: Session, order: Order, agent_name: str,
                             agent_id_no: str) -> Authorization:
    """校验代领授权：存在、未撤销、在有效期内、代领人姓名与证件号一致。"""
    now = datetime.utcnow()
    stmt = (
        select(Authorization)
        .where(Authorization.order_id == order.id)
        .order_by(Authorization.id.desc())
    )
    auths = db.scalars(stmt).all()
    if not auths:
        raise ServiceError("该订单没有代领授权，禁止代领签收", status.HTTP_403_FORBIDDEN)

    # 先定位身份匹配的授权
    matched = [
        a for a in auths
        if a.agent_name.strip() == agent_name.strip()
        and a.agent_id_no.strip() == agent_id_no.strip()
    ]
    if not matched:
        raise ServiceError(
            "代领人姓名/证件号与授权书不符，禁止代领", status.HTTP_403_FORBIDDEN
        )

    auth = matched[0]
    if auth.status == "revoked":
        raise ServiceError("该代领授权已撤销，禁止代领", status.HTTP_403_FORBIDDEN)
    if now < auth.valid_from:
        raise ServiceError("代领授权尚未生效", status.HTTP_403_FORBIDDEN)
    if now > auth.valid_until:
        raise ServiceError("代领授权已过期，禁止代领", status.HTTP_403_FORBIDDEN)
    return auth


def sign_materials(db: Session, order: Order, materials: list[Material], actor: User,
                   receiver_kind: str, receiver_name: str, receiver_id_no: str,
                   sign: str, note: str) -> dict:
    """客户按件签收。逐件写签收记录，任何一件不满足都整体报错，不产生部分签收。"""
    assert_transition(materials, EVENT_SIGN)
    if not sign.strip():
        raise ServiceError("签收需要客户签名/签收码，按件签收不可为空",
                           status.HTTP_400_BAD_REQUEST)

    authorization = None
    if receiver_kind == "agent":
        if not receiver_id_no.strip():
            raise ServiceError("代领必须提供代领人证件号", status.HTTP_400_BAD_REQUEST)
        authorization = find_valid_authorization(
            db, order, receiver_name, receiver_id_no
        )

    for m in materials:
        add_handover(
            db, order, m, event_type=EVENT_SIGN,
            from_party="配送员" if m.status == "delivering" else "旅行社",
            to_party="代领人" if receiver_kind == "agent" else "客户本人",
            actor=actor,
            counterparty_name=receiver_name,
            counterparty_sign=sign,
            location="客户处" if m.status == "delivering" else "旅行社前台",
            note=note, authorization=authorization,
        )
        m.status = STATUS_SIGNED
    db.flush()
    completed = maybe_complete_order(db, order)
    return {
        "signed": len(materials),
        "authorization_id": authorization.id if authorization else None,
        "order_completed": completed,
    }
