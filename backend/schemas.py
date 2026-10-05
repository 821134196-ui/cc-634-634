# -*- coding: utf-8 -*-
"""Pydantic 请求/响应结构"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---- 认证 ----
class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    token: str
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str

    class Config:
        from_attributes = True


# ---- 客户 / 订单 ----
class CustomerOut(BaseModel):
    id: int
    name: str
    phone: str
    id_number: str

    class Config:
        from_attributes = True


class EventOut(BaseModel):
    id: int
    material_id: int
    event_type: str
    event_type_label: str
    batch_no: Optional[str]
    from_party: str
    to_party: str
    counterparty_name: str
    counterparty_id: Optional[str]
    sign_mode: Optional[str]
    note: Optional[str]
    has_embassy_receipt: bool
    actor_name: str
    created_at: datetime


class MaterialOut(BaseModel):
    id: int
    seq_no: int
    item_no: str
    doc_type: str
    doc_name: str
    status: str
    location_text: str
    has_photo: bool
    events: list[EventOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


class OrderSummary(BaseModel):
    id: int
    order_no: str
    customer: CustomerOut
    destination: str
    visa_type: str
    created_at: datetime
    completed: bool
    total_count: int
    held_count: int
    submitted_count: int
    returned_count: int
    received_count: int
    missing_count: int  # 尚未领回的件数
    current_stage: str


class OrderDetail(OrderSummary):
    receipt_token: str
    materials: list[MaterialOut]
    events: list[EventOut]
    proxy_auths: list["ProxyAuthOut"]


# ---- 交接动作 ----
class SubmitIn(BaseModel):
    material_ids: list[int] = Field(min_length=1)
    counterparty_name: str = Field(min_length=1, max_length=64)  # 使馆/签证中心窗口
    note: Optional[str] = None


class EmbassyReturnIn(BaseModel):
    material_ids: list[int] = Field(min_length=1)
    counterparty_name: str = Field(min_length=1, max_length=64)
    note: Optional[str] = None


class PickupIn(BaseModel):
    material_ids: list[int] = Field(min_length=1)
    sign_mode: str  # self / proxy
    delivery_mode: str = "office"  # office 自取 / courier 分批送达
    signer_name: str = Field(min_length=1, max_length=64)
    signer_id_no: Optional[str] = None
    proxy_auth_id: Optional[int] = None
    note: Optional[str] = None


# ---- 代领授权 ----
class ProxyAuthIn(BaseModel):
    proxy_name: str = Field(min_length=1, max_length=64)
    proxy_id_no: str = Field(min_length=1, max_length=64)
    scope_material_ids: list[int] = Field(default_factory=list)  # 空=全部
    valid_from: date
    valid_until: date
    note: Optional[str] = None


class ProxyAuthOut(BaseModel):
    id: int
    proxy_name: str
    proxy_id_no: str
    scope_material_ids: list[int]
    valid_from: date
    valid_until: date
    revoked: bool
    valid_now: bool
    note: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class SmsOut(BaseModel):
    id: int
    kind: str
    phone: str
    content: str
    created_at: datetime
    order_id: int
    material_id: Optional[int]

    class Config:
        from_attributes = True


LoginOut.model_rebuild()
OrderDetail.model_rebuild()
