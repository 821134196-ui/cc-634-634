"""SQLAlchemy 模型。

核心设计：
- Material.status 记录每件材料的粗粒度位置；精确交接经过全部落在 Handover。
- Handover 只追加（append-only），不提供修改/删除接口；分批送达、改自取、
  部分退件都通过新增交接记录体现，最初收件单永不被改写。
- 订单是否完成只取决于“是否每一件都已签收”，不存在整单一键归还。
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# ---- 材料状态（当前位置粗粒度） -----------------------------------------
STATUS_RECEIVED = "received"      # 已收件，在旅行社
STATUS_SUBMITTED = "submitted"    # 已递交，在使馆（外部办理中）
STATUS_RETURNED = "returned"      # 使馆退件，已回到旅行社 / 待自取
STATUS_DELIVERING = "delivering"  # 配送中
STATUS_SIGNED = "signed"          # 客户/代领人已签收（终态）

MATERIAL_STATUSES = {
    STATUS_RECEIVED,
    STATUS_SUBMITTED,
    STATUS_RETURNED,
    STATUS_DELIVERING,
    STATUS_SIGNED,
}

# ---- 交接事件类型 --------------------------------------------------------
EVENT_RECEIVE = "receive"                 # 收件（客户 -> 旅行社）
EVENT_SUBMIT = "submit"                   # 递交使馆（旅行社 -> 使馆）
EVENT_EMBASSY_RETURN = "embassy_return"   # 使馆退件（使馆 -> 旅行社，可部分）
EVENT_ASSIGN_COURIER = "assign_courier"   # 交配送员送达（旅行社 -> 配送员）
EVENT_SELF_PICKUP = "self_pickup"         # 改为客户自取（追加记录）
EVENT_SIGN = "sign"                       # 签收看管移交（-> 客户/代领人）

# 每种事件允许的来源状态
EVENT_FROM_STATUSES = {
    EVENT_RECEIVE: None,  # 仅建件时使用
    EVENT_SUBMIT: {STATUS_RECEIVED},
    EVENT_EMBASSY_RETURN: {STATUS_SUBMITTED},
    EVENT_ASSIGN_COURIER: {STATUS_RETURNED},
    EVENT_SELF_PICKUP: {STATUS_RETURNED, STATUS_DELIVERING},
    EVENT_SIGN: {STATUS_RETURNED, STATUS_DELIVERING},
}

EVENT_TARGET_STATUS = {
    EVENT_SUBMIT: STATUS_SUBMITTED,
    EVENT_EMBASSY_RETURN: STATUS_RETURNED,
    EVENT_ASSIGN_COURIER: STATUS_DELIVERING,
    EVENT_SELF_PICKUP: STATUS_RETURNED,
    EVENT_SIGN: STATUS_SIGNED,
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    phone: Mapped[str] = mapped_column(String(32))
    id_doc_no: Mapped[str] = mapped_column(String(64))
    # 经手岗位（责任前台/收件员）；只有其本人（及管理员）能看该客户证件照片
    owner_staff_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    owner: Mapped["User"] = relationship()
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    embassy: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # active=办理中；completed 仅在全部单件均 signed 后由系统置位
    status: Mapped[str] = mapped_column(String(16), default="active")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    customer: Mapped["Customer"] = relationship(back_populates="orders")
    materials: Mapped[list["Material"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    handovers: Mapped[list["Handover"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    authorizations: Mapped[list["Authorization"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    material_no: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    material_type: Mapped[str] = mapped_column(String(64))  # 护照/户口本/在职证明...
    description: Mapped[str] = mapped_column(String(255), default="")
    photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_RECEIVED)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    order: Mapped["Order"] = relationship(back_populates="materials")


class Handover(Base):
    """一次双方交接记录。只追加，不修改。"""

    __tablename__ = "handovers"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    material_id: Mapped[int | None] = mapped_column(
        ForeignKey("materials.id"), nullable=True, index=True
    )  # 递交/退件可一次覆盖多件，批量事件用 order 级 + 每件各写一条
    event_type: Mapped[str] = mapped_column(String(32))
    from_party: Mapped[str] = mapped_column(String(64))
    to_party: Mapped[str] = mapped_column(String(64))
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    # 交接对方：客户本人/代领人/使馆窗口/配送员
    counterparty_name: Mapped[str] = mapped_column(String(64), default="")
    # 电子签收：签名或签收码；签收件必填
    counterparty_sign: Mapped[str] = mapped_column(String(128), default="")
    location: Mapped[str] = mapped_column(String(128), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    # 使馆回执号（递交时模拟生成）
    embassy_receipt_no: Mapped[str] = mapped_column(String(64), default="")
    # 代领所使用的授权
    authorization_id: Mapped[int | None] = mapped_column(
        ForeignKey("authorizations.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    order: Mapped["Order"] = relationship(back_populates="handovers")


class Authorization(Base):
    """代领授权书。"""

    __tablename__ = "authorizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(64))
    agent_id_no: Mapped[str] = mapped_column(String(64))
    id_doc_photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/revoked
    valid_from: Mapped[datetime] = mapped_column(DateTime)
    valid_until: Mapped[datetime] = mapped_column(DateTime)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoke_reason: Mapped[str] = mapped_column(String(255), default="")

    order: Mapped["Order"] = relationship(back_populates="authorizations")


class SmsLog(Base):
    """短信模拟发送记录。"""

    __tablename__ = "sms_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    phone: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
