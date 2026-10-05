"""FastAPI 依赖：身份认证、岗位校验、照片访问范围控制。"""
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .config import PHOTO_ALLOWED_ROLES, ROLE_ADMIN
from .database import get_db
from .models import Customer, Material, Order, User
from .security import decode_token


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少登录令牌")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效或已过期")
    user = db.get(User, payload.get("uid"))
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不可用")
    return user


def require_roles(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"岗位 {user.role} 无权执行该操作"
            )
        return user

    return checker


def get_order_or_404(order_id: int, db: Session) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "订单不存在")
    return order


def user_can_view_customer(user: User, customer: Customer) -> bool:
    """业务数据列表对内部员工可见；照片访问另行严格隔离。"""
    return user.role in PHOTO_ALLOWED_ROLES or user.role == "courier"


def assert_photo_access(user: User, customer: Customer) -> None:
    """证件照片访问授权：
    - 仅经手岗位（staff）与管理员可访问；
    - staff 只能访问自己名下客户，不得跨客户读取；
    - 配送员等其他岗位一律拒绝。
    """
    if user.role not in PHOTO_ALLOWED_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "当前岗位无权查看证件照片（仅经手岗位可访问）",
        )
    if user.role == ROLE_ADMIN:
        return
    # staff：必须是该客户的经手人
    if customer.owner_staff_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "不能跨客户读取证件资料：该客户不归当前经手人负责",
        )


def customer_for_material(db: Session, material: Material) -> Customer:
    return db.get(Order, material.order_id).customer
