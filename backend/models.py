# -*- coding: utf-8 -*-
"""数据模型

核心设计：
- Material（每件原件）有独立保管状态，整单状态由各件汇总，绝不"一单标记全归还"。
- HandoverEvent 为只追加流水：收件 / 递交 / 使馆退件 / 客户领回，每次双方交接各记一条，
  系统不提供任何修改或删除交接记录的接口（分批送达、改自取都只追加）。
"""
from datetime import datetime, date

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, ForeignKey, Boolean,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship

from .database import Base


# ---- 岗位角色 ----
ROLE_ADMIN = "admin"          # 管理员：全部功能
ROLE_RECEPTION = "reception"  # 前台收件岗：收件、查看自己经手件的证件照片
ROLE_HANDLER = "handler"      # 经办岗：递交/退件/领回，经手件照片
ROLE_VIEWER = "viewer"        # 只读统计岗：可看列表，不可看证件照片

# 能接触证件原件照片的岗位（"经手岗位"）
HANDLING_ROLES = {ROLE_ADMIN, ROLE_RECEPTION, ROLE_HANDLER}
ALL_ROLES = {ROLE_ADMIN, ROLE_RECEPTION, ROLE_HANDLER, ROLE_VIEWER}


# ---- 单件材料的保管状态（每件独立） ----
MAT_RECEIVED = "received"    # 已收件，在旅行社保管
MAT_SUBMITTED = "submitted"  # 已递交使馆/签证中心，外部办理中
MAT_RETURNED = "returned"    # 使馆已退件，回到旅行社待客户领回
MAT_HELD = "held"            # 客户已按件签收领回（终态）

MAT_STATES = {MAT_RECEIVED, MAT_SUBMITTED, MAT_RETURNED, MAT_HELD}

# 允许的状态流转
SUBMIT_FROM = {MAT_RECEIVED, MAT_RETURNED}   # 首次递交 / 退件后补递
EMBASSY_RETURN_FROM = {MAT_SUBMITTED}
PICKUP_FROM = {MAT_RECEIVED, MAT_RETURNED}   # 未递交直接取回 / 退件后领回

MAT_LOCATION = {
    MAT_RECEIVED: "旅行社在库保管",
    MAT_SUBMITTED: "使馆/签证中心（外部办理中）",
    MAT_RETURNED: "旅行社在库（已退件，待领回）",
    MAT_HELD: "客户已领回",
}


# ---- 交接事件类型（只追加） ----
EV_RECEIVE = "receive"            # 旅行社 <-- 客户（收件）
EV_SUBMIT = "submit"              # 旅行社 --> 使馆（递交）
EV_EMBASSY_RETURN = "embassy_return"  # 使馆 --> 旅行社（退件，可分批）
EV_PICKUP = "pickup"              # 旅行社 --> 客户（按件签收领回）

EVENT_LABEL = {
    EV_RECEIVE: "客户交件·旅行社收件",
    EV_SUBMIT: "递交使馆",
    EV_EMBASSY_RETURN: "使馆退件回社",
    EV_PICKUP: "客户领回签收",
}


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(64), nullable=False)
    role = Column(String(32), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiToken(Base):
    __tablename__ = "api_tokens"
    id = Column(Integer, primary_key=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User")


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False)
    phone = Column(String(32), nullable=False)
    id_number = Column(String(64), nullable=False)  # 证件号（PII）
    created_at = Column(DateTime, default=datetime.utcnow)
    orders = relationship("Order", back_populates="customer")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    order_no = Column(String(32), unique=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    destination = Column(String(128), nullable=False)   # 使馆/签证中心
    visa_type = Column(String(64), nullable=False)
    receipt_token = Column(String(64), unique=True, nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    completed_at = Column(DateTime, nullable=True)      # 仅当全部单件 HELD 后才允许写入
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="orders")
    materials = relationship(
        "Material", back_populates="order",
        cascade="all, delete-orphan", order_by="Material.seq_no",
    )
    events = relationship(
        "HandoverEvent", back_populates="order",
        cascade="all, delete-orphan", order_by="HandoverEvent.id",
    )
    proxy_auths = relationship(
        "ProxyAuthorization", back_populates="order",
        cascade="all, delete-orphan", order_by="ProxyAuthorization.id",
    )


class Material(Base):
    __tablename__ = "materials"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    seq_no = Column(Integer, nullable=False)          # 订单内逐件编号
    doc_type = Column(String(64), nullable=False)     # 护照 / 身份证 / 户口本 ...
    doc_name = Column(String(128), nullable=False)    # 明细描述（如护照号尾号）
    photo_path = Column(String(256), nullable=False)  # 本地存放路径
    photo_sha256 = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default=MAT_RECEIVED)
    created_at = Column(DateTime, default=datetime.utcnow)

    order = relationship("Order", back_populates="materials")
    events = relationship(
        "HandoverEvent", back_populates="material",
        cascade="all, delete-orphan", order_by="HandoverEvent.id",
    )

    __table_args__ = (
        UniqueConstraint("order_id", "seq_no", name="uq_material_order_seq"),
    )

    @property
    def item_no(self) -> str:
        return f"{self.order.order_no}-{self.seq_no:02d}"

    @property
    def location_text(self) -> str:
        return MAT_LOCATION[self.status]


class HandoverEvent(Base):
    """交接流水：只追加（append-only），不做修改/删除。"""
    __tablename__ = "handover_events"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    event_type = Column(String(32), nullable=False)
    batch_no = Column(String(40), nullable=True)        # 同批交接共享一个批次号

    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    from_party = Column(String(64), nullable=False)     # 交出方
    to_party = Column(String(64), nullable=False)       # 接收方
    counterparty_name = Column(String(64), nullable=False)  # 交接对方（使馆窗口/客户本人/代领人）
    counterparty_id = Column(String(64), nullable=True)     # 领回时签收人证件号
    sign_mode = Column(String(16), nullable=True)       # pickup: self / proxy
    proxy_auth_id = Column(Integer, ForeignKey("proxy_authorizations.id"), nullable=True)

    note = Column(Text, nullable=True)
    embassy_receipt_path = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    order = relationship("Order", back_populates="events")
    material = relationship("Material", back_populates="events")
    actor = relationship("User")
    proxy_auth = relationship("ProxyAuthorization")

    __table_args__ = (
        Index("ix_events_material", "material_id", "id"),
        Index("ix_events_batch", "batch_no"),
    )


class ProxyAuthorization(Base):
    """代领授权：限本人（姓名+证件号）、限有效期、可撤销、可限定材料范围。"""
    __tablename__ = "proxy_authorizations"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    proxy_name = Column(String(64), nullable=False)
    proxy_id_no = Column(String(64), nullable=False)
    # 逗号分隔的 material id；空串表示全部材料
    scope_material_ids = Column(Text, nullable=False, default="")
    valid_from = Column(Date, nullable=False, default=date.today)
    valid_until = Column(Date, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    note = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    order = relationship("Order", back_populates="proxy_auths")


class PhotoAccessLog(Base):
    """证件照片访问审计：谁、何时、看了哪一件（每次授权/拒绝都留痕）。"""
    __tablename__ = "photo_access_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    allowed = Column(Boolean, nullable=False)
    reason = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class SmsOutbox(Base):
    """短信发送模拟：只写出站记录，不真正发送。"""
    __tablename__ = "sms_outbox"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=True)
    kind = Column(String(32), nullable=False)
    phone = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
