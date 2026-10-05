from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import ROLE_ADMIN, ROLE_STAFF
from ..database import get_db
from ..deps import get_current_user, require_roles
from ..models import Customer, User
from ..schemas import CustomerIn

router = APIRouter(prefix="/api/customers", tags=["customers"])


def customer_out(c: Customer, owner_name: str = "") -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "phone": c.phone,
        "id_doc_no": c.id_doc_no,
        "owner_staff_id": c.owner_staff_id,
        "owner_name": owner_name,
    }


@router.get("")
def list_customers(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Customer).order_by(Customer.id)).all()
    owner_names = {u.id: u.name for u in db.scalars(select(User)).all()}
    return [customer_out(c, owner_names.get(c.owner_staff_id, "")) for c in rows]


@router.post("", status_code=201)
def create_customer(
    body: CustomerIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(ROLE_ADMIN, ROLE_STAFF)),
):
    # 经手岗位新建客户时自动归属本人；管理员建客户归属管理员（管理员可见全部）
    owner_id = user.id
    c = Customer(
        name=body.name,
        phone=body.phone,
        id_doc_no=body.id_doc_no,
        owner_staff_id=owner_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return customer_out(c, user.name)
