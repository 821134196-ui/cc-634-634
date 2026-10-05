"""请求 / 响应模式。"""
from datetime import datetime
from pydantic import BaseModel, Field


# ---- 认证 ----------------------------------------------------------------
class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    token: str
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    username: str
    name: str
    role: str

    class Config:
        from_attributes = True


# ---- 客户 / 订单 ----------------------------------------------------------
class CustomerIn(BaseModel):
    name: str
    phone: str
    id_doc_no: str


class CustomerOut(BaseModel):
    id: int
    name: str
    phone: str
    id_doc_no: str
    owner_staff_id: int
    owner_name: str = ""

    class Config:
        from_attributes = True


class OrderIn(BaseModel):
    customer_id: int
    embassy: str


class OrderOut(BaseModel):
    id: int
    order_no: str
    customer_id: int
    customer_name: str = ""
    embassy: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    total: int = 0
    signed: int = 0
    in_external: int = 0


# ---- 材料 ----------------------------------------------------------------
class MaterialIn(BaseModel):
    material_type: str
    description: str = ""


class MaterialOut(BaseModel):
    id: int
    material_no: str
    material_type: str
    description: str
    status: str
    has_photo: bool
    photo_url: str | None = None
    order_id: int
    created_at: datetime


# ---- 交接 ----------------------------------------------------------------
class SubmitIn(BaseModel):
    material_ids: list[int] = Field(default_factory=list)
    note: str = ""


class ReturnIn(BaseModel):
    material_ids: list[int] = Field(default_factory=list)
    note: str = ""


class DeliverIn(BaseModel):
    material_ids: list[int] = Field(default_factory=list)
    courier_name: str = ""
    note: str = ""


class SelfPickupIn(BaseModel):
    material_ids: list[int] = Field(default_factory=list)
    note: str = ""


class SignIn(BaseModel):
    material_ids: list[int] = Field(default_factory=list)
    # customer=本人自取；agent=代领人
    receiver_kind: str = "customer"
    receiver_name: str
    receiver_id_no: str = ""
    sign: str  # 客户按件签收（签名/签收码）
    note: str = ""


class HandoverOut(BaseModel):
    id: int
    order_id: int
    material_id: int | None
    event_type: str
    from_party: str
    to_party: str
    counterparty_name: str
    counterparty_sign: str
    location: str
    note: str
    embassy_receipt_no: str
    authorization_id: int | None
    actor_name: str = ""
    created_at: datetime

    class Config:
        from_attributes = True


# ---- 授权 ----------------------------------------------------------------
class AuthorizationIn(BaseModel):
    agent_name: str
    agent_id_no: str
    valid_from: datetime
    valid_until: datetime


class AuthorizationOut(BaseModel):
    id: int
    order_id: int
    agent_name: str
    agent_id_no: str
    status: str
    valid_from: datetime
    valid_until: datetime
    created_at: datetime
    revoked_at: datetime | None = None
    revoke_reason: str = ""

    class Config:
        from_attributes = True


class RevokeIn(BaseModel):
    reason: str = ""


class SimpleResult(BaseModel):
    ok: bool = True
    message: str = ""
    data: dict | None = None


LoginOut.model_rebuild()
