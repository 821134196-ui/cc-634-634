"""把 ORM 对象序列化为前端需要的字典。"""
from .models import (
    STATUS_SIGNED,
    STATUS_SUBMITTED,
    Handover,
    Material,
    Order,
    User,
)

STATUS_LABELS = {
    "received": "在旅行社（已收件）",
    "submitted": "在使馆·外部办理中",
    "returned": "已退件·待客户领回",
    "delivering": "配送中",
    "signed": "已签收",
}

EVENT_LABELS = {
    "receive": "收件",
    "submit": "递交使馆",
    "embassy_return": "使馆退件",
    "assign_courier": "交配送员送达",
    "self_pickup": "改为自取",
    "sign": "客户签收",
}


def user_dict(u: User) -> dict:
    return {"id": u.id, "username": u.username, "name": u.name, "role": u.role}


def material_dict(m: Material, *, include_photo: bool) -> dict:
    d = {
        "id": m.id,
        "material_no": m.material_no,
        "material_type": m.material_type,
        "description": m.description,
        "status": m.status,
        "status_label": STATUS_LABELS.get(m.status, m.status),
        "has_photo": bool(m.photo_path),
        "order_id": m.order_id,
        "created_at": m.created_at.isoformat(),
    }
    if include_photo and m.photo_path:
        d["photo_url"] = f"/api/photos/material/{m.id}"
    return d


def order_dict(o: Order) -> dict:
    materials = o.materials
    total = len(materials)
    signed = sum(1 for m in materials if m.status == STATUS_SIGNED)
    in_external = sum(1 for m in materials if m.status == STATUS_SUBMITTED)
    return {
        "id": o.id,
        "order_no": o.order_no,
        "customer_id": o.customer_id,
        "customer_name": o.customer.name if o.customer else "",
        "customer_phone": o.customer.phone if o.customer else "",
        "embassy": o.embassy,
        "status": o.status,
        "created_at": o.created_at.isoformat(),
        "completed_at": o.completed_at.isoformat() if o.completed_at else None,
        "total": total,
        "signed": signed,
        "in_external": in_external,
    }


def handover_dict(h: Handover, actor_name: str = "") -> dict:
    return {
        "id": h.id,
        "order_id": h.order_id,
        "material_id": h.material_id,
        "material_no": "",  # 由调用方填充（可选）
        "event_type": h.event_type,
        "event_label": EVENT_LABELS.get(h.event_type, h.event_type),
        "from_party": h.from_party,
        "to_party": h.to_party,
        "counterparty_name": h.counterparty_name,
        "counterparty_sign": h.counterparty_sign,
        "location": h.location,
        "note": h.note,
        "embassy_receipt_no": h.embassy_receipt_no,
        "authorization_id": h.authorization_id,
        "actor_name": actor_name,
        "created_at": h.created_at.isoformat(),
    }


def authorization_dict(a) -> dict:
    return {
        "id": a.id,
        "order_id": a.order_id,
        "agent_name": a.agent_name,
        "agent_id_no": a.agent_id_no,
        "has_id_photo": bool(a.id_doc_photo_path),
        "status": a.status,
        "valid_from": a.valid_from.isoformat(),
        "valid_until": a.valid_until.isoformat(),
        "created_at": a.created_at.isoformat(),
        "revoked_at": a.revoked_at.isoformat() if a.revoked_at else None,
        "revoke_reason": a.revoke_reason,
    }
