from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Handover, SmsLog, User

router = APIRouter(prefix="/api", tags=["logs"])


@router.get("/sms-logs")
def sms_logs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(SmsLog).order_by(SmsLog.id.desc()).limit(100)).all()
    return [
        {
            "id": r.id,
            "customer_id": r.customer_id,
            "phone": r.phone,
            "kind": r.kind,
            "content": r.content,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/orders/{order_id}/receipts")
def embassy_receipts(order_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """使馆回执：列出该订单所有递交批次回执号（模拟使馆回执）。"""
    rows = db.scalars(
        select(Handover)
        .where(Handover.order_id == order_id, Handover.embassy_receipt_no != "")
        .order_by(Handover.id)
    ).all()
    seen = {}
    for h in rows:
        seen.setdefault(h.embassy_receipt_no, h.created_at)
    return [
        {"embassy_receipt_no": no, "created_at": ts.isoformat()}
        for no, ts in seen.items()
    ]
