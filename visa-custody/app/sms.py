"""短信发送模拟：落库 SmsLog，并在控制台打印。"""
from sqlalchemy.orm import Session

from .models import SmsLog


def send_sms(db: Session, customer, content: str, kind: str) -> SmsLog:
    log = SmsLog(
        customer_id=customer.id,
        phone=customer.phone,
        content=content,
        kind=kind,
    )
    db.add(log)
    db.flush()
    print(f"[模拟短信] -> {customer.name}({customer.phone}) [{kind}] {content}")
    return log
