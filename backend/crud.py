# -*- coding: utf-8 -*-
"""响应序列化与订单状态汇总"""
from sqlalchemy.orm import Session

from . import models


def event_out(ev: models.HandoverEvent) -> dict:
    return {
        "id": ev.id,
        "material_id": ev.material_id,
        "event_type": ev.event_type,
        "event_type_label": models.EVENT_LABEL.get(ev.event_type, ev.event_type),
        "batch_no": ev.batch_no,
        "from_party": ev.from_party,
        "to_party": ev.to_party,
        "counterparty_name": ev.counterparty_name,
        "counterparty_id": ev.counterparty_id,
        "sign_mode": ev.sign_mode,
        "note": ev.note,
        "has_embassy_receipt": bool(ev.embassy_receipt_path),
        "actor_name": ev.actor.display_name if ev.actor else str(ev.actor_user_id),
        "created_at": ev.created_at,
    }


def material_out(m: models.Material, with_events: bool = True) -> dict:
    return {
        "id": m.id,
        "seq_no": m.seq_no,
        "item_no": m.item_no,
        "doc_type": m.doc_type,
        "doc_name": m.doc_name,
        "status": m.status,
        "location_text": m.location_text,
        "has_photo": bool(m.photo_path),
        "events": [event_out(e) for e in m.events] if with_events else [],
    }


def proxy_auth_out(a: models.ProxyAuthorization, today=None) -> dict:
    from datetime import date as _date
    today = today or _date.today()
    revoked = a.revoked_at is not None
    valid_now = (not revoked) and a.valid_from <= today <= a.valid_until
    scope = [int(x) for x in a.scope_material_ids.split(",") if x.strip()]
    return {
        "id": a.id,
        "proxy_name": a.proxy_name,
        "proxy_id_no": a.proxy_id_no,
        "scope_material_ids": scope,
        "valid_from": a.valid_from,
        "valid_until": a.valid_until,
        "revoked": revoked,
        "valid_now": valid_now,
        "note": a.note,
        "created_at": a.created_at,
    }


def _counts(materials: list[models.Material]) -> dict:
    c = {
        models.MAT_RECEIVED: 0,
        models.MAT_SUBMITTED: 0,
        models.MAT_RETURNED: 0,
        models.MAT_HELD: 0,
    }
    for m in materials:
        c[m.status] += 1
    total = len(materials)
    held = c[models.MAT_HELD]
    missing = total - held
    if held == total and total > 0:
        stage = "全部领回·已完结"
    elif c[models.MAT_RETURNED] > 0:
        stage = f"部分退件待领回（缺件 {missing} 件仍在外部/在库）"
    elif c[models.MAT_SUBMITTED] > 0 and held > 0:
        stage = f"部分已领回，其余 {c[models.MAT_SUBMITTED]} 件仍在外部办理"
    elif c[models.MAT_SUBMITTED] > 0:
        if c[models.MAT_RECEIVED] > 0:
            stage = "分批递交中·部分外部办理"
        else:
            stage = "全部外部办理中（使馆/签证中心）"
    elif held > 0:
        stage = f"部分已领回，其余 {c[models.MAT_RECEIVED]} 件在库待处理"
    else:
        stage = "已收件·旅行社保管"
    return {
        "total_count": total,
        "held_count": held,
        "submitted_count": c[models.MAT_SUBMITTED],
        "returned_count": c[models.MAT_RETURNED],
        "received_count": c[models.MAT_RECEIVED],
        "missing_count": missing,
        "current_stage": stage,
    }


def order_summary(o: models.Order) -> dict:
    base = {
        "id": o.id,
        "order_no": o.order_no,
        "customer": {
            "id": o.customer.id,
            "name": o.customer.name,
            "phone": o.customer.phone,
            "id_number": o.customer.id_number,
        },
        "destination": o.destination,
        "visa_type": o.visa_type,
        "created_at": o.created_at,
        "completed": o.completed_at is not None,
    }
    base.update(_counts(o.materials))
    return base


def order_detail(o: models.Order) -> dict:
    d = order_summary(o)
    d["receipt_token"] = o.receipt_token
    d["materials"] = [material_out(m) for m in o.materials]
    d["events"] = [event_out(e) for e in o.events]
    d["proxy_auths"] = [proxy_auth_out(a) for a in o.proxy_auths]
    return d


def staff_handles_order(db: Session, user: models.User, order: models.Order) -> bool:
    """该员工是否经手此订单（在交接流水中出现过）。用于证件照片的访问控制。"""
    if user.role == models.ROLE_ADMIN:
        return True
    exists = (
        db.query(models.HandoverEvent.id)
        .filter(
            models.HandoverEvent.order_id == order.id,
            models.HandoverEvent.actor_user_id == user.id,
        )
        .first()
    )
    return exists is not None
