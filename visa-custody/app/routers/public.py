"""客户侧公开查询：凭订单号 + 手机号查看收件凭证与每件材料当前位置。

不返回证件照片，也不要求登录，供客户自助核对。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Handover, Material, Order
from ..serializers import STATUS_LABELS

router = APIRouter(prefix="/api/public", tags=["public"])


class TrackIn(BaseModel):
    order_no: str
    phone: str


@router.post("/track")
def track(body: TrackIn, db: Session = Depends(get_db)):
    order = db.scalar(select(Order).where(Order.order_no == body.order_no))
    if not order or order.customer.phone.strip() != body.phone.strip():
        # 不区分“订单不存在”和“手机号不符”，避免枚举订单
        raise HTTPException(status.HTTP_404_NOT_FOUND, "订单号或手机号不正确")

    materials = []
    for m in sorted(order.materials, key=lambda x: x.id):
        last = (
            db.scalar(
                select(Handover)
                .where(Handover.material_id == m.id)
                .order_by(Handover.id.desc())
            )
        )
        materials.append({
            "material_no": m.material_no,
            "material_type": m.material_type,
            "status": m.status,
            "status_label": STATUS_LABELS.get(m.status, m.status),
            "last_event": last.event_type if last else None,
            "last_location": last.location if last else "",
            "last_party": f"{last.from_party} → {last.to_party}" if last else "",
            "last_time": last.created_at.isoformat() if last else None,
        })

    return {
        "order_no": order.order_no,
        "embassy": order.embassy,
        "status": order.status,
        "customer_name": order.customer.name,
        "materials": materials,
    }
